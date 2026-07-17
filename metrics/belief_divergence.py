"""
belief_divergence -- true (Gazebo) vs believed (PX4 LOCAL_POSITION_NED)
position, item 2B of the pre-campaign instrumentation.

Why this exists
----------------
`estimator_series` (item 2A) records `pos_horiz_ratio` -- the EKF's own
residual between its GPS input and its prediction. It answers "did the
filter notice a discrepancy?" but not "how far off was the belief in
metres?". That second question needs ground truth (Gazebo) paired
against what PX4 actually believed (`LOCAL_POSITION_NED`), which is a
different channel recorded for exactly this purpose (see
`runners/monitor.py` DEFAULT_TELEMETRY_LOG_TYPES).

This module closes that gap for the truth-vs-belief leg. The third leg
(GPS_RAW_INT, the falsified input itself) is geodetic and needs the EKF
origin in lat/lon -- deferred; see PROJECT_STATE.md for status.

EKF origin -- measured, not configured
--------------------------------------
Gazebo's world frame is shared across the fleet; PX4's NED frame is
local to each UAV, zeroed at its own EKF origin. The fleet is spread in
Gazebo via `PX4_GZ_MODEL_POSE = instance*5,0,0`, so a healthy uav_1
would read ~5 m of "divergence" against raw Gazebo coordinates if that
offset is not removed first.

The offset is resolved from data (`resolve_ekf_origin`), not from the
`*5` constant. Two reasons: this module has no business knowing a
deployment's fleet-spacing config (architecture-blind, same as
`flight_check`), and the project already got an axis assumption wrong
once by reasoning about frames instead of measuring them (see
`metrics/estimator_series.py`'s AXIS CALIBRATION note in
PROJECT_STATE.md) -- the same discipline applies here.

Origin is the median Gazebo pose over samples recorded before the UAV's
first liftoff (`z < airborne_threshold_m`, chronologically first block),
not over every low-altitude sample in the run -- a crash or landing later
in the trial must not contaminate the reference point. `None` when no
pre-liftoff sample exists (recorder started after takeoff, or the UAV
never appears grounded); the caller must not substitute (0, 0, 0), which
would silently reintroduce the fleet-spacing bug this function exists to
remove.

Axis mapping
------------
Measured on `runs/run_c_none_1784272577` (baseline, 4383 paired
samples): Gazebo world is standard ENU, x = east, y = north.

    ned.north = gz.y - origin.y
    ned.east  = gz.x - origin.x
    ned.down  = -(gz.z - origin.z)

Frame
-----
Trajectory samples are Gazebo world ENU, z up, metres -- same source and
convention as `metrics/flight_check.py`.
"""

from __future__ import annotations

import bisect
import math
import statistics
from typing import Any, Optional


DEFAULT_AIRBORNE_THRESHOLD_M: float = 1.0
"""Mirrors `flight_check.DEFAULT_AIRBORNE_THRESHOLD_M` -- the same
ground/airborne boundary should define "pre-liftoff" here as it does
"flying" there. Duplicated, not imported: this module must stay readable
on its own, same rationale as the threshold duplication in
`estimator_series.py`."""


def resolve_ekf_origin(
    samples: list[dict[str, Any]],
    uav_id: str,
    *,
    airborne_threshold_m: float = DEFAULT_AIRBORNE_THRESHOLD_M,
) -> Optional[dict[str, Any]]:
    """Median Gazebo (x, y, z) over `uav_id`'s pre-liftoff ground samples.

    `samples` is the output of `metrics.flight_check.read_trajectory`
    (unfiltered, all UAVs, any order). Only the block of samples
    chronologically before the UAV's first crossing into
    `z >= airborne_threshold_m` is used -- a later crash or landing must
    not pull the origin estimate away from where the EKF actually
    started.

    Returns None if the UAV has no samples, or if its very first
    recorded sample is already airborne (the recorder started after
    liftoff -- there is no ground reference to measure). A caller must
    not default the result to (0, 0, 0): an unmeasured origin is a
    missing fact, not a fact that happens to be zero.
    """
    own = sorted(
        (s for s in samples if s["uav_id"] == uav_id),
        key=lambda s: s["t_wall"],
    )
    if not own:
        return None

    ground: list[dict[str, Any]] = []
    for s in own:
        if s["z"] >= airborne_threshold_m:
            break
        ground.append(s)

    if not ground:
        return None

    return {
        "x": statistics.median(s["x"] for s in ground),
        "y": statistics.median(s["y"] for s in ground),
        "z": statistics.median(s["z"] for s in ground),
        "n_samples": len(ground),
    }


# ---------------------------------------------------------------------------
# True (Gazebo) vs believed (PX4 LOCAL_POSITION_NED) divergence
# ---------------------------------------------------------------------------

DEFAULT_BELIEF_MSG_TYPE: str = "LOCAL_POSITION_NED"
"""PX4's own position estimate in its local NED frame, already zeroed at
the EKF origin. Fields: x = north, y = east, z = down (metres). This is
what GPS spoofing corrupts; pairing it against Gazebo truth measures how
far the attack moved the autopilot's belief."""

