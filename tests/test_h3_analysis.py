"""metrics.h3_analysis — the pre-registered H3 rules (H3_PREREGISTRATION.md)."""
import json
import math

import pytest

from detectors.ranging import RangingConsistencyDetector
from metrics import h3_analysis as h3
from metrics.spoof_rate_probe import level_params

T0 = 1000.0          # t_target_set
MARK = T0 - 0.3      # runner's inject_start marker (before the OFF_N write)
LAT0, LON0 = 47.3977, 8.5456
M_PER_DEG = math.radians(1.0) * 6_371_000.0


# --- synthetic flight ---------------------------------------------------------

def _summary(attack="gps_spoofing", policy="detect_only", rate=0.0006667,
             t_target=T0, rate_ok=True, error=None, seed=7, arch="C"):
    ev = {"injection_confirmed": True}
    if attack != "none":
        ev.update(spoof_rate=rate, rate_confirmed=rate_ok, t_target_set=t_target)
    return {"run_id": f"run_{attack}_{policy}", "architecture": arch,
            "attack_name": attack, "recovery_settings": {"policy": policy},
            "attack_evidence": {} if attack == "none" else {"gps_spoofing": ev},
            "range_source": {"model": "simulated_uwb", "seed": seed},
            "error": error}


def _marker(phase, t):
    return {"event_type": "attack", "phase": phase, "timestamp": t,
            "target_uav": "uav_0"}


def _sec(detector, t, target="uav_0", monitor="uav_1", **ev):
    e = {"event_type": "security", "detector": detector, "timestamp": t,
         "target_uav": target, "source": f"monitor_{monitor}", "evidence": dict(ev)}
    if detector == "ranging":
        e["evidence"].update(monitor_uav=monitor, theta_m=h3.THETA_M,
                             theta_ok_m=h3.THETA_OK_M, sustain=h3.SUSTAIN,
                             path="self" if monitor == target else "peer")
    return e


def _ack(t, ok=True, action="hold_zero_velocity"):
    return {"event_type": "recovery_ack", "timestamp": t, "target_uav": "uav_0",
            "success": ok, "action": action}


def _series(err_rate=0.65, spoof_m=50.0, v_east=5.0, t_from=-60.0, t_to=125.0,
            hold_after=None):
    """uav_0 flies east at v_east (truth); belief = truth + err_rate * t north
    after T0; GPS carries the full spoof offset after T0. hold_after: truth
    stops at T0 + hold_after (a hold action)."""
    truth, belief, vel, gps = [], [], [], []
    t = t_from
    while t <= t_to + 1e-9:
        tw = T0 + t
        te = t if hold_after is None else min(t, hold_after)
        east = v_east * te
        ve = v_east if (hold_after is None or t < hold_after) else 0.0
        e = err_rate * t if t > 0 else 0.0
        truth.append((tw, 0.0, east))
        belief.append((tw, e, east))
        vel.append((tw, 0.0, ve))
        off = spoof_m if t > 0 else 0.0
        gps.append((tw, LAT0 + off / M_PER_DEG, LON0))
        t += 0.1
    return truth, belief, vel, gps


def _flight(summary, events, **kw):
    truth, belief, vel, gps = _series(**kw)
    return h3.analyse_flight(summary, events, truth, belief, vel, gps)


def _l1_events(t_peer=9.0, t_self=10.0, extra=()):
    ev = [_marker("inject_start", MARK), _marker("inject_end", MARK + 130.0)]
    if t_peer is not None:
        ev.append(_sec("ranging", T0 + t_peer, monitor="uav_1"))
        ev.append(_sec("ranging", T0 + t_peer + 0.4, monitor="uav_2"))
    if t_self is not None:
        ev.append(_sec("ranging", T0 + t_self, monitor="uav_0"))
    return ev + list(extra)


# --- constants ---------------------------------------------------------------

def test_constants_frozen_and_match_detector():
    assert (h3.THETA_M, h3.THETA_OK_M, h3.SUSTAIN) == (1.8, 1.3, 3)
    assert h3.H_MAX_M == pytest.approx(6.8)
    assert h3.WINDOW_S == 120.0
    assert h3.THETA_M == RangingConsistencyDetector.DEFAULT_THETA_M
    assert h3.THETA_OK_M == RangingConsistencyDetector.DEFAULT_THETA_OK_M
    assert h3.SUSTAIN == RangingConsistencyDetector.DEFAULT_SUSTAIN


def test_level_rates_match_b0_model():
    for name, r in h3.LEVEL_RATES.items():
        assert r == pytest.approx(level_params(name)["r"], rel=1e-3)


