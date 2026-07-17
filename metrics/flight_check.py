"""
flight_check — was the UAV actually flying when the attack fired?

Why this exists
---------------
Every attack in runs_v1, runs_v2 and results R1-R4 hit a **hovering**
UAV. The single-lap route finished at t~57 s while attacks fire at
t=90 s. Nobody noticed for 120 runs, because nothing in the pipeline
recorded the answer: the question was only answerable by hand-reading a
Gazebo trajectory, and it was only asked once, late (RESULTS_NOTES
OPEN-1 / R7).

`mission.laps` fixed the route. This module fixes the *blind spot* — it
makes "was it flying?" a field in `run_summary.json` for every run, so a
recurrence is caught by reading one boolean instead of by re-deriving a
trajectory. That matters most on the ~1160-trial campaign, where
re-running is not an option and the failure is silent by construction.

Ground truth only
-----------------
Input is Gazebo model poses (`trajectory.jsonl`), which are the
simulator's own physics state. This is deliberate and is the whole
point: PX4's estimate is corrupted by GPS spoofing by construction, and
monitors are killed by the takeout attacks. An answer derived from
either would be an answer from inside the system under test. Gazebo
cannot be spoofed by a PX4 param.

The functions here are architecture-blind: they read poses and a
timestamp. Nothing branches on A/B/C, so the identical-measurement-
procedure requirement (thesis 3.5.5, table 3.14) holds by construction
rather than by discipline.

Frame
-----
Gazebo world frame, Z **up** (ENU), metres. Verified against
`runs_v3/run_C_gps_spoofing_r16_*`: uav_0 at a 20 m cruise reads
z = +19.81 / +20.21. So `alt_m = z` directly, with no sign flip. This
is measured, not assumed — the NED convention (z down) is equally
common in this stack and would silently invert every `airborne` flag.

Thresholds
----------
Defaults are arguments, and the value used is written into the output
dict next to the numbers it produced. A threshold baked into code is a
hidden assumption a reviewer cannot audit; one recorded beside its
result is reproducible, and lets a later analysis re-derive the booleans
from the raw speeds without re-flying anything.

`DEFAULT_MOTION_THRESHOLD_MPS = 0.5` sits in a 50x gap measured in R7:
hovering reads v ~ 0.03 m/s, mission flight reads v = 1.5-5.1 m/s. Any
value in that gap classifies identically; 0.5 is not tuned.

Speed
-----
Path length between consecutive samples divided by elapsed time, not
endpoint displacement over dt. Gazebo poses carry no sensor noise (they
are the physics state), so path length costs nothing in robustness and
does not read ~0 for a UAV that rounds a corner inside the window.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Defaults — overridable; the effective value is recorded in the output.
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_SEC: float = 1.0
"""Half-width of the sampling window around the attack timestamp. At the
recorder's 5 Hz this yields ~10 samples, enough for a stable speed while
staying short enough that the UAV cannot meaningfully change regime
inside it."""

DEFAULT_MOTION_THRESHOLD_MPS: float = 0.5
DEFAULT_AIRBORNE_THRESHOLD_M: float = 1.0


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_trajectory(path: Path | str) -> list[dict[str, Any]]:
    """Load `trajectory.jsonl` into pose samples.

    Tolerant by contract: a missing file, an unreadable file, a truncated
    final line (the recorder is killed at teardown, so this is normal) or
    a malformed record yields fewer samples, never an exception. A
    degraded flight check must not fail a run that otherwise succeeded —
    it degrades to `n_samples: 0`, which the summary reports honestly as
    missing data rather than as "not flying".
    """
    out: list[dict[str, Any]] = []
    p = Path(path)
    try:
        with p.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                try:
                    sample = {
                        "t_wall": float(rec["t_wall"]),
                        "uav_id": str(rec["uav_id"]),
                        "x": float(rec.get("x", 0.0)),
                        "y": float(rec.get("y", 0.0)),
                        "z": float(rec.get("z", 0.0)),
                    }
                except (KeyError, TypeError, ValueError):
                    continue
                out.append(sample)
    except OSError:
        return out
    return out


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


def _per_uav_state(
    window: list[dict[str, Any]],
    t_wall: float,
    *,
    motion_threshold_mps: float,
    airborne_threshold_m: float,
) -> dict[str, Any]:
    """Reduce one UAV's in-window samples to a state dict.

    `None` means "not measurable from the data available", which is a
    different fact from `False` and must not collapse into it: a run with
    no trajectory recorder did not observe a hovering UAV, it observed
    nothing.
    """
    state: dict[str, Any] = {
        "n_samples": len(window),
        "t_offset_sec": None,
        "dt_sec": None,
        "x": None,
        "y": None,
        "alt_m": None,
        "speed_horiz_mps": None,
        "speed_mps": None,
        "in_motion": None,
        "airborne": None,
        "flying": None,
    }
    if not window:
        return state

    nearest = min(window, key=lambda s: abs(s["t_wall"] - t_wall))
    state["t_offset_sec"] = nearest["t_wall"] - t_wall
    state["x"] = nearest["x"]
    state["y"] = nearest["y"]
    state["alt_m"] = nearest["z"]
    state["airborne"] = nearest["z"] >= airborne_threshold_m

    if len(window) >= 2:
        dt = window[-1]["t_wall"] - window[0]["t_wall"]
        if dt > 0:
            path_h = 0.0
            path_3d = 0.0
            for a, b in zip(window, window[1:]):
                dx = b["x"] - a["x"]
                dy = b["y"] - a["y"]
                dz = b["z"] - a["z"]
                path_h += math.hypot(dx, dy)
                path_3d += math.sqrt(dx * dx + dy * dy + dz * dz)
            state["dt_sec"] = dt
            state["speed_horiz_mps"] = path_h / dt
            state["speed_mps"] = path_3d / dt
            state["in_motion"] = (path_h / dt) >= motion_threshold_mps

    if state["in_motion"] is not None and state["airborne"] is not None:
        state["flying"] = bool(state["in_motion"] and state["airborne"])
    return state


def _all_true(values: list[Optional[bool]]) -> Optional[bool]:
    """True/False over a fleet, or None if any member is unmeasurable.

    A fleet verdict computed over partial data would be a claim the data
    does not support.
    """
    if not values or any(v is None for v in values):
        return None
    return all(bool(v) for v in values)


def flight_state_at(
    samples: list[dict[str, Any]],
    t_wall: Optional[float],
    *,
    target_uav: Optional[str] = None,
    window_sec: float = DEFAULT_WINDOW_SEC,
    motion_threshold_mps: float = DEFAULT_MOTION_THRESHOLD_MPS,
    airborne_threshold_m: float = DEFAULT_AIRBORNE_THRESHOLD_M,
) -> Optional[dict[str, Any]]:
    """Physical state of every UAV at `t_wall`, from ground-truth poses.

    Returns None when `t_wall` is None — a baseline run has no attack
    instant, so the question does not apply and inventing an answer for
    it would be worse than omitting one.

    The returned dict is written verbatim into `run_summary.json` as
    `flight_at_attack`, so it carries its own thresholds and window: the
    committed dataset must be self-describing (`*.jsonl` is gitignored,
    and `configs/experiment.yaml` changes between OPEN-2 sweeps).
    """
    if t_wall is None:
        return None
    if window_sec <= 0:
        raise ValueError("window_sec must be positive")

    by_uav: dict[str, list[dict[str, Any]]] = {}
    for s in samples:
        by_uav.setdefault(s["uav_id"], []).append(s)

    uavs: dict[str, dict[str, Any]] = {}
    for uav_id in sorted(by_uav):
        window = sorted(
            (
                s
                for s in by_uav[uav_id]
                if abs(s["t_wall"] - t_wall) <= window_sec
            ),
            key=lambda s: s["t_wall"],
        )
        uavs[uav_id] = _per_uav_state(
            window,
            t_wall,
            motion_threshold_mps=motion_threshold_mps,
            airborne_threshold_m=airborne_threshold_m,
        )

    target_state = uavs.get(target_uav) if target_uav else None

    return {
        "t_wall": t_wall,
        "window_sec": window_sec,
        "motion_threshold_mps": motion_threshold_mps,
        "airborne_threshold_m": airborne_threshold_m,
        "frame": "gazebo_world_enu_z_up",
        "n_samples_total": len(samples),
        "target_uav": target_uav,
        "target_in_motion": (
            target_state["in_motion"] if target_state else None
        ),
        "target_flying": target_state["flying"] if target_state else None,
        "all_in_motion": _all_true([u["in_motion"] for u in uavs.values()]),
        "all_flying": _all_true([u["flying"] for u in uavs.values()]),
        "uavs": uavs,
    }


# ---------------------------------------------------------------------------
# Mission plan — the reference frame for everything above
# ---------------------------------------------------------------------------


def mission_plan_summary(
    mission_cfg: Any,
    *,
    attack_at_sec: Optional[float] = None,
    observation_after_attack_sec: Optional[float] = None,
) -> dict[str, Any]:
    """JSON-able description of the flown plan, for `run_summary.json`.

    Not decoration. A bare `x = 27.5, y = 0.5` means nothing without the
    route it belongs to, so mission resilience and coordination integrity
    (thesis 3.4.5, 3.5.4) are computed *relative to the plan*. Three
    reasons this has to travel with the run rather than be looked up
    later:

    - `*.jsonl` is gitignored; `run_summary.json` is what gets committed,
      so it has to be self-contained or the dataset is uninterpretable
      later.
    - OPEN-2 sweeps `laps`, so `configs/experiment.yaml` will not match
      the runs already on disk.
    - a run that does not describe its own plan is exactly the failure
      class that produced OPEN-1.

    Waypoint indices are NOT resolved here: with `laps: 5` the square
    repeats, so lap 1 and lap 3 are physically identical and a
    nearest-waypoint guess is ambiguous. Real mission progress needs
    PX4's believed item index (instrumentation item 2) alongside the true
    position. Recording the plan now is what keeps that open.
    """
    laps = int(getattr(mission_cfg, "laps", 1) or 1)
    waypoints = tuple(getattr(mission_cfg, "waypoints", ()) or ())

    def _wp(w: Any) -> dict[str, float]:
        return {
            "north_m": float(w.north_m),
            "east_m": float(w.east_m),
            "alt_m": float(w.alt_m),
        }

    try:
        lap_waypoints = [_wp(w) for w in mission_cfg.lap_waypoints]
    except Exception:
        n = len(waypoints) // laps if laps else len(waypoints)
        lap_waypoints = [_wp(w) for w in waypoints[:n]]

    return {
        "type": str(getattr(mission_cfg, "type", "")),
        "duration_sec": float(getattr(mission_cfg, "duration_sec", 0.0)),
        "laps": laps,
        "n_waypoints": len(waypoints),
        "lap_waypoints": lap_waypoints,
        "waypoints": [_wp(w) for w in waypoints],
        "attack_at_sec": attack_at_sec,
        "observation_after_attack_sec": observation_after_attack_sec,
    }
