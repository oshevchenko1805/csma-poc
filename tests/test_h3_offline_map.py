"""metrics.h3_offline_map — offline coverage map (H3 prereg, Amendment A1)."""
import importlib.util
import math
import os

import numpy as np
import pytest

from detectors.ranging import distance_3d_m, interpolate_position
from metrics import h3_offline_map as M

T0 = 1000.0


# --- helpers ----------------------------------------------------------------------

def _track(fn, t_from=T0 - 60.0, t_to=T0 + 130.0, hz=10.0):
    t = np.arange(t_from, t_to, 1.0 / hz)
    return np.array([(tt, *fn(tt)) for tt in t])


def _scene_flight(spoof_mps=None, level="L1"):
    """uav_0 flies east at 5 m/s, uav_1 10 m north of it, uav_2 10 m south,
    same altitude. With spoof_mps, uav_0's belief drifts north after T0."""
    pos = {"uav_0": lambda t: (0.0, 5.0 * (t - T0), 20.0),
           "uav_1": lambda t: (10.0, 5.0 * (t - T0), 20.0),
           "uav_2": lambda t: (-10.0, 5.0 * (t - T0), 20.0)}
    truth = {u: _track(f) for u, f in pos.items()}
    belief = {u: truth[u].copy() for u in M.UAVS}
    navw = []
    if spoof_mps is not None:
        b = belief["uav_0"]
        b[:, 1] += np.maximum(0.0, b[:, 0] - T0) * spoof_mps
        navw = [(t, max(0.0, t) * spoof_mps) for t in np.arange(0.0, 120.01, 0.1)]
    return M.Flight(run_id=f"synthetic_{level}", cell=f"{level}@detect_only" if spoof_mps else "none@detect_only",
                    level=level if spoof_mps is not None else None, t0=T0,
                    truth=truth, belief=belief, navw=navw, t_jump=None, live={})


