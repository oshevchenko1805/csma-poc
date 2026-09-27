"""metrics.spoof_rate_probe — executable rules of B0_PREREGISTRATION.md."""
import math

import pytest

from metrics import spoof_rate_probe as B


def test_levels_match_preregistration_table():
    got = {l: B.level_params(l) for l in B.LEVELS}
    assert got["L30"]["r"] == pytest.approx(0.02)
    assert got["L30"]["tau_s"] == pytest.approx(1.65, abs=0.01)
    assert got["L10"]["tau_s"] == pytest.approx(5.0, abs=0.05)
    assert got["L3"]["tau_s"] == pytest.approx(16.7, abs=0.1)
    assert got["L1"]["tau_s"] == pytest.approx(50.0, abs=0.1)
    assert B.model_offset(180.0, got["L1"]["r"]) == pytest.approx(48.6, abs=0.05)
    assert B.model_offset(300.0, got["L0.5"]["r"]) == pytest.approx(47.5, abs=0.05)
    assert got["L0.5"]["window_s"] == 300.0


def test_model_offset_at_tau_and_2tau():
    r = B.level_params("L3")["r"]
    tau = B.level_params("L3")["tau_s"]
    assert B.model_offset(tau, r) == pytest.approx(50 * (1 - math.e ** -1), abs=1e-6)
    assert B.model_offset(2 * tau, r) == pytest.approx(50 * (1 - math.e ** -2), abs=1e-6)
    assert B.model_offset(-1.0, r) == 0.0


def test_step_budget_is_cross_check_budget_per_announcement():
    assert B.STEP_BUDGET_M == 35.0


def test_announce_period_matches_monitor_default():
    monitor = pytest.importorskip("runners.monitor")
    assert B.ANNOUNCE_PERIOD_S == monitor.Monitor.DEFAULT_PEER_PUBLISH_PERIOD_SEC


def test_interp_and_gap():
    s = [(0.0, 0.0, 0.0), (1.0, 10.0, 20.0), (5.0, 0.0, 0.0)]
    assert B.interp(s, 0.5) == (5.0, 10.0)
    assert B.interp(s, 3.0) is None          # gap 4 s > 1 s
    assert B.interp(s, -1.0) is None


def _flight(offset_fn, t_inject=100.0, dur=200.0, speed=5.0):
    """Synthetic flight: UAV flies north at `speed`; belief = truth +
    offset_fn(t_rel) + constant frame offset (3, -2)."""
    truth, belief = [], []
    t = 90.0
    while t <= t_inject + dur:
        n = speed * (t - 90.0)
        truth.append((t, n, 0.0))
        off = offset_fn(t - t_inject) if t >= t_inject else 0.0
        belief.append((t + 0.01, n + 3.0 + off + speed * 0.01, -2.0))
        t += 0.2
    return truth, belief


def test_nav_error_removes_frame_offset_and_follows_attack():
    truth, belief = _flight(lambda tr: 50.0 if tr >= 8.0 else 0.0)
    nav = B.nav_error_series(truth, belief, 100.0)
    assert B.value_at(nav, 2.0) == pytest.approx(0.0, abs=0.1)
    assert B.value_at(nav, 50.0) == pytest.approx(50.0, abs=0.1)
    assert B.max_step(nav, 1.0) == pytest.approx(50.0, abs=0.5)   # one jump


def test_gradual_drift_has_small_max_step():
    truth, belief = _flight(lambda tr: min(50.0, tr * 1.0))
    nav = B.nav_error_series(truth, belief, 100.0)
    assert B.max_step(nav, 1.0) == pytest.approx(1.0, abs=0.1)
    assert B.max_step(nav, 1.0) < B.STEP_BUDGET_M