DEFAULT_PAIR_TOLERANCE_SEC: float = 0.2
"""Max wall-clock gap between a believed sample and the Gazebo sample it
is paired with. Gazebo records at ~4.6 Hz (~0.22 s spacing), so a
believed sample is at worst ~0.11 s from the nearest truth sample; 0.2 s
admits every real pair while rejecting a truth dropout. At ~4 m/s this
tolerance alone allows up to ~0.8 m of pure time-alignment error, which
is why sub-metre divergence must not be over-interpreted — the 50 m spoof
is what this instrument is sized for (see PROJECT_STATE 2A calibration)."""

DEFAULT_OUTPUT_RATE_HZ: float = 1.0
"""Believed NED arrives at ~30 Hz; the pair is rate-limited by the slower
side (Gazebo, ~4.6 Hz) and 30 Hz x 160 s x 3 UAV would not fit in
run_summary.json. Downsample the believed stream to one sample per
1/rate-second wall-clock bucket before pairing."""

_T_ROUND: int = 3
_V_ROUND: int = 4


def _ned_true(gz: dict[str, Any], origin: dict[str, Any]) -> dict[str, float]:
    """Gazebo world ENU pose -> local NED relative to the EKF origin.

    Axis map measured on baseline run_c_none_1784272577 (see module
    docstring): the square route is symmetric under an x/y swap, so this
    can only be fixed by data whose frame is pinned by spec
    (LOCAL_POSITION_NED), not by the trajectory itself.
    """
    return {
        "north": gz["y"] - origin["y"],
        "east": gz["x"] - origin["x"],
        "down": -(gz["z"] - origin["z"]),
    }


def _downsample(
    samples: list[dict[str, Any]], period_sec: float
) -> list[dict[str, Any]]:
    """Keep the first sample in each `period_sec` wall-clock bucket.

    First, not nearest-to-centre: cheap, deterministic, and the choice is
    immaterial at this ratio (~30 candidates per 1 s bucket, all within
    ~1 s of each other on a signal that moves slowly relative to the
    bucket)."""
    kept: list[dict[str, Any]] = []
    last_bucket: Optional[int] = None
    for s in sorted(samples, key=lambda r: r["t_wall"]):
        bucket = math.floor(s["t_wall"] / period_sec)
        if bucket != last_bucket:
            kept.append(s)
            last_bucket = bucket
    return kept


def _nearest(
    truth_t: list[float], truth: list[dict[str, Any]], t: float
) -> Optional[dict[str, Any]]:
    """Nearest truth sample to wall-time `t` by absolute gap, or None on
    an empty truth list."""
    if not truth_t:
        return None
    i = bisect.bisect_left(truth_t, t)
    best = None
    best_gap = None
    for j in (i - 1, i):
        if 0 <= j < len(truth_t):
            gap = abs(truth_t[j] - t)
            if best_gap is None or gap < best_gap:
                best_gap = gap
                best = truth[j]
    return best


def _uav_divergence(
    believed: list[dict[str, Any]],
    truth: list[dict[str, Any]],
    origin: Optional[dict[str, Any]],
    *,
    attack_at_wall: Optional[float],
    pair_tolerance_sec: float,
    output_rate_hz: float,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "origin": origin,
        "anchor": None,
        "n": 0,
        "n_unpaired": 0,
        "rate_hz": None,
        "t_rel_sec": [],
        "divergence_horiz_m": [],
        "divergence_3d_m": [],
        "baseline_median_horiz_m": None,
        "baseline_n": 0,
        "peak_horiz_m": None,
        "peak_t_rel_sec": None,
    }
    # Without an origin the truth cannot be placed in the believed frame,
    # so no divergence exists. None, not zero — an unmeasured offset is
    # missing data, and defaulting it to (0,0,0) is exactly the
    # fleet-spacing bug resolve_ekf_origin exists to prevent.
    if origin is None:
        return entry

    truth_ned = [
        {"t_wall": s["t_wall"], **_ned_true(s, origin)} for s in truth
    ]
    truth_ned.sort(key=lambda r: r["t_wall"])
    truth_t = [r["t_wall"] for r in truth_ned]

    period = 1.0 / output_rate_hz
    kept = _downsample(believed, period)

    paired: list[tuple[float, float, float]] = []  # (t_wall, horiz, 3d)
    n_unpaired = 0
    for b in kept:
        t = _nearest(truth_t, truth_ned, b["t_wall"])
        if t is None or abs(t["t_wall"] - b["t_wall"]) > pair_tolerance_sec:
            n_unpaired += 1
            continue
        data = b["data"]
        bn = _as_float(data.get("x"))
        be = _as_float(data.get("y"))
        bd = _as_float(data.get("z"))
        if bn is None or be is None or bd is None:
            n_unpaired += 1
            continue
        dn = bn - t["north"]
        de = be - t["east"]
        dd = bd - t["down"]
        horiz = math.hypot(dn, de)
        three = math.sqrt(dn * dn + de * de + dd * dd)
        paired.append((b["t_wall"], horiz, three))

    entry["n_unpaired"] = n_unpaired
    if not paired:
        return entry

    paired.sort(key=lambda p: p[0])

    if attack_at_wall is not None:
        anchor = "attack"
        zero = attack_at_wall
    else:
        anchor = "first_sample"
        zero = paired[0][0]
    entry["anchor"] = anchor

    t_rel = [round(p[0] - zero, _T_ROUND) for p in paired]
    horiz = [round(p[1], _V_ROUND) for p in paired]
    three = [round(p[2], _V_ROUND) for p in paired]
    entry["t_rel_sec"] = t_rel
    entry["divergence_horiz_m"] = horiz
    entry["divergence_3d_m"] = three
    entry["n"] = len(paired)

    span = paired[-1][0] - paired[0][0]
    if span > 0:
        entry["rate_hz"] = round((len(paired) - 1) / span, _V_ROUND)

    # Baseline: pre-attack when anchored to an attack, otherwise the whole
    # run (an un-attacked run is baseline end to end). Median, so one
    # transient does not move it.
    if anchor == "attack":
        base = [h for h, tr in zip(horiz, t_rel) if tr < 0.0]
    else:
        base = list(horiz)
    entry["baseline_n"] = len(base)
    if base:
        entry["baseline_median_horiz_m"] = round(
            statistics.median(base), _V_ROUND
        )

    peak_i = max(range(len(horiz)), key=lambda k: horiz[k])
    entry["peak_horiz_m"] = horiz[peak_i]
    entry["peak_t_rel_sec"] = t_rel[peak_i]
    return entry