def test_design_is_20_flights():
    assert sum(h3.PLANNED.values()) == 20
    assert set(h3.PLANNED) == set(h3.SERIES)
    assert h3.PLANNED["L1@detect_only"] == 5 and h3.PLANNED["none@detect_only"] == 3


# --- cells -------------------------------------------------------------------

@pytest.mark.parametrize("rate,level", [(0.02, "L30"), (0.006667, "L10"),
                                        (1 / 1500, "L1"), (0.002, "L3"),
                                        (0.01, None), (None, None)])
def test_level_of_rate(rate, level):
    assert h3.level_of_rate(rate) == level


def test_cell_of():
    assert h3.cell_of(_summary()) == "L1@detect_only"
    assert h3.cell_of(_summary(policy="trust_aware")) == "L1@trust_aware"
    assert h3.cell_of(_summary(attack="none")) == "none@detect_only"
    assert h3.cell_of(_summary(attack="detector_takeout+gps_spoofing")) == "DT+L1@detect_only"
    assert h3.cell_of(_summary(rate=0.01)) == "L?@detect_only"


# --- inclusion (never on outcomes) ------------------------------------------

def test_included_flight_uses_t_target_set_not_marker():
    r = _flight(_summary(), _l1_events())
    assert r["included"] and r["exclusion_reason"] is None
    assert r["inject_lag_s"] == pytest.approx(0.3)
    assert r["t_rng_peer_s"] == pytest.approx(9.0)


@pytest.mark.parametrize("kw,needle", [
    ({"error": "boom"}, "run error"),
    ({"t_target": None}, "t_target_set"),
    ({"rate_ok": None}, "rate not confirmed"),
    ({"rate_ok": False}, "rate not confirmed"),
])
def test_exclusion_reasons(kw, needle):
    r = _flight(_summary(**kw), _l1_events())
    assert not r["included"] and needle in r["exclusion_reason"]


def test_excluded_when_spoof_not_seen_in_gps():
    r = _flight(_summary(), _l1_events(), spoof_m=3.0)
    assert not r["included"] and "injection not observed" in r["exclusion_reason"]


def test_outcomes_never_exclude():
    ev = _l1_events(t_peer=None, t_self=None,
                    extra=[_sec("ranging", T0 + 5.0, target="uav_1", monitor="uav_0")])
    r = _flight(_summary(), ev, err_rate=0.9)
    assert r["included"]
    assert r["t_rng_s"] is None and r["misattributions"] == 1 and r["passes"] is False


def test_no_attack_included_without_injection_check():
    r = _flight(_summary(attack="none"), [_marker("inject_start", MARK)], spoof_m=0.0)
    assert r["included"] and r["false_alarms"] == 0


# --- metrics -----------------------------------------------------------------

def test_l1_metrics_and_pass():
    r = _flight(_summary(), _l1_events())
    assert r["t_rng_self_s"] == pytest.approx(10.0)
    assert r["t_rng_s"] == pytest.approx(9.0)
    assert r["harm_at_alarm_m"] == pytest.approx(0.65 * 9.0, abs=0.05)
    assert r["t_gps_s"] is None and r["t_cc_s"] is None
    assert r["t_jump_s"] == pytest.approx(25.0 / 0.65, abs=0.2)
    assert r["nav_error_end_m"] == pytest.approx(0.65 * 115.0, abs=0.2)
    assert r["misattributions"] == 0 and r["passes"] is True


def test_harm_over_h_max_fails():
    r = _flight(_summary(), _l1_events(), err_rate=0.9)   # 8.1 m at 9 s
    assert r["harm_at_alarm_m"] > h3.H_MAX_M and r["passes"] is False


def test_self_alarm_counts_toward_t_rng():
    r = _flight(_summary(), _l1_events(t_peer=None, t_self=8.0))
    assert r["t_rng_peer_s"] is None and r["t_rng_s"] == pytest.approx(8.0)


def test_alarms_outside_window_or_before_injection_ignored():
    ev = _l1_events(t_peer=None, t_self=None, extra=[
        _sec("ranging", T0 - 2.0), _sec("ranging", T0 + 121.0),
        _sec("gps", T0 - 1.0, monitor="uav_0")])
    r = _flight(_summary(), ev)
    assert r["t_rng_s"] is None and r["t_gps_s"] is None
    assert r["ranging_alarms_before_injection"] == 1


