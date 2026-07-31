"""
metrics/coordination.py — coordination integrity of Table 3.13, measured
as inter-node consistency rather than as off-plan distance.

Why this module exists
----------------------
`metrics/derived.py` computes

    coord_loss     = 1 - min over time of (share of UAVs on plan)
    coord_restored = shares[-1]
    residual       = shares[-1]        # <- same expression

so `coordination_restored` and `residual_mission_func` are the SAME
number reported under two different security properties, and
`coordination_loss` is mission degradation thresholded at 15 m and
averaged over the fleet. Neither measures whether the nodes stayed
consistent WITH EACH OTHER, which is what 3.5.4 and Table 3.12 ask for
("розбіжність у проходженні waypoint, відхилення від очікуваної часової
синхронізації, розбіжність між локальними станами вузлів").

This module measures the two indicators the methodology actually names,
from artefacts every run already wrote (`trajectory.jsonl`, Gazebo
ground truth, ~5 Hz, all UAVs). No re-runs.

Indicators
----------
phase divergence (m of along-track path)
    How far a UAV has fallen behind / run ahead of the fleet in
    cumulative distance flown. A vehicle parked by a loiter recovery is
    still geometrically ON the route — off-plan distance sees nothing —
    but its mission phase separates from the swarm at flight speed.
    This is the indicator that makes containment-vs-synchronisation a
    visible trade-off.

geometry deviation (m of inter-UAV distance)
    How far pairwise inter-UAV distances moved from their own
    pre-attack values. Captures formation break-up independently of
    whether anyone left the planned polyline.

Both are reported raw AND as an excess over the run's own pre-attack
level, so nominal SITL tracking scatter is subtracted per run rather
than assumed.

Everything here is a pure function on plain lists. The only I/O lives in
`analyse_run_dir`, which is a thin convenience wrapper.
"""

from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import dataclass
from typing import Optional

GRID_STEP_S = 1.0
"""Resampling step. Gazebo runs at ~5 Hz; cumulative path length over a
150 s run would accumulate sensor scatter at that rate, so positions are
resampled to 1 Hz before path length is integrated. At ~3.5 m/s cruise a
1 s step covers metres, and sub-decimetre scatter stops mattering."""

SAMPLE_TOLERANCE_S = 1.0
"""A grid point with no sample within this gap counts as missing rather
than being interpolated across an unknown interval."""

BASELINE_WINDOW_S = 30.0
"""Pre-attack window defining this run's own nominal spread."""


# --- pure helpers ------------------------------------------------------


def nearest_index(times: list, t: float) -> Optional[tuple]:
    """(gap, index) of the sample closest to t, or None for an empty list."""
    if not times:
        return None
    k = bisect.bisect_left(times, t)
    best = None
    for cand in (k - 1, k, k + 1):
        if 0 <= cand < len(times):
            gap = abs(times[cand] - t)
            if best is None or gap < best[0]:
                best = (gap, cand)
    return best


def resample(samples: list, grid: list, tolerance: float = SAMPLE_TOLERANCE_S) -> list:
    """[(t, north, east)] -> one entry per grid point, None where missing."""
    times = [s[0] for s in samples]
    row = []
    for gt in grid:
        hit = nearest_index(times, gt)
        row.append(None if (hit is None or hit[0] > tolerance) else samples[hit[1]])
    return row


def path_progress(row: list) -> list:
    """Cumulative horizontal distance flown, one value per grid point.

    A missing grid point carries the previous total forward; the distance
    across the gap is credited to the next present sample, so a dropout
    neither invents nor loses travel.
    """
    out = []
    total = 0.0
    prev = None
    for sample in row:
        if sample is None:
            out.append(total if prev is not None else None)
            continue
        if prev is not None:
            total += math.hypot(sample[1] - prev[1], sample[2] - prev[2])
        out.append(total)
        prev = sample
    return out