def _as_float(v: Any) -> Optional[float]:
    """None for anything not a real finite number. `bool` rejected: it is
    an int subclass, so a stray True would silently read as 1.0 m."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def belief_divergence(
    trajectory_samples: list[dict[str, Any]],
    telemetry_samples: list[dict[str, Any]],
    attack_at_wall: Optional[float] = None,
    *,
    target_uav: Optional[str] = None,
    belief_msg_type: str = DEFAULT_BELIEF_MSG_TYPE,
    airborne_threshold_m: float = DEFAULT_AIRBORNE_THRESHOLD_M,
    pair_tolerance_sec: float = DEFAULT_PAIR_TOLERANCE_SEC,
    output_rate_hz: float = DEFAULT_OUTPUT_RATE_HZ,
) -> dict[str, Any]:
    """True-vs-believed position divergence per UAV, in metres.

    `trajectory_samples` are Gazebo poses (`flight_check.read_trajectory`);
    `telemetry_samples` are monitor telemetry records
    (`estimator_series.read_telemetry`), of which only `belief_msg_type`
    rows are used.

    Unlike `estimator_series`, this does NOT require an attack anchor: the
    axis calibration and the EKF noise floor are both measured on baseline
    (un-attacked) runs, where truth == belief, so a working baseline is
    the only condition under which a frame error is even distinguishable.
    With `attack_at_wall`, times are relative to injection and the
    baseline is pre-injection; without it, times are relative to the first
    paired sample and the whole run is baseline. The `anchor` field records
    which, so zero is never ambiguous.

    Diagnostic, NOT a metric source: the believed channel comes from a
    monitor inside the system under test and dies under `monitor_takeout`,
    so nothing in table 3.13 may be computed from it (same scope rule as
    `estimator_series`). Ground truth for metrics stays with Gazebo.
    """
    if output_rate_hz <= 0:
        raise ValueError("output_rate_hz must be positive")
    if pair_tolerance_sec < 0:
        raise ValueError("pair_tolerance_sec must be non-negative")

    believed_by_uav: dict[str, list[dict[str, Any]]] = {}
    n_belief_total = 0
    for s in telemetry_samples:
        if s.get("msg_type") != belief_msg_type:
            continue
        n_belief_total += 1
        believed_by_uav.setdefault(s["uav_id"], []).append(s)

    truth_by_uav: dict[str, list[dict[str, Any]]] = {}
    for s in trajectory_samples:
        truth_by_uav.setdefault(s["uav_id"], []).append(s)

    uav_ids = sorted(set(believed_by_uav) | set(truth_by_uav))
    uavs: dict[str, Any] = {}
    for uav_id in uav_ids:
        origin = resolve_ekf_origin(
            trajectory_samples,
            uav_id,
            airborne_threshold_m=airborne_threshold_m,
        )
        uavs[uav_id] = _uav_divergence(
            believed_by_uav.get(uav_id, []),
            truth_by_uav.get(uav_id, []),
            origin,
            attack_at_wall=attack_at_wall,
            pair_tolerance_sec=pair_tolerance_sec,
            output_rate_hz=output_rate_hz,
        )

    return {
        "belief_msg_type": belief_msg_type,
        "truth_frame": "gazebo_world_enu_z_up",
        "axis_map": "north=gz.y-oy; east=gz.x-ox; down=-(gz.z-oz)",
        "airborne_threshold_m": airborne_threshold_m,
        "pair_tolerance_sec": pair_tolerance_sec,
        "output_rate_hz": output_rate_hz,
        "attack_at_wall": attack_at_wall,
        "n_belief_samples_total": n_belief_total,
        "target_uav": target_uav,
        "uavs": uavs,
    }
