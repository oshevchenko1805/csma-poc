"""metrics.h2_analysis — the pre-registered H2 decision rules."""
import math

import pytest

from metrics import h2_analysis as h2


def _row(policy, attack, drift, included=True, rid=None):
    return {"run_id": rid or f"{policy}_{attack}_{drift}", "policy": policy,
            "attack": attack, "included": included, "drift_itt_m": drift}


def _cell(attack, trust, prop):
    return [_row("trust_aware", attack, d, rid=f"t{i}{attack}") for i, d in enumerate(trust)] + \
           [_row("proportionate", attack, d, rid=f"p{i}{attack}") for i, d in enumerate(prop)]


GOOD_T = [1.5, 1.7, 2.0, 2.2, 2.5, 2.9, 3.1, 3.3, 3.5, 3.8, 1.9, 2.4, 2.6, 2.8, 3.0]
LOIT = [49.8, 49.9, 50.0, 50.1, 50.2] * 3


def test_constants_fixed_before_campaign():
    assert h2.BOUND_M == 7.91 and h2.ALPHA == 0.05
    assert h2.CONFIRMATORY_CELLS == ("gps_spoofing", "monitor_takeout+gps_spoofing")


def test_confirmed_when_both_cells_pass():
    rows = _cell("gps_spoofing", GOOD_T, LOIT) + _cell("monitor_takeout+gps_spoofing", GOOD_T, LOIT)
    v = h2.verdict(rows)
    assert v["H2"] == "CONFIRMED"
    assert all(v["cells"][c]["p_holm"] < 1e-4 for c in h2.CONFIRMATORY_CELLS)


def test_partial_when_magnitude_bound_missed_in_one_cell():
    big = [x + 6.0 for x in GOOD_T]          # median ~8.8 m > 7.91, still << 50
    rows = _cell("gps_spoofing", GOOD_T, LOIT) + _cell("monitor_takeout+gps_spoofing", big, LOIT)
    v = h2.verdict(rows)
    assert v["cells"]["monitor_takeout+gps_spoofing"]["p_holm"] < 0.05
    assert v["cells"]["monitor_takeout+gps_spoofing"]["accepted"] is False
    assert v["H2"] == "PARTIAL"


def test_not_confirmed_without_difference():
    rows = _cell("gps_spoofing", LOIT, LOIT) + _cell("monitor_takeout+gps_spoofing", LOIT, LOIT)
    assert h2.verdict(rows)["H2"] == "NOT CONFIRMED"


def test_failed_actions_rank_worst_and_count():
    t = GOOD_T[:10] + [math.inf] * 5
    rows = _cell("gps_spoofing", t, LOIT)
    info = h2.verdict(rows)["cells"]["gps_spoofing"]
    assert info["action_failures_trust"] == 5
    assert info["median_trust_m"] == pytest.approx(3.3)   # 10 finite + 5 inf, median = 8th value
    assert h2.one_sided_mw_less([math.inf] * 3, [1.0] * 3) > 0.9


def test_excluded_runs_are_listed_not_used():
    rows = _cell("gps_spoofing", GOOD_T, LOIT) + [
        _row("trust_aware", "gps_spoofing", 999.0, included=False, rid="bad")]
    v = h2.verdict(rows)
    assert v["excluded"] == ["bad"]
    assert v["cells"]["gps_spoofing"]["n_trust"] == 15


def test_dt_is_descriptive_only():
    rows = _cell("detector_takeout+gps_spoofing", GOOD_T, [8.4] * 15)
    info = h2.verdict(rows)["cells"]["detector_takeout+gps_spoofing"]
    assert "p_one_sided" not in info and "accepted" not in info
    assert info["diff_median_ci"][0] < 0


def test_fallback_after():
    modes = [{"t_wall": 1.0, "mode": "MISSION"}, {"t_wall": 5.0, "mode": "OFFBOARD"},
             {"t_wall": 30.0, "mode": "HOLD"}]
    assert h2.fallback_after(modes, "OFFBOARD", 4.9, 60.0) == "HOLD"
    assert h2.fallback_after(modes, "OFFBOARD", 4.9, 20.0) is None
    assert h2.fallback_after(modes[:1], "OFFBOARD", 4.9, 60.0) == "never:OFFBOARD"
    # mode already in effect at action time counts (LOITER after takeoff HOLD)
    assert h2.fallback_after([{"t_wall": 0.0, "mode": "HOLD"}], "HOLD", 4.0, 60.0) is None


def test_first_ok_ack_skips_failures_and_pre_injection():
    ev = [{"event_type": "recovery_ack", "target_uav": "uav_0", "success": True, "timestamp": 5, "action": "x"},
          {"event_type": "recovery_ack", "target_uav": "uav_0", "success": False, "timestamp": 11, "action": "a"},
          {"event_type": "recovery_ack", "target_uav": "uav_1", "success": True, "timestamp": 12, "action": "b"},
          {"event_type": "recovery_ack", "target_uav": "uav_0", "success": True, "timestamp": 13, "action": "c"}]
    assert h2.first_ok_ack(ev, 10.0, "uav_0") == (13.0, "c")
    assert h2.first_ok_ack(ev, 20.0, "uav_0") is None
