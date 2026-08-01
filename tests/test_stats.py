"""
tests/test_stats.py — inferential statistics helpers.

Cases with hand-checkable answers, so a wrong implementation fails here
rather than in Chapter 5.
"""

import math

import pytest

from metrics import stats as S


# --- normal ------------------------------------------------------------


def test_normal_cdf_known_points():
    assert S.normal_cdf(0.0) == pytest.approx(0.5)
    assert S.normal_cdf(1.96) == pytest.approx(0.975, abs=1e-3)
    assert S.normal_cdf(-1.96) == pytest.approx(0.025, abs=1e-3)


# --- Fisher ------------------------------------------------------------


def test_fisher_symmetric_table_is_not_significant():
    assert S.fisher_exact(5, 5, 5, 5) == pytest.approx(1.0)


def test_fisher_perfect_separation_small_table():
    """Margins 3/3/3/3, complete separation: two-sided p = 0.1 exactly.

    C(3,3)*C(3,0)/C(6,3) = 1/20 per extreme, two extremes -> 0.1.
    """
    assert S.fisher_exact(3, 0, 0, 3) == pytest.approx(0.1)


def test_fisher_is_transpose_invariant():
    assert S.fisher_exact(2, 26, 30, 0) == pytest.approx(S.fisher_exact(26, 2, 0, 30))


def test_fisher_campaign_core_is_significant():
    """The load-bearing cell: A 2/28 vs C 30/30 under detector_takeout."""
    p = S.fisher_exact(2, 26, 30, 0)
    assert p < 1e-10


def test_fisher_degenerate_margins_return_one():
    assert S.fisher_exact(0, 0, 5, 5) == pytest.approx(1.0)
    assert S.fisher_exact(5, 0, 5, 0) == pytest.approx(1.0)


# --- proportion difference ---------------------------------------------


def test_newcombe_interval_excludes_zero_for_separated_cells():
    lo, hi = S.newcombe_diff_ci(30, 30, 2, 28)
    assert lo > 0.0
    assert hi <= 1.0


def test_newcombe_interval_contains_zero_for_equal_cells():
    lo, hi = S.newcombe_diff_ci(5, 10, 5, 10)
    assert lo < 0.0 < hi


def test_newcombe_handles_boundary_without_running_off_scale():
    lo, hi = S.newcombe_diff_ci(30, 30, 0, 30)
    assert -1.0 <= lo <= hi <= 1.0


# --- Mann-Whitney ------------------------------------------------------


def test_mann_whitney_identical_samples_not_significant():
    u, p = S.mann_whitney_u([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
    assert p > 0.5


def test_mann_whitney_separated_samples_significant():
    x = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7]
    y = [9.0, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7]
    u, p = S.mann_whitney_u(x, y)
    assert p < 0.01


def test_mann_whitney_u_statistic_is_zero_when_all_x_below_y():
    u, _p = S.mann_whitney_u([1, 2, 3], [4, 5, 6])
    assert u == pytest.approx(0.0)


def test_mann_whitney_handles_ties():
    u, p = S.mann_whitney_u([1, 1, 1, 1], [1, 1, 1, 1])
    assert p == pytest.approx(1.0)


def test_mann_whitney_empty_returns_none():
    assert S.mann_whitney_u([], [1, 2, 3]) is None


# --- bootstrap ---------------------------------------------------------


def test_bootstrap_interval_brackets_the_observed_difference():
    x = [10.0, 11.0, 12.0, 13.0, 14.0]
    y = [1.0, 2.0, 3.0, 4.0, 5.0]
    obs, lo, hi = S.bootstrap_diff_median(x, y, iterations=2000)
    assert obs == pytest.approx(9.0)
    assert lo <= obs <= hi
    assert lo > 0.0


def test_bootstrap_is_reproducible_under_a_fixed_seed():
    x = [1.0, 5.0, 2.0, 9.0, 3.0, 4.0]
    y = [2.0, 3.0, 8.0, 1.0, 7.0, 6.0]
    a = S.bootstrap_diff_median(x, y, iterations=1000, seed=7)
    b = S.bootstrap_diff_median(x, y, iterations=1000, seed=7)
    assert a == b


def test_bootstrap_too_small_returns_none():
    assert S.bootstrap_diff_median([1.0], [2.0, 3.0]) is None


# --- Holm --------------------------------------------------------------


def test_holm_scales_the_smallest_p_by_the_family_size():
    adj = S.holm({"a": 0.01, "b": 0.02, "c": 0.03})
    assert adj["a"] == pytest.approx(0.03)


def test_holm_is_monotone_and_bounded():
    adj = S.holm({"a": 0.001, "b": 0.4, "c": 0.9})
    assert adj["a"] <= adj["b"] <= adj["c"] <= 1.0


def test_holm_single_test_is_unchanged():
    assert S.holm({"only": 0.042})["only"] == pytest.approx(0.042)


# --- reporting ---------------------------------------------------------


def test_stars_thresholds():
    assert S.stars(0.0001) == "***"
    assert S.stars(0.005) == "**"
    assert S.stars(0.04) == "*"
    assert S.stars(0.4) == "ns"
    assert S.stars(None) == ""
