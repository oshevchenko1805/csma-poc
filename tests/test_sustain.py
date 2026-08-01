"""
tests/test_sustain.py — offline re-evaluation of the sustain rule.

The maths is small, which is exactly why it needs guarding: this module
underwrites a claim in Chapter 4 about why one spoof went undetected.
"""

import pytest

from metrics import sustain as S


# --- max_consecutive_above --------------------------------------------


def test_empty_series_has_no_run():
    assert S.max_consecutive_above([]) == 0


def test_all_below_threshold():
    assert S.max_consecutive_above([0.0, 0.1, 0.9, 1.0]) == 0


def test_threshold_is_strict():
    """Exactly at the threshold does not count as a breach."""
    assert S.max_consecutive_above([1.0, 1.0, 1.0]) == 0
    assert S.max_consecutive_above([1.01, 1.01, 1.01]) == 3


def test_longest_run_not_total_count():
    """The undetected-run signature: two breaches, never adjacent."""
    assert S.max_consecutive_above([2.0, 0.0, 2.0]) == 1


def test_picks_the_longest_of_several_runs():
    assert S.max_consecutive_above([2.0, 2.0, 0.0, 2.0, 2.0, 2.0, 0.0, 2.0]) == 3


def test_non_numeric_samples_break_the_run():
    assert S.max_consecutive_above([2.0, None, 2.0]) == 1


# --- would_detect ------------------------------------------------------


def test_would_detect_reproduces_the_undetected_case():
    """2 breaches, non-adjacent: fires at k=1, silent at k>=2."""
    vals = [2.0, 0.0, 2.0]
    assert S.would_detect(vals, 1) is True
    assert S.would_detect(vals, 2) is False
    assert S.would_detect(vals, 3) is False


def test_would_detect_is_monotone_in_k():
    vals = [2.0, 2.0, 2.0, 2.0, 0.0]
    fired = [S.would_detect(vals, k) for k in (1, 2, 3, 4, 5)]
    assert fired == [True, True, True, True, False]
    assert all(not f for f in fired[fired.index(False):])


# --- series extraction -------------------------------------------------


def test_series_pairs_zips_and_drops_malformed():
    node = {"t_rel_sec": [-1.0, 0.0, 1.0, 2.0], "pos_horiz_ratio": [0.1, 2.0, None, 2.0]}
    assert S.series_pairs(node) == [(-1.0, 0.1), (0.0, 2.0), (2.0, 2.0)]


def test_post_window_drops_pre_attack_samples():
    node = {"t_rel_sec": [-2.0, -1.0, 0.0, 1.0], "pos_horiz_ratio": [2.0, 2.0, 2.0, 2.0]}
    assert S.window_values(node, "post") == [2.0, 2.0]
    assert S.window_values(node, "full") == [2.0, 2.0, 2.0, 2.0]


def test_windows_can_disagree_about_detection():
    """A breach run that began BEFORE the attack: the live (causal)
    detector counts it, post-attack attribution does not."""
    node = {"t_rel_sec": [-2.0, -1.0, 0.0], "pos_horiz_ratio": [2.0, 2.0, 2.0]}
    assert S.would_detect(S.window_values(node, "full"), 3) is True
    assert S.would_detect(S.window_values(node, "post"), 3) is False


def test_missing_series_yields_empty_window():
    assert S.window_values({}, "post") == []
    assert S.window_values({"t_rel_sec": [], "pos_horiz_ratio": []}, "full") == []


# --- scenario filter ---------------------------------------------------


def test_scenario_match_is_exact_not_substring():
    """detector_takeout+gps_spoofing must NOT be swept: its local
    detector is silenced by design, so the sustain rule is not what
    decides the outcome there."""
    assert S.is_scenario({"attack_name": "gps_spoofing"}) is True
    assert S.is_scenario({"attack_name": "detector_takeout+gps_spoofing"}) is False
    assert S.is_scenario({"attack_name": "monitor_takeout+gps_spoofing"}) is False


def test_scenario_match_rejects_other_attacks_and_baseline():
    for name in ("comm_disruption", "command_injection", "none", "", None):
        assert S.is_scenario({"attack_name": name}) is False


def test_scenario_name_is_configurable():
    assert S.is_scenario({"attack_name": "comm_disruption"}, "comm_disruption") is True


# --- sweep bookkeeping -------------------------------------------------


def test_sweep_on_empty_roots_is_well_formed():
    res = S.sweep([], [])
    assert res["attack_runs"] == 0
    assert res["baseline_runs"] == 0
    assert res["skipped_other_scenario"] == 0
    assert set(res["detected"]) == set(S.DEFAULT_KS)
    assert all(v == 0 for v in res["fp_runs"].values())


def test_sweep_reports_the_scenario_it_used():
    assert S.sweep([], [])["attack_name"] == S.ATTACK_NAME


def test_shipped_value_is_the_documented_one():
    """Guard against the constant drifting away from the config it
    describes; Chapter 4 quotes this number."""
    assert S.SHIPPED_SUSTAINED_SAMPLES == 3
