"""
metrics/physical_outcomes.py — physical consequences of an attack,
separated into four quantities that `mission_degradation_m` conflated.

Why this module exists
----------------------
`mission_degradation_m` (metrics/derived.py) is the peak distance from
the target's ground-truth position to the closest point of the closed
mission polyline. It answers "how far from the route line", not "how
far was the aircraft displaced" or "did the mission continue". Under GPS
spoofing these differ: in architecture C the LOITER action holds the
*estimated* position, the estimate later jumps by the injected 50 m, and
the aircraft is physically pushed ~50 m — but along a side of the square,
so the route-line distance reads 19.7 m (or 0.24 m when the aircraft
ends up on another side). See review P1/P2, 2026-09-26.

Quantities (all anchored at the attack onset t0 = inject_start, over the
common observation window [t0, t0 + WINDOW_S])
----------------------------------------------------------------------
nav_error_end_m        |belief - truth| horizontal, median over the last
                       10 s of the window. Navigation integrity: does the
                       aircraft still know where it is? Source:
                       run_summary.belief_divergence (PX4 LOCAL_POSITION_NED
                       vs Gazebo ground truth, 1 Hz).
nav_error_peak_m       max of the same series after t0.
t_estimate_jump_s      first t >= 0 at which |belief - truth| > JUMP_M.
                       The moment the spoof enters the position estimate.
t_first_response_s     first attributable recovery_ack for the target
                       (C only; A/B have recovery disabled).
first_response_action  action of that recovery_ack (mode_loiter,
                       filter_commands, ...).
post_response_drift_m  for position-holding actions only (HOLD_ACTIONS):
                       max ground-truth distance of the target from the
                       point where it was when the first response was
                       acknowledged, over [t_ack, t0 + WINDOW_S]. What the
                       hold actually held. NaN otherwise: after
                       filter_commands the mission resumes and the aircraft
                       is supposed to move.
route_distance_m       = mission_degradation_m, copied from the master
                       under an honest name: distance to the route line.
waypoints_captured     number of mission corners reached, in ground-truth
                       coordinates and in plan order, within the window
                       (reached = within CAPTURE_RADIUS_M).
mission_execution      waypoints_captured / median of the same count over
                       valid clean flights of the same architecture.
                       1.0 = mission progressed as in a clean flight.

Ground truth is Gazebo, never the PX4 estimate. Each UAV's trajectory is
expressed in its own frame (origin = first sample), exactly as in
metrics/derived.load_trajectory, so plan corners apply to every UAV.

Usage
-----
    python -m metrics.physical_outcomes <runs_root> <campaign_master.csv> <out.csv>

<runs_root> is the directory containing the pass folders (base_pass1, ...).
"""

from __future__ import annotations

import csv
import json
import math
import os
import statistics
import sys
from typing import Optional

from metrics.derived import (
    _attack_ts,
    attributable_ts,
    load_events,
    load_trajectory,
    plan_corners,
)

WINDOW_S = 60.0
"""Common post-attack observation window (thesis 3.5.2: t = 90 .. 150 s)."""

NAV_END_TAIL_S = 10.0
"""Tail of the window over which nav_error_end_m is taken."""

JUMP_M = 25.0
"""|belief - truth| above which the estimate is considered to have taken
the spoof (half of the injected 50 m offset; clean runs stay < 1 m)."""

CAPTURE_RADIUS_M = 5.0
"""A mission corner counts as reached within this ground-truth radius.
Nominal SITL tracking error is well under 5 m (derived.ON_PLAN_TOLERANCE_M
docstring)."""


HOLD_ACTIONS = frozenset({"mode_loiter", "hold_zero_velocity"})
"""Recovery actions whose purpose is to keep the aircraft where it is."""


# --- pure functions ------------------------------------------------------


def estimate_jump_time(t_rel: list, div: list, threshold: float = JUMP_M) -> Optional[float]:
    """First t_rel >= 0 with divergence above threshold. None if never."""
    for t, d in zip(t_rel, div):
        if t >= 0.0 and d is not None and d > threshold:
            return float(t)
    return None


def tail_median(t_rel: list, values: list, t_end: float, tail: float) -> Optional[float]:
    """Median of values with t_end - tail <= t <= t_end. None if empty."""
    sel = [v for t, v in zip(t_rel, values) if t_end - tail <= t <= t_end and v is not None]
    return statistics.median(sel) if sel else None


def max_distance_from(samples: list, t_from: float, t_to: float) -> Optional[float]:
    """
    samples: [(t, north, east)] sorted by t.
    Max horizontal distance of the samples in [t_from, t_to] from the
    sample nearest to t_from. None if no sample in the interval.
    """
    seg = [s for s in samples if t_from <= s[0] <= t_to]
    if not seg:
        return None
    ref = min(samples, key=lambda s: abs(s[0] - t_from))
    return max(math.hypot(s[1] - ref[1], s[2] - ref[2]) for s in seg)