def test_spoof_offset_series_against_moving_truth():
    t_inject = 100.0
    r = B.level_params("L10")["r"]
    truth = [(t / 5, 5.0 * t / 5, 0.0) for t in range(450, 1200)]   # 90..240 s
    lat0 = 47.0
    gps = []
    for k in range(95 * 30, 200 * 30):
        t = k / 30
        north = 5.0 * t + 7.0 + B.model_offset(t - t_inject, r)     # +7 m frame
        gps.append((t, lat0 + math.degrees(north / B._R_EARTH), 8.0))
    sp = B.spoof_offset_series(gps, truth, t_inject)
    tau = B.level_params("L10")["tau_s"]
    assert B.value_at(sp, -2.0) == pytest.approx(0.0, abs=0.05)
    assert B.value_at(sp, tau) == pytest.approx(31.6, abs=0.3)


def test_replay_gps_needs_three_consecutive_after_injection():
    est = [(100.0 + i, 0.2) for i in range(5)]
    est += [(105.0, 1.5), (106.0, 1.5), (107.0, 0.3), (108.0, 1.5),
            (109.0, 1.5), (110.0, 1.5)]
    r = B.replay_gps(est, t_inject=100.0)
    assert r["t_gps_s"] == pytest.approx(10.0)
    assert r["gps_alarm_before_injection"] is False


def _gpi(north_fn, t0=90.0, t1=200.0, lat0=47.0):
    out, t = [], t0
    while t <= t1:
        out.append((t, lat0 + math.degrees(north_fn(t) / B._R_EARTH), 8.0))
        t += 0.1
    return out


def test_announcements_one_per_period_latest_sample():
    gpi = _gpi(lambda t: 0.0, 90.0, 95.0)
    ann = B.announcements(gpi)
    assert len(ann) == 5
    assert all(abs(a[0] - (90.0 + k + 1)) < 0.11 for k, a in enumerate(ann))


def test_cross_check_fires_on_jump_not_on_slow_drift():
    jump = _gpi(lambda t: 5.0 * (t - 90) + (50.0 if t >= 107.5 else 0.0))
    r = B.replay_cross_check(jump, t_inject=100.0)
    assert r["t_cc_s"] == pytest.approx(8.0, abs=0.15)
    slow = _gpi(lambda t: 5.0 * (t - 90) + max(0.0, t - 100.0))   # +1 m/s
    assert B.replay_cross_check(slow, t_inject=100.0)["t_cc_s"] is None


def _summary(**kw):
    s = {"spoof_at_window_end_m": 48.0, "nav_error_end_m": 48.0,
         "t_gps_s": None, "t_cc_s": None}
    s.update(kw)
    return s


def test_classify_flight():
    assert B.classify_flight(_summary()) == "BLIND"
    assert B.classify_flight(_summary(t_cc_s=7.5)) == "DETECTED"
    assert B.classify_flight(_summary(nav_error_end_m=3.0)) == "NOT_LANDED"
    assert B.classify_flight(_summary(spoof_at_window_end_m=1.0)) == "INVALID"
    assert B.classify_flight(_summary(), error="boom") == "INVALID"
    assert B.detected_by(_summary(t_gps_s=3.0)) == "gps only"
    assert B.detected_by(_summary(t_gps_s=3.0, t_cc_s=7.0)) == "both"


def test_classify_level_agreement_and_majority():
    assert B.classify_level(["BLIND", "BLIND"]) == "BLIND"
    assert B.classify_level(["BLIND", "DETECTED"]) == "FLY_AGAIN"
    assert B.classify_level(["BLIND", "DETECTED", "BLIND"]) == "BLIND"
    assert B.classify_level(["BLIND", "INVALID"]) == "FLY_AGAIN"


def test_control_ok():
    good = {"t_jump_s": 7.5, "t_gps_s": 3.0}
    assert B.control_ok([good, good])
    assert not B.control_ok([good, {"t_jump_s": 12.0, "t_gps_s": 3.0}])
    assert not B.control_ok([good])


def test_decision_rule():
    d = {"L30": "DETECTED", "L10": "DETECTED", "L3": "BLIND", "L1": "BLIND"}
    assert B.decision(d).startswith("BLIND ZONE: v_blind = 3")
    d = {"L30": "DETECTED", "L10": "DETECTED", "L3": "DETECTED", "L1": "DETECTED"}
    assert B.decision(d).startswith("EXTEND")
    d["L0.5"] = "DETECTED"
    assert B.decision(d).startswith("NO BLIND ZONE")
    d["L3"] = "FLY_AGAIN"
    assert B.decision(d).startswith("INCOMPLETE")