def test_misattribution_split_by_monitor():
    ev = _l1_events(extra=[_sec("ranging", T0 + 6.0, target="uav_1", monitor="uav_0"),
                           _sec("ranging", T0 + 7.0, target="uav_2", monitor="uav_1")])
    r = _flight(_summary(), ev)
    assert (r["misattributions"], r["misattr_by_victim_monitor"],
            r["misattr_by_peer_monitors"]) == (2, 1, 1)
    assert r["passes"] is False


def test_v1_alarms_recorded():
    ev = _l1_events(extra=[_sec("gps", T0 + 3.0, monitor="uav_0"),
                           _sec("cross_check", T0 + 7.5)])
    r = _flight(_summary(), ev)
    assert r["t_gps_s"] == pytest.approx(3.0) and r["t_cc_s"] == pytest.approx(7.5)


def test_no_attack_false_alarms_whole_flight():
    ev = [_marker("inject_start", MARK), _sec("ranging", MARK - 50.0),
          _sec("ranging", MARK + 30.0, target="uav_2", monitor="uav_0")]
    r = _flight(_summary(attack="none"), ev)
    assert r["false_alarms"] == 2


def test_config_problems():
    s = _summary(arch="B")
    s.pop("range_source")
    bad = _sec("ranging", T0 + 9.0)
    bad["evidence"]["theta_m"] = 1.6
    probs = h3.config_problems(s, [bad])
    assert len(probs) == 3


def test_window_short_reported():
    ev = _l1_events()
    ev[1] = _marker("inject_end", MARK + 120.0)
    r = _flight(_summary(), ev)
    assert r["window_short_s"] == pytest.approx(0.3)


# --- S3 ----------------------------------------------------------------------

def test_s3_hold_drift_creep_vel_err():
    ev = _l1_events(extra=[_ack(T0 + 9.1)])
    r = _flight(_summary(policy="trust_aware"), ev, hold_after=9.1)
    assert r["action_ok"] and r["t_action_s"] == pytest.approx(9.1)
    assert r["drift_itt_m"] == pytest.approx(0.0, abs=0.6)
    assert r["creep_mps"] == pytest.approx(0.0, abs=1e-6)
    assert r["vel_err_mps"] == pytest.approx(0.0, abs=1e-6)


def test_s3_vel_err_sees_ekf_velocity_error():
    ev = _l1_events(extra=[_ack(T0 + 9.1)])
    truth, belief, vel, gps = _series(hold_after=9.1)
    vel = [(t, 0.3, ve) for t, _vn, ve in vel]         # EKF thinks 0.3 m/s north
    r = h3.analyse_flight(_summary(policy="trust_aware"), ev, truth, belief, vel, gps)
    assert r["vel_err_mps"] == pytest.approx(0.3, abs=1e-6)


def test_s3_failed_action_is_inf_for_acting_arm_only():
    ev = _l1_events(extra=[_ack(T0 + 9.1, ok=False)])
    assert _flight(_summary(policy="proportionate"), ev)["drift_itt_m"] == math.inf
    assert _flight(_summary(policy="detect_only"), ev)["drift_itt_m"] is None


# --- decision ------------------------------------------------------------------

def _row(cell, **kw):
    r = {"run_id": kw.pop("rid", f"{cell}-{id(kw)}"), "cell": cell, "included": True,
         "config_problems": [], "range_seed": kw.pop("seed", None)}
    r.update(kw)
    return r


def _l1(n_pass=5, n=5, harm=5.9, detect=None, **kw):
    detect = n if detect is None else detect
    rows = []
    for i in range(n):
        det = i < detect
        rows.append(_row("L1@detect_only", rid=f"l1_{i}", seed=i,
                         t_rng_s=9.0 if det else None,
                         harm_at_alarm_m=harm if det else None,
                         passes=i < n_pass, t_gps_s=None, t_cc_s=None, **kw))
    return rows


def _na(fa=0):
    return [_row("none@detect_only", rid=f"na_{i}", seed=100 + i,
                 false_alarms=fa if i == 0 else 0) for i in range(3)]


def test_confirmed():
    v = h3.verdict(_l1() + _na())
    assert v["H3"] == "CONFIRMED"
    lo, hi = v["L1"]["wilson95"]
    assert v["L1"]["passes"] == 5 and lo == pytest.approx(0.566, abs=0.01) and hi == 1.0


@pytest.mark.parametrize("k", [3, 4])
def test_partial_3_or_4(k):
    assert h3.verdict(_l1(n_pass=k) + _na())["H3"] == "PARTIAL"