def count_captures(samples: list, corners: list, t_from: float, t_to: float,
                   radius: float = CAPTURE_RADIUS_M) -> int:
    """
    Mission corners reached in plan order within [t_from, t_to].

    The next expected corner is the first one the aircraft reaches after
    t_from (any corner may be first — the window starts mid-lap). After
    that only the next corner in the closed sequence counts, so hovering
    at one corner or cutting across the square does not inflate the
    count.
    """
    if not corners:
        return 0
    n = len(corners)
    seg = [s for s in samples if t_from <= s[0] <= t_to]
    expected = None
    count = 0
    inside = None  # index of the corner we are currently inside
    for _, north, east in seg:
        hit = None
        for i, (cn, ce) in enumerate(corners):
            if math.hypot(north - cn, east - ce) <= radius:
                hit = i
                break
        if hit is None:
            inside = None
            continue
        if hit == inside:
            continue
        inside = hit
        if expected is None or hit == expected:
            count += 1
            expected = (hit + 1) % n
    return count


# --- per-run ---------------------------------------------------------------


def analyse_run(run_dir: str) -> Optional[dict]:
    spath = os.path.join(run_dir, "run_summary.json")
    if not os.path.exists(spath):
        return None
    with open(spath) as fh:
        summary = json.load(fh)
    events = load_events(run_dir)
    traj = load_trajectory(run_dir)
    corners = plan_corners(summary)
    target = summary.get("target_uav") or ""
    t0 = _attack_ts(events)
    out = {
        "nav_error_end_m": None,
        "nav_error_peak_m": None,
        "t_estimate_jump_s": None,
        "t_first_response_s": None,
        "first_response_action": None,
        "post_response_drift_m": None,
        "waypoints_captured": None,
    }
    if t0 is None:
        return out

    bd = ((summary.get("belief_divergence") or {}).get("uavs") or {}).get(target) or {}
    t_rel = bd.get("t_rel_sec") or []
    div = bd.get("divergence_horiz_m") or []
    post = [d for t, d in zip(t_rel, div) if t >= 0.0 and d is not None]
    if post:
        out["nav_error_peak_m"] = max(post)
        out["nav_error_end_m"] = tail_median(t_rel, div, WINDOW_S, NAV_END_TAIL_S)
        out["t_estimate_jump_s"] = estimate_jump_time(t_rel, div)

    t_ack = attributable_ts(events, t0, target, ("recovery_ack",))
    samples = traj.get(target) or []
    if t_ack is not None:
        ack = next(
            e for e in events
            if e.get("event_type") == "recovery_ack"
            and float(e["timestamp"]) == t_ack
            and e.get("target_uav") == target
        )
        action = ack.get("action")
        out["t_first_response_s"] = t_ack - t0
        out["first_response_action"] = action
        if action in HOLD_ACTIONS:
            out["post_response_drift_m"] = max_distance_from(
                samples, t_ack, t0 + WINDOW_S)

    if samples:
        out["waypoints_captured"] = count_captures(samples, corners, t0, t0 + WINDOW_S)
    return out


def _run_dirs(root: str) -> dict:
    found = {}
    for dirpath, dirnames, _ in os.walk(root):
        base = os.path.basename(dirpath)
        if base.startswith("run_"):
            found[base[4:]] = dirpath
            dirnames[:] = []
    return found


def build(runs_root: str, master_csv: str) -> list:
    with open(master_csv) as fh:
        master = [r for r in csv.DictReader(fh) if r["valid"] == "True"]
    dirs = _run_dirs(runs_root)
    rows = []
    for m in master:
        d = dirs.get(m["run_id"])
        res = analyse_run(d) if d else None
        row = {
            "run_id": m["run_id"],
            "architecture": m["architecture"],
            "attack": m["attack"],
            "route_distance_m": m["mission_degradation_m"] or None,
        }
        row.update(res or {})
        rows.append(row)

    clean = {}
    for r in rows:
        if r["attack"] == "none" and r.get("waypoints_captured") is not None:
            clean.setdefault(r["architecture"], []).append(r["waypoints_captured"])
    ref = {a: statistics.median(v) for a, v in clean.items() if v}
    for r in rows:
        c = r.get("waypoints_captured")
        base = ref.get(r["architecture"])
        r["mission_execution"] = (c / base) if (c is not None and base) else None
    return rows


FIELDS = [
    "run_id", "architecture", "attack",
    "nav_error_end_m", "nav_error_peak_m", "t_estimate_jump_s",
    "t_first_response_s", "first_response_action", "post_response_drift_m",
    "route_distance_m", "waypoints_captured", "mission_execution",
]


def main(argv: list) -> int:
    if len(argv) != 4:
        print(__doc__.split("Usage")[1])
        return 2
    rows = build(argv[1], argv[2])
    with open(argv[3], "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in FIELDS})
    print(f"{len(rows)} valid runs -> {argv[3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
