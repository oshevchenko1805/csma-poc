"""Tests for metrics/trust_hold_probe.py (stage-2 SITL probe analysis)."""

from metrics.trust_hold_probe import (
    belief_ne,
    nav_error_series,
    summarize,
    truth_ne,
    verdict,
)

T0 = 1000.0  # injection wall time


def _flight(truth_fn, belief_fn, t_from=-8.0, t_to=60.0, dt=0.2):
    truth, belief = [], []
    t = t_from
    while t <= t_to + 1e-9:
        tn, te = truth_fn(t)
        bn, be = belief_fn(t)
        truth.append((T0 + t, tn, te))
        belief.append((T0 + t, bn, be))
        t += dt
    return truth, belief


# Frame offset between Gazebo world and the EKF origin: truth = belief + (3, -2).
OFF_N, OFF_E = 3.0, -2.0


def _loiter_like(t):
    """Estimate jumps +50 m N at 7.5 s; LOITER then flies truth 50 m S."""
    jump = 50.0 if t >= 7.5 else 0.0
    push = -min(max(t - 7.5, 0.0) * 5.0, 50.0)  # 5 m/s until 50 m
    truth = (10.0 + OFF_N + push, 5.0 + OFF_E)
    belief = (10.0 + jump + push, 5.0)
    return truth, belief


def _zerovel_like(t):
    """Estimate jumps +50 m N at 7.5 s; aircraft stays put."""
    jump = 50.0 if t >= 7.5 else 0.0
    return (10.0 + OFF_N, 5.0 + OFF_E), (10.0 + jump, 5.0)


def _split(fn):
    return (lambda t: fn(t)[0]), (lambda t: fn(t)[1])


def test_loaders_map_enu_to_ne_and_filter_uav():
    recs = [
        {"t_wall": 2.0, "uav_id": "uav_0", "x": 1.0, "y": 7.0},
        {"t_wall": 1.0, "uav_id": "uav_0", "x": 4.0, "y": 9.0},
        {"t_wall": 1.5, "uav_id": "uav_1", "x": 0.0, "y": 0.0},
    ]
    assert truth_ne(recs) == [(1.0, 9.0, 4.0), (2.0, 7.0, 1.0)]
    assert belief_ne([{"t_wall": 1.0, "n": 2.0, "e": 3.0}]) == [(1.0, 2.0, 3.0)]


def test_frame_offset_removed_before_injection():
    truth, belief = _flight(*_split(_zerovel_like))
    nav = nav_error_series(truth, belief, T0 - 5.0, T0)
    pre = [e for t, e in nav if t < T0]
    assert pre and max(pre) < 1e-9


def test_nav_error_empty_without_bias_samples():
    truth, belief = _flight(*_split(_zerovel_like), t_from=0.0)
    assert nav_error_series(truth, belief, T0 - 5.0, T0 - 0.1) == []


def test_zerovel_like_passes_and_still_has_nav_error():
    truth, belief = _flight(*_split(_zerovel_like))
    s = summarize(truth, belief, T0, T0 + 3.0)
    assert abs(s["t_estimate_jump_s"] - 7.6) < 0.25
    assert abs(s["nav_error_end_m"] - 50.0) < 1e-6
    assert s["post_response_drift_m"] < 1e-9
    assert verdict("zerovel", s).startswith("PASS")


def test_loiter_like_is_valid_control():
    truth, belief = _flight(*_split(_loiter_like))
    s = summarize(truth, belief, T0, T0 + 3.0)
    assert abs(s["post_response_drift_m"] - 50.0) < 1e-6
    assert abs(s["drift_at_window_end_m"] - 50.0) < 1e-6
    assert verdict("loiter", s).startswith("CONTROL OK")


def test_zerovel_with_drift_fails():
    truth, belief = _flight(*_split(_loiter_like))
    s = summarize(truth, belief, T0, T0 + 3.0)
    assert verdict("zerovel", s).startswith("FAIL: drift")


def test_verdict_invalid_when_attack_did_not_land():
    truth, belief = _flight(lambda t: (OFF_N, OFF_E), lambda t: (0.0, 0.0))
    s = summarize(truth, belief, T0, T0 + 3.0)
    assert s["t_estimate_jump_s"] is None
    assert verdict("zerovel", s).startswith("INVALID")


def test_verdict_fails_on_rejected_action_or_mode_fallback():
    truth, belief = _flight(*_split(_zerovel_like))
    s = summarize(truth, belief, T0, T0 + 3.0)
    assert verdict("zerovel", s, action_error="OffboardError").startswith("FAIL: action")
    assert verdict("zerovel", s, fallback_mode="LAND").startswith("FAIL: autopilot")


def test_no_action_time_gives_no_drift():
    truth, belief = _flight(*_split(_zerovel_like))
    s = summarize(truth, belief, T0, None)
    assert s["post_response_drift_m"] is None
    assert verdict("zerovel", s).startswith("INVALID")
