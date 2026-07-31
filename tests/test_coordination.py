"""
tests/test_coordination.py — coordination integrity metric.

Every case is a synthetic trajectory with a known answer, so the test
fails when the maths is wrong rather than when the simulator drifts.
"""

import math

import pytest

from metrics import coordination as C


# --- fixtures ----------------------------------------------------------


def straight(t0: float, n: int, speed: float, north0: float = 0.0,
             east0: float = 0.0, dt: float = 1.0,
             stop_at: float = None, drift_north: float = 0.0) -> list:
    """UAV flying east at `speed`, optionally stopping or drifting north."""
    out = []
    north, east = north0, east0
    for i in range(n):
        t = t0 + i * dt
        out.append((t, north, east))
        moving = stop_at is None or t < stop_at
        if moving:
            east += speed * dt
            if drift_north and (stop_at is None or t >= 0):
                north += drift_north * dt
    return out


def fleet(**kwargs) -> dict:
    return kwargs


T0 = 1000.0
ATTACK = T0 + 60.0
N = 120  # 120 s of flight at 1 Hz


# --- cases -------------------------------------------------------------


def test_synchronised_fleet_has_no_divergence():
    """Three UAVs flying identically: both indicators must stay ~0."""
    traj = fleet(
        uav_0=straight(T0, N, 5.0, north0=0.0),
        uav_1=straight(T0, N, 5.0, north0=5.0),
        uav_2=straight(T0, N, 5.0, north0=10.0),
    )
    m = C.analyse(traj, ATTACK)
    assert m is not None
    assert m.n_uavs == 3
    assert m.phase_excess_m == pytest.approx(0.0, abs=1e-6)
    assert m.geometry_excess_m == pytest.approx(0.0, abs=1e-6)


def test_stopped_uav_produces_phase_divergence():
    """A UAV parked at the attack instant falls behind at flight speed.

    This is the loiter-recovery case: the vehicle stays on the planned
    route geometrically, so an off-plan metric sees nothing, while its
    mission phase separates from the swarm by speed x elapsed time.
    """
    traj = fleet(
        uav_0=straight(T0, N, 5.0, north0=0.0, stop_at=ATTACK),
        uav_1=straight(T0, N, 5.0, north0=5.0),
        uav_2=straight(T0, N, 5.0, north0=10.0),
    )
    m = C.analyse(traj, ATTACK)
    assert m is not None
    # ~59 s of flight left after the attack, at 5 m/s.
    assert m.phase_excess_m > 250.0
    assert m.phase_divergence_end_m == pytest.approx(m.phase_divergence_peak_m, rel=1e-6)


def test_lateral_drift_shows_in_geometry_not_phase():
    """A UAV pushed sideways keeps pace but breaks formation.

    Separates the two indicators: geometry moves a lot, phase barely.
    """
    traj = fleet(
        uav_0=straight(T0, N, 5.0, north0=0.0, drift_north=1.0),
        uav_1=straight(T0, N, 5.0, north0=5.0),
        uav_2=straight(T0, N, 5.0, north0=10.0),
    )
    m = C.analyse(traj, ATTACK)
    assert m is not None
    assert m.geometry_excess_m > 40.0
    # sqrt(5^2+1^2) vs 5 m/s => ~0.1 m/s of extra path, ~12 m over the run
    assert m.phase_excess_m < 20.0


def test_baseline_is_subtracted_per_run():
    """Divergence that exists BEFORE the attack is not charged to it."""
    traj = fleet(
        uav_0=straight(T0, N, 4.0, north0=0.0),   # slower the whole time
        uav_1=straight(T0, N, 5.0, north0=5.0),
        uav_2=straight(T0, N, 5.0, north0=10.0),
    )
    m = C.analyse(traj, ATTACK)
    assert m is not None
    assert m.phase_baseline_m is not None and m.phase_baseline_m > 0.0
    assert m.phase_divergence_peak_m > m.phase_excess_m


def test_single_uav_returns_none():
    """Coordination between one node and itself is not a quantity."""
    assert C.analyse(fleet(uav_0=straight(T0, N, 5.0)), ATTACK) is None


def test_missing_samples_are_tolerated():
    """A telemetry dropout must not abort the analysis or invent travel."""
    full = straight(T0, N, 5.0, north0=0.0)
    gapped = [s for s in full if not (T0 + 20 <= s[0] < T0 + 25)]
    traj = fleet(
        uav_0=gapped,
        uav_1=straight(T0, N, 5.0, north0=5.0),
        uav_2=straight(T0, N, 5.0, north0=10.0),
    )
    m = C.analyse(traj, ATTACK)
    assert m is not None
    # the gap is bridged, not double-counted: still a synchronised fleet
    assert m.phase_excess_m < 1.0


# --- pure-function guards ---------------------------------------------


def test_path_progress_is_cumulative():
    row = [(0.0, 0.0, 0.0), (1.0, 0.0, 3.0), (2.0, 4.0, 3.0)]
    assert C.path_progress(row) == pytest.approx([0.0, 3.0, 7.0])


def test_path_progress_carries_gaps_forward():
    row = [(0.0, 0.0, 0.0), None, (2.0, 0.0, 6.0)]
    out = C.path_progress(row)
    assert out[0] == pytest.approx(0.0)
    assert out[1] == pytest.approx(0.0)
    assert out[2] == pytest.approx(6.0)


def test_spread_is_median_based():
    assert C.spread([10.0, 10.0, 20.0]) == pytest.approx(10.0)
    assert C.spread([5.0]) is None
    assert C.spread([]) is None


def test_pairwise_distances_are_symmetric_pairs():
    pts = {"uav_0": (0.0, 0.0, 0.0), "uav_1": (0.0, 3.0, 4.0)}
    d = C.pairwise_distances(pts)
    assert set(d) == {("uav_0", "uav_1")}
    assert d[("uav_0", "uav_1")] == pytest.approx(5.0)


def test_nearest_index_picks_closest_sample():
    times = [0.0, 1.0, 2.0]
    assert C.nearest_index(times, 1.4)[1] == 1
    assert C.nearest_index(times, 1.6)[1] == 2
    assert C.nearest_index([], 1.0) is None


def test_resample_marks_missing_beyond_tolerance():
    samples = [(0.0, 0.0, 0.0), (10.0, 0.0, 50.0)]
    row = C.resample(samples, [0.0, 5.0, 10.0], tolerance=1.0)
    assert row[0] is not None
    assert row[1] is None
    assert row[2] is not None


def test_analyse_is_deterministic():
    traj = fleet(
        uav_0=straight(T0, N, 5.0, north0=0.0, stop_at=ATTACK),
        uav_1=straight(T0, N, 5.0, north0=5.0),
        uav_2=straight(T0, N, 5.0, north0=10.0),
    )
    a = C.analyse(traj, ATTACK)
    b = C.analyse(traj, ATTACK)
    assert a == b