def test_partial_all_detect_but_harm_over():
    assert h3.verdict(_l1(n_pass=0, harm=7.5) + _na())["H3"] == "PARTIAL"


def test_not_confirmed_low_pass():
    assert h3.verdict(_l1(n_pass=2, detect=2) + _na())["H3"] == "NOT CONFIRMED"


def test_not_confirmed_on_any_false_alarm():
    assert h3.verdict(_l1() + _na(fa=1))["H3"] == "NOT CONFIRMED"


def test_not_applicable_when_v1_fires_at_l1():
    rows = _l1() + _na()
    rows[2]["t_cc_s"] = 60.0
    v = h3.verdict(rows)
    assert v["H3"] == "NOT APPLICABLE" and v["L1"]["v1_fired"] == ["l1_2"]


def test_incomplete_and_excluded_not_counted():
    rows = _l1() + _na()
    rows[0]["included"] = False
    rows[0]["exclusion_reason"] = "run error: x"
    v = h3.verdict(rows)
    assert v["H3"] == "INCOMPLETE"
    assert v["status"]["cells"]["L1@detect_only"]["missing"] == 1
    assert v["status"]["excluded"][0][0] == "l1_0"


def test_invalid_config_overrides():
    rows = _l1() + _na()
    rows[1]["config_problems"] = ["run_summary has no range_source with a seed"]
    assert h3.verdict(rows)["H3"] == "INVALID CONFIG"


def test_duplicate_seeds_reported():
    rows = _l1() + _na()
    rows[1]["range_seed"] = rows[0]["range_seed"]
    assert h3.verdict(rows)["duplicate_range_seeds"] == [0]


# --- P-B1-2 ------------------------------------------------------------------

def _fast(t_rng, t_jump, rid):
    return _row("L30@detect_only", rid=rid, t_rng_s=t_rng, t_jump_s=t_jump)


def test_p_b1_2_holds():
    res = h3.p_b1_2([_fast(10.0, 7.3, "a"), _fast(7.0, 7.3, "b")])
    assert res["result"] == "HOLDS"


def test_p_b1_2_falsified():
    assert h3.p_b1_2([_fast(10.0, 7.3, "a"), _fast(6.7, 7.3, "b")])["result"] == "FALSIFIED"


def test_p_b1_2_undetermined_without_alarm():
    assert h3.p_b1_2([_fast(None, 7.3, "a")])["result"] == "UNDETERMINED"


# --- files end to end ----------------------------------------------------------

def _write_run(root, name, summary, events, uav_series):
    d = root / name
    d.mkdir()
    (d / "run_summary.json").write_text(json.dumps(summary))
    (d / "merged.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    truth, belief, vel, gps = uav_series
    traj, tel = [], []
    for (t, n, e) in truth:
        traj.append({"t_wall": t, "uav_id": "uav_0", "x": e, "y": n, "z": 20.0})
    for (t, n, e), (_, vn, ve) in zip(belief, vel):
        tel.append({"timestamp": t, "msg_type": "LOCAL_POSITION_NED",
                    "data": {"x": n, "y": e, "vx": vn, "vy": ve}})
    for (t, lat, lon) in gps:
        tel.append({"timestamp": t, "msg_type": "GPS_RAW_INT",
                    "data": {"lat": round(lat * 1e7), "lon": round(lon * 1e7)}})
    (d / "trajectory.jsonl").write_text("\n".join(json.dumps(x) for x in traj) + "\n")
    (d / "telemetry_monitor_uav_0.jsonl").write_text(
        "\n".join(json.dumps(x) for x in tel) + "\n")
    return d


def test_run_row_from_files(tmp_path):
    d = _write_run(tmp_path, "run_L1_a", _summary(), _l1_events(), _series())
    r = h3.run_row(str(d))
    assert r["included"] and r["cell"] == "L1@detect_only"
    assert r["spoof_at_window_end_m"] == pytest.approx(50.0, abs=0.1)
    assert r["harm_at_alarm_m"] == pytest.approx(0.65 * 9.0, abs=0.05)
    assert r["passes"] is True


def test_main_prints_status_only_without_final(tmp_path, capsys):
    _write_run(tmp_path, "run_L1_a", _summary(), _l1_events(), _series())
    assert h3.main(["x", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "H3" not in out and out["cells"]["L1@detect_only"]["included"] == 1
    assert not (tmp_path / "h3_rows.json").exists()
    assert h3.main(["x", str(tmp_path), "--final"]) == 0
    assert "H3" in json.loads(capsys.readouterr().out)
    assert (tmp_path / "h3_rows.json").exists()
