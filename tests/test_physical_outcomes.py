"""
Регресія для metrics/physical_outcomes.py.

Навіщо: `mission_degradation_m` — відстань до лінії маршруту, а не фізичне
зміщення. Під GPS spoofing у C апарат після LOITER зносило на ~50 м уздовж
сторони квадрата, а метрика показувала 19.7 м (ревʼю P1, 2026-09-26).
Ці тести фіксують, що нові величини рахують саме те, що заявлено.
"""

from __future__ import annotations

import math

import pytest

from metrics.physical_outcomes import (
    count_captures,
    estimate_jump_time,
    max_distance_from,
    tail_median,
)

SQUARE = [(30.0, 0.0), (30.0, 30.0), (0.0, 30.0), (0.0, 0.0)]


def test_jump_time_ignores_pre_attack_and_small_divergence():
    t = [-5.0, -1.0, 0.0, 3.0, 7.0, 8.0]
    d = [40.0, 0.2, 0.3, 0.5, 49.0, 50.0]
    assert estimate_jump_time(t, d) == 7.0


def test_jump_time_none_when_estimate_never_takes_spoof():
    assert estimate_jump_time([0.0, 1.0, 2.0], [0.1, 0.2, 0.3]) is None


def test_tail_median_uses_only_tail():
    t = [0.0, 45.0, 52.0, 55.0, 60.0]
    v = [0.0, 1.0, 49.0, 50.0, 51.0]
    assert tail_median(t, v, 60.0, 10.0) == 50.0


def test_drift_is_physical_displacement_not_route_distance():
    # LOITER at the (30, 30) corner, then pushed 50 m south along the
    # east = 30 side: route distance at the end is 20 m, drift is 50 m.
    samples = [(float(k), 30.0 - 50.0 * k / 10.0, 30.0) for k in range(11)]
    assert max_distance_from(samples, 0.0, 10.0) == pytest.approx(50.0)


def test_drift_zero_when_hold_holds():
    samples = [(float(k), 2.5, 30.0) for k in range(10)]
    assert max_distance_from(samples, 0.0, 9.0) == 0.0


def test_drift_none_without_samples_in_interval():
    assert max_distance_from([(0.0, 0.0, 0.0)], 5.0, 9.0) is None


def _walk(points, step=1.0):
    """Straight-line samples through points, 1 m apart, t = arc length."""
    out, t = [], 0.0
    for (a, b) in zip(points, points[1:]):
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
        for k in range(n):
            f = k / n
            out.append((t, a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])))
            t += step
    out.append((t, points[-1][0], points[-1][1]))
    return out


def test_captures_full_lap_in_order():
    path = _walk([(30.0, 0.0), (30.0, 30.0), (0.0, 30.0), (0.0, 0.0), (30.0, 0.0)])
    assert count_captures(path, SQUARE, 0.0, 1e9) == 5


def test_captures_start_mid_lap():
    path = _walk([(30.0, 15.0), (30.0, 30.0), (0.0, 30.0)])
    assert count_captures(path, SQUARE, 0.0, 1e9) == 2


def test_hovering_at_corner_counts_once():
    path = [(float(k), 30.0, 30.0) for k in range(20)]
    assert count_captures(path, SQUARE, 0.0, 1e9) == 1


def test_shifted_square_captures_nothing():
    # A/B under spoofing fly the whole square 50 m south of the plan.
    path = _walk([(-20.0, 0.0), (-20.0, 30.0), (-50.0, 30.0), (-50.0, 0.0)])
    assert count_captures(path, SQUARE, 0.0, 1e9) == 0


def test_out_of_order_corner_not_counted():
    # (30,0) -> diagonal to (0,30) skips (30,30): the second corner is not
    # the expected next one.
    path = _walk([(30.0, 0.0), (0.0, 30.0)])
    assert count_captures(path, SQUARE, 0.0, 1e9) == 1