# --- end-to-end: log files -> analyze -> report (scripts/probe_spoof_rate.py)

def _load_script():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "scripts" / "probe_spoof_rate.py"
    spec = importlib.util.spec_from_file_location("probe_spoof_rate", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_flight(root, name, level, jump, t0=1000.0, t_inject=1030.0):
    """Synthetic flight at 5 Hz: UAV flies north at 5 m/s. GPS follows the
    patch model; belief jumps by 50 m at +7.5 s (jump=True) or follows the
    GPS offset gradually (jump=False); pos_horiz_ratio high on +1..+6 s
    only when jump=True."""
    import json
    d = root / name
    d.mkdir()
    p = B.level_params(level)
    lat0 = 47.0
    traj, mav = [], []
    t = t0
    while t <= t_inject + p["window_s"] + 5:
        tr = t - t_inject
        n = 5.0 * (t - t0)
        traj.append({"t_wall": t, "uav_id": "uav_0", "x": 0.0, "y": n})
        off = B.model_offset(tr, p["r"])
        bel = (50.0 if tr >= 7.5 else 0.0) if jump else off
        g = n + off
        mav.append({"t_wall": t, "type": "LOCAL_POSITION_NED", "x": n + bel + 2.0,
                    "y": -1.0, "z": -20.0})
        mav.append({"t_wall": t, "type": "GPS_RAW_INT", "fix_type": 3,
                    "lat": round((lat0 + math.degrees(g / B._R_EARTH)) * 1e7),
                    "lon": 80000000})
        mav.append({"t_wall": t, "type": "GLOBAL_POSITION_INT", "relative_alt": 20000,
                    "lat": round((lat0 + math.degrees((n + bel) / B._R_EARTH)) * 1e7),
                    "lon": 80000000})
        if abs(t - round(t)) < 1e-6:
            hi = jump and 1.0 <= tr <= 6.0
            mav.append({"t_wall": t, "type": "ESTIMATOR_STATUS",
                        "pos_horiz_ratio": 1.5 if hi else 0.2, "vel_ratio": 0.1})
        t = round(t + 0.2, 6)
    (d / "trajectory.jsonl").write_text("\n".join(json.dumps(r) for r in traj))
    (d / "mav.jsonl").write_text("\n".join(json.dumps(r) for r in mav))
    (d / "meta.json").write_text(json.dumps({"level": level, "t_inject": t_inject,
                                             "error": None}))


def test_report_end_to_end(tmp_path):
    S = _load_script()
    _write_flight(tmp_path, "L30_1", "L30", jump=True, t0=1000.0, t_inject=1030.0)
    _write_flight(tmp_path, "L30_2", "L30", jump=True, t0=5000.0, t_inject=5030.0)
    _write_flight(tmp_path, "L1_1", "L1", jump=False, t0=9000.0, t_inject=9030.0)
    _write_flight(tmp_path, "L1_2", "L1", jump=False, t0=13000.0, t_inject=13030.0)
    rep = S.report(tmp_path)
    f = {x["dir"]: x for x in rep["flights"]}
    assert f["L30_1"]["class"] == "DETECTED" and f["L30_1"]["detected_by"] == "both"
    assert f["L30_1"]["t_jump_s"] == pytest.approx(7.6, abs=0.15)
    assert f["L30_1"]["t_gps_s"] == pytest.approx(3.0, abs=0.01)
    assert f["L30_1"]["ramp_ok"] is True
    assert f["L1_1"]["class"] == "BLIND"
    assert f["L1_1"]["max_step_1s_m"] < B.STEP_BUDGET_M
    assert f["L1_1"]["harm_at_alarm_m"] == pytest.approx(48.6, abs=0.5)
    assert rep["control_ok"] is True
    assert rep["levels"] == {"L30": "DETECTED", "L1": "BLIND"}
    assert rep["decision"].startswith("BLIND ZONE: v_blind = 1")
    assert (tmp_path / "b0_report.json").exists()