def _load_2b():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "h3_predict_2b", os.path.join(here, "scripts", "h3_predict_2b.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- constants fixed by A1 ------------------------------------------------------------

def test_a1_constants():
    assert M.SIGMAS == (0.0, 0.5, 1.5, 3.0)
    assert M.BIASES == (0.0, 0.2, 0.4)
    assert M.SEEDS == 50 and M.TAU_S == 60.0 and M.GM_DT_S == 0.1
    assert (M.RANGE_SIGMA_M, M.P_NLOS, M.M_NLOS) == (0.1, 0.05, 0.5)
    assert M.WINDOW_S == 120.0 and M.PRE_S == 45.0
    assert M.CAL_PREFIX != M.EVAL_PREFIX
    assert (M.CHECK_SIGMA, M.CHECK_BIAS, M.CHECK_THETA, M.CHECK_THETA_OK) == (0.0, 0.2, 1.8, 1.3)
    assert M.CHECK_TOL_S == 1.5 and M.CHECK_MIN_SHARE == 0.95
    assert M.M1_RATIO == (0.8, 1.25) and M.M2_TOL_M == 0.1
    assert M.M3_WINDOW_S == (-0.5, 4.0) and M.M3_MIN_SHARE == 0.95
    assert set(M.V0_MPS) == {"L1", "L3", "L10", "L30"}


# --- same scheme as [2b] ------------------------------------------------------------

def test_seed_and_range_noise_match_2b():
    b2 = _load_2b()
    key = ("cal", "run_C_x", "uav_0", "uav_1", 3)
    ref = b2.range_noise(44, b2.seeded(*key))
    got = M.range_noise(M.range_draws(M.seeded(*key), 44), 0.2)
    assert np.array_equal(ref, got)


def test_sustained_min_matches_2b():
    b2 = _load_2b()
    a = np.array([0.1, 2.0, 2.5, 3.0, 0.2, 4.0, 4.0, 4.0])
    assert np.array_equal(M.sustained_min(a), b2.sustained_min(a))


@pytest.mark.parametrize("mx, exp", [(1.24, (1.8, 1.3)), (1.3, (1.8, 1.3)),
                                      (1.31, (1.9, 1.4)), (2.05, (2.6, 2.1))])
def test_thresholds_rule(mx, exp):
    assert M.thresholds_from_max(mx) == exp


# --- noise models -------------------------------------------------------------------

def test_gm_unit_stationary_variance_and_correlation():
    x = M.gm_unit(np.random.default_rng(1), 200_000, dt=0.1, tau=1.0)
    assert abs(x[:, 0].std() - 1.0) < 0.05 and abs(x[:, 1].std() - 1.0) < 0.05
    lag = 10   # = tau / dt
    r = np.corrcoef(x[:-lag, 0], x[lag:, 0])[0, 1]
    assert abs(r - math.exp(-1.0)) < 0.05
    assert abs(np.corrcoef(x[:, 0], x[:, 1])[0, 1]) < 0.02


def test_gm_track_interpolates_and_is_seeded():
    a = M.gm_track(M.seeded("k", 1), 0.0, 10.0)
    b = M.gm_track(M.seeded("k", 1), 0.0, 10.0)
    assert np.array_equal(a.unit, b.unit)
    assert a.t[0] == 0.0 and a.t[-1] >= 10.0
    mid = a.at(np.array([0.05]))[0]
    assert np.allclose(mid, (a.unit[0] + a.unit[1]) / 2)


# --- geometry and interpolation ------------------------------------------------------

def test_interp_gap_matches_detector_rule():
    samples = [(0.0, 0.0, 0.0, 0.0), (0.4, 4.0, 0.0, 1.0), (2.0, 20.0, 0.0, 2.0),
               (2.3, 23.0, 1.0, 2.0)]
    a = np.array(samples)
    for t in (-0.6, -0.3, 0.0, 0.2, 0.4, 0.8, 1.2, 1.7, 2.0, 2.1, 2.3, 2.7, 3.0):
        got = M.interp_gap(a, np.array([t]), 0.5)[0]
        ref = interpolate_position(samples, t, 0.5)
        if ref is None:
            assert np.all(np.isnan(got)), t
        else:
            assert np.allclose(got, ref), t


def test_geodetic_roundtrip_distance():
    pts = [(0.0, 0.0, 20.0), (10.0, -3.0, 25.0), (-40.0, 55.0, 30.0), (45.5, 12.0, 20.0)]
    for p in pts:
        for q in pts:
            d = distance_3d_m(M.to_geodetic(*p), M.to_geodetic(*q))
            assert abs(d - math.dist(p, q)) < 1e-3


def test_frame_offset_and_coverage_gate():
    tr = _track(lambda t: (t - T0, 2.0, 20.0))
    bel = tr.copy()
    bel[:, 1:] -= np.array([1.0, 2.0, 3.0])
    off = M.frame_offset(tr, bel, T0 - 45, T0 - 1)
    assert np.allclose(off, [1.0, 2.0, 3.0])
    ticks = np.arange(T0 - 45, T0 - 1, 1.0)
    trs = {u: tr for u in M.UAVS}
    assert M.coverage_ok(trs, {u: bel for u in M.UAVS}, ticks)
    holey = bel[(bel[:, 0] < T0 - 30) | (bel[:, 0] > T0 - 20)]
    assert not M.coverage_ok(trs, {"uav_0": holey, "uav_1": bel, "uav_2": bel}, ticks)


def test_announcement_times():
    t = M.announcement_times(0.0, 10.0, 0.3)
    assert len(t) == 10 and t[0] == pytest.approx(0.3) and t[-1] == pytest.approx(9.3)
    t = M.announcement_times(0.0, 10.0, 0.0)
    assert len(t) == 11 and t[-1] == 10.0


# --- calibration ----------------------------------------------------------------------

def _scene(name="s"):
    ticks = np.arange(0.0, 44.0, 1.0)
    x = {"uav_0": np.stack([np.zeros(44), 5.0 * ticks, np.full(44, 20.0)], 1),
         "uav_1": np.stack([np.full(44, 2.0), 5.0 * ticks, np.full(44, 25.0)], 1),
         "uav_2": np.stack([np.full(44, -2.0), 5.0 * ticks, np.full(44, 30.0)], 1)}
    return M.Scene(name, ticks, {u: v.copy() for u, v in x.items()}, x)


def test_calibration_deterministic_disjoint_and_grows_with_sigma():
    sc = [_scene("a"), _scene("b")]
    w1 = M.calibrate_cells(sc, (0.0, 3.0), (0.0, 0.4), 5)
    w2 = M.calibrate_cells(sc, (0.0, 3.0), (0.0, 0.4), 5)
    assert w1 == w2
    w3 = M.calibrate_cells(sc, (0.0, 3.0), (0.0, 0.4), 5, prefix=M.EVAL_PREFIX)
    assert w3 != w1
    assert w1[(3.0, 0.0)] > w1[(0.0, 0.0)]
    assert w1[(0.0, 0.4)] > w1[(0.0, 0.0)]
    tab = M.calibration_table(w1)
    assert tab[(0.0, 0.0)]["theta_m"] == M.thresholds_from_max(w1[(0.0, 0.0)])[0]


def test_calibration_sigma0_ignores_gnss_draws():
    sc = [_scene()]
    only0 = M.calibrate_cells(sc, (0.0,), (0.2,), 4)
    with_noise = M.calibrate_cells(sc, (0.0, 1.5), (0.2,), 4)
    assert only0[(0.0, 0.2)] == with_noise[(0.0, 0.2)]


# --- replay -------------------------------------------------------------------------------

def test_replay_no_attack_is_silent():
    fl = _scene_flight()
    alarms = M.replay(fl, 0.0, 0.2, 0, 1.8, 1.3)
    assert alarms == []
    assert M.replay_metrics(fl, alarms) == {"false_alarms": 0}


def test_replay_spoof_peers_flag_victim_and_victim_flags_itself():
    fl = _scene_flight(spoof_mps=1.0)
    for sd in range(3):
        m = M.replay_metrics(fl, M.replay(fl, 0.0, 0.0, sd, 1.8, 1.3))
        # |rho| = e(t) = t: bad from t > 1.8 s, 3 announcements later
        assert 3.0 <= m["t_rng_peer_s"] <= 6.0
        assert m["t_rng_self_s"] is not None
        assert m["misattributions"] == 0 and m["alarms_before_t0"] == 0
        assert m["harm_at_alarm_m"] == pytest.approx(m["t_rng_s"], abs=0.3)


def test_replay_is_seeded():
    fl = _scene_flight(spoof_mps=1.0)
    assert M.replay(fl, 1.5, 0.2, 7, 3.0, 2.5) == M.replay(fl, 1.5, 0.2, 7, 3.0, 2.5)


def test_large_gnss_noise_without_attack_raises_alarms_at_live_theta():
    # sanity: sigma = 3 m with the live theta 1.8 m is not tolerable
    fl = _scene_flight()
    n = sum(M.replay_metrics(fl, M.replay(fl, 3.0, 0.2, sd, 1.8, 1.3))["false_alarms"]
            for sd in range(5))
    assert n > 0


def test_no_position_no_announcement():
    fl = _scene_flight(spoof_mps=1.0)
    b = fl.belief["uav_0"]
    fl.belief["uav_0"] = b[(b[:, 0] < T0 - 10) | (b[:, 0] > T0 + 30)]
    m = M.replay_metrics(fl, M.replay(fl, 0.0, 0.0, 0, 1.8, 1.3))
    assert m["t_rng_peer_s"] is None or m["t_rng_peer_s"] >= 30.0


# --- summaries, check, predictions --------------------------------------------------------

def _row(level, t_peer, harm, run="r", dj=None):
    return {"level": level, "run_id": run, "t_rng_peer_s": t_peer, "t_rng_self_s": None,
            "t_rng_s": t_peer, "harm_at_alarm_m": harm, "misattributions": 0,
            "misattr_by_victim_monitor": 0, "alarms_before_t0": 0, "t_rng_minus_jump_s": dj}


def test_summaries_and_false_alarm_rate():
    rows = [_row("L1", 8.0, 5.0), _row("L1", None, None), _row("L10", 7.0, 35.0, dj=2.5)]
    s = M.summarize_level(rows, "L1")
    assert s["peer_detect_share"] == 0.5 and s["harm_at_alarm_m"]["median"] == 5.0
    f = M.summarize_level(rows, "L10")
    assert f["n_before_jump"] == 0 and f["share_in_jump_window"] == 1.0
    fa = M.false_alarm_rate([{"level": None, "false_alarms": 0}] * 150)
    assert fa["exposure_h"] == pytest.approx(150 * 165 / 3600)
    assert fa["upper95_per_flight_hour"] == pytest.approx(3 / fa["exposure_h"])
    fa2 = M.false_alarm_rate([{"level": None, "false_alarms": 2}] * 10)
    assert fa2["upper95_per_flight_hour"] is None and fa2["per_flight_hour"] > 0


def test_check_verdict():
    ok = {"share": 1.0, "median_t_peer": 8.0, "live_t_peer": 8.43}
    assert M.check_verdict([ok], 0) == "PASS"
    assert M.check_verdict([ok], 1) == "FAIL"
    assert M.check_verdict([{**ok, "share": 0.9}], 0) == "FAIL"
    assert M.check_verdict([{**ok, "median_t_peer": 10.0}], 0) == "FAIL"
    assert M.check_verdict([{**ok, "live_t_peer": None}], 0) == "FAIL"


def _cells(h1, h3, fast_before=0, fast_share=1.0):
    def lv(h, fb=0, fs=1.0):
        return {"harm_at_alarm_m": {"median": h}, "n_before_jump": fb, "share_in_jump_window": fs}
    return {(s, b): {"levels": {"L1": lv(h1[s]), "L3": lv(h3[s]),
                                "L10": lv(35.0, fast_before, fast_share), "L30": lv(49.0)}}
            for s in (0.0, 1.5) for b in (0.2,)}


def test_predictions():
    c = _cells({0.0: 5.5, 1.5: 6.0}, {0.0: 3.8, 1.5: 5.9})
    m1 = M.eval_m1(c)
    assert not m1["holds"] and m1["cells"]["1.5|0.2"]["holds"]
    assert M.eval_m2(c)["holds"]
    assert not M.eval_m2(_cells({0.0: 5.5, 1.5: 5.2}, {0.0: 3.8, 1.5: 5.9}))["holds"]
    assert M.eval_m3(c)["holds"]
    assert not M.eval_m3(_cells({0.0: 1, 1.5: 1}, {0.0: 1, 1.5: 1}, fast_before=1))["holds"]
    assert not M.eval_m3(_cells({0.0: 1, 1.5: 1}, {0.0: 1, 1.5: 1}, fast_share=0.9))["holds"]