def spread(values: list) -> Optional[float]:
    """Largest absolute deviation from the median. Robust to one outlier
    being the whole story, which is exactly the single-target case."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    med = statistics.median(vals)
    return max(abs(v - med) for v in vals)


def pairwise_distances(points: dict) -> dict:
    """{uav: (t, north, east)} -> {(uav_a, uav_b): distance}."""
    uavs = sorted(points)
    out = {}
    for i in range(len(uavs)):
        for j in range(i + 1, len(uavs)):
            a, b = uavs[i], uavs[j]
            pa, pb = points[a], points[b]
            out[(a, b)] = math.hypot(pa[1] - pb[1], pa[2] - pb[2])
    return out


# --- result ------------------------------------------------------------


@dataclass
class CoordinationMetrics:
    """All distances in metres. `*_excess_m` = peak minus this run's own
    pre-attack level, floored at zero — the honest headline number."""

    phase_divergence_peak_m: Optional[float]
    phase_divergence_end_m: Optional[float]
    phase_baseline_m: Optional[float]
    phase_excess_m: Optional[float]
    geometry_deviation_peak_m: Optional[float]
    geometry_deviation_end_m: Optional[float]
    geometry_baseline_m: Optional[float]
    geometry_excess_m: Optional[float]
    n_uavs: int
    n_grid_points: int


def analyse(
    trajectories: dict,
    t_attack: float,
    grid_step_s: float = GRID_STEP_S,
    tolerance_s: float = SAMPLE_TOLERANCE_S,
    baseline_window_s: float = BASELINE_WINDOW_S,
) -> Optional[CoordinationMetrics]:
    """
    trajectories: {uav_id: [(t_wall, north_m, east_m), ...]} sorted by time,
                  in the frame produced by metrics.derived.load_trajectory.
    t_attack:     injection instant (wall clock).

    Returns None when fewer than two UAVs have usable data — coordination
    between one node and itself is not a quantity.
    """
    uavs = sorted(u for u, s in trajectories.items() if len(s) >= 2)
    if len(uavs) < 2:
        return None

    start = max(trajectories[u][0][0] for u in uavs)
    end = min(trajectories[u][-1][0] for u in uavs)
    if end - start < grid_step_s * 2:
        return None

    steps = int((end - start) / grid_step_s)
    grid = [start + i * grid_step_s for i in range(steps + 1)]

    rows = {u: resample(trajectories[u], grid, tolerance_s) for u in uavs}
    progress = {u: path_progress(rows[u]) for u in uavs}

    phase_series = []
    geometry_series = []
    for i, gt in enumerate(grid):
        ph = spread([progress[u][i] for u in uavs])
        if ph is not None:
            phase_series.append((gt, ph))
        points = {u: rows[u][i] for u in uavs if rows[u][i] is not None}
        if len(points) >= 2:
            geometry_series.append((gt, pairwise_distances(points)))

    # Pre-attack reference: each pair against its own median separation.
    pre_geo = [
        (gt, d)
        for (gt, d) in geometry_series
        if t_attack - baseline_window_s <= gt < t_attack
    ]
    base = {}
    for pair in {p for (_, d) in pre_geo for p in d}:
        vals = [d[pair] for (_, d) in pre_geo if pair in d]
        if vals:
            base[pair] = statistics.median(vals)

    def geo_deviation(distances: dict) -> Optional[float]:
        vals = [abs(v - base[p]) for p, v in distances.items() if p in base]
        return max(vals) if vals else None

    pre_phase = [v for (gt, v) in phase_series if t_attack - baseline_window_s <= gt < t_attack]
    post_phase = [v for (gt, v) in phase_series if gt >= t_attack]
    phase_base = max(pre_phase) if pre_phase else None
    phase_peak = max(post_phase) if post_phase else None
    phase_end = post_phase[-1] if post_phase else None

    pre_geo_dev = [d for (gt, dd) in pre_geo for d in [geo_deviation(dd)] if d is not None]
    post_geo_dev = [
        d
        for (gt, dd) in geometry_series
        if gt >= t_attack
        for d in [geo_deviation(dd)]
        if d is not None
    ]
    geo_base = max(pre_geo_dev) if pre_geo_dev else None
    geo_peak = max(post_geo_dev) if post_geo_dev else None
    geo_end = post_geo_dev[-1] if post_geo_dev else None

    def excess(peak: Optional[float], baseline: Optional[float]) -> Optional[float]:
        if peak is None:
            return None
        return max(0.0, peak - (baseline or 0.0))

    return CoordinationMetrics(
        phase_divergence_peak_m=phase_peak,
        phase_divergence_end_m=phase_end,
        phase_baseline_m=phase_base,
        phase_excess_m=excess(phase_peak, phase_base),
        geometry_deviation_peak_m=geo_peak,
        geometry_deviation_end_m=geo_end,
        geometry_baseline_m=geo_base,
        geometry_excess_m=excess(geo_peak, geo_base),
        n_uavs=len(uavs),
        n_grid_points=len(grid),
    )


# --- thin I/O wrapper --------------------------------------------------


def analyse_run_dir(run_dir: str) -> Optional[CoordinationMetrics]:
    """Convenience for scripts. Imported lazily so this module stays
    importable without the rest of the metrics package."""
    from metrics.derived import load_trajectory, load_events, _attack_ts

    events = load_events(run_dir)
    t_attack = _attack_ts(events)
    if t_attack is None:
        return None
    return analyse(load_trajectory(run_dir), t_attack)
