"""
metrics/trust_hold_probe.py — analysis for the stage-2 SITL probe of a
"do not trust position" hold action (review plan, stage 2, 2026-09-26).

Question
--------
Under the GZBridge GPS-offset spoof, LOITER holds the *estimated*
position; ~7.5 s after injection the EKF takes the spoof, the estimate
jumps by the injected 50 m and the aircraft is physically pushed ~50 m
(campaign median post_response_drift 50.0 m, arch C, GPS cell). The
spoof falsifies GPS *position* only (lat/lon in GZBridge, tag
OFFSET_INJECT); GPS velocity stays true. An action that holds ZERO
VELOCITY instead of a position therefore does not act on the channel the
attacker controls.

Pre-registered criteria (fixed before the first probe flight)
-------------------------------------------------------------
Action at t_inject + 3.0 s (≈ campaign C detection 2.95 s), same 60 s
window and definitions as metrics/physical_outcomes.py.

  valid       attack landed: t_estimate_jump_s is not None
              (|belief - truth| > 25 m at some t >= 0).
  control     loiter arm must reproduce the campaign: drift > 40 m.
              Otherwise the probe setup is wrong and nothing is concluded.
  PASS        zerovel arm: post_response_drift_m < 5 m (= CAPTURE_RADIUS_M)
              AND the action was accepted (no error, no mode fallback).
  FAIL        otherwise. Two attempts at most (review plan); after that
              stage 2 reports the negative result as is.

The action does NOT repair navigation: nav_error_end_m is expected to stay
~50 m in both arms. What is tested is only whether the aircraft stops
acting on the compromised channel. Stated limitation: a spoofer that also
falsifies GNSS velocity consistently would defeat zero-velocity hold.

Frames
------
Truth: Gazebo world ENU (x = east, y = north; verified 4383 samples),
uav_0 spawns at the world origin. Belief: PX4 LOCAL_POSITION_NED relative
to the EKF origin. The constant offset between the two is removed with the
median (truth - belief) over the pre-injection settle interval.
"""

from __future__ import annotations

import bisect
import json
import math
import statistics
from typing import Optional

from metrics.physical_outcomes import (
    CAPTURE_RADIUS_M,
    JUMP_M,
    NAV_END_TAIL_S,
    WINDOW_S,
    estimate_jump_time,
    max_distance_from,
    tail_median,
)

ACTION_T_S = 3.0
"""Action time after injection (campaign C median detection 2.95 s)."""

BIAS_WINDOW_S = 5.0
"""Pre-injection interval used to align belief to truth."""

PAIR_TOL_S = 0.5
"""Max |t_belief - t_truth| for a belief sample to be paired with truth."""

CONTROL_MIN_DRIFT_M = 40.0
"""Loiter control must drift more than this to reproduce the campaign."""

PASS_MAX_DRIFT_M = CAPTURE_RADIUS_M
"""Zero-velocity hold passes below this post-response drift."""


# --- loading -------------------------------------------------------------


def read_jsonl(path: str) -> list:
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def truth_ne(records: list, uav_id: str = "uav_0") -> list:
    """Gazebo records -> [(t_wall, north, east)] sorted. north = y, east = x."""
    s = [
        (float(r["t_wall"]), float(r["y"]), float(r["x"]))
        for r in records
        if r.get("uav_id") == uav_id
    ]
    s.sort()
    return s


def belief_ne(records: list) -> list:
    """Belief records {t_wall, n, e, ...} -> [(t_wall, north, east)] sorted."""
    s = [(float(r["t_wall"]), float(r["n"]), float(r["e"])) for r in records]
    s.sort()
    return s


# --- pure analysis -------------------------------------------------------


def _nearest(samples: list, t: float) -> Optional[tuple]:
    if not samples:
        return None
    ts = [s[0] for s in samples]
    i = bisect.bisect_left(ts, t)
    cands = [samples[j] for j in (i - 1, i) if 0 <= j < len(samples)]
    return min(cands, key=lambda s: abs(s[0] - t))


def _paired(truth: list, belief: list) -> list:
    """[(t, truth_n, truth_e, bel_n, bel_e)] at belief timestamps."""
    out = []
    for t, bn, be in belief:
        tr = _nearest(truth, t)
        if tr is not None and abs(tr[0] - t) <= PAIR_TOL_S:
            out.append((t, tr[1], tr[2], bn, be))
    return out


def nav_error_series(truth: list, belief: list, t_bias_from: float,
                     t_bias_to: float) -> list:
    """
    [(t, |belief - truth| horizontal)] after removing the frame offset,
    estimated as the median (truth - belief) over [t_bias_from, t_bias_to].
    Empty if no paired sample lies in the bias interval.
    """
    pairs = _paired(truth, belief)
    ref = [p for p in pairs if t_bias_from <= p[0] <= t_bias_to]
    if not ref:
        return []
    dn = statistics.median(p[1] - p[3] for p in ref)
    de = statistics.median(p[2] - p[4] for p in ref)
    return [
        (p[0], math.hypot(p[3] + dn - p[1], p[4] + de - p[2])) for p in pairs
    ]


def summarize(truth: list, belief: list, t_inject: float,
              t_action: Optional[float], window: float = WINDOW_S) -> dict:
    """All times in the returned dict are relative to t_inject."""
    nav = nav_error_series(truth, belief, t_inject - BIAS_WINDOW_S, t_inject)
    t_rel = [t - t_inject for t, _ in nav]
    err = [e for _, e in nav]

    t_end = t_inject + window
    rel_truth = [(t - t_inject, n, e) for t, n, e in truth]
    drift = None
    drift_end = None
    if t_action is not None:
        drift = max_distance_from(rel_truth, t_action - t_inject, window)
        seg = [s for s in rel_truth if s[0] <= window]
        if seg:
            ref = min(rel_truth, key=lambda s: abs(s[0] - (t_action - t_inject)))
            last = seg[-1]
            drift_end = math.hypot(last[1] - ref[1], last[2] - ref[2])

    return {
        "t_estimate_jump_s": estimate_jump_time(t_rel, err, JUMP_M),
        "nav_error_peak_m": max((e for t, e in zip(t_rel, err) if t >= 0), default=None),
        "nav_error_end_m": tail_median(t_rel, err, window, NAV_END_TAIL_S),
        "t_action_s": None if t_action is None else t_action - t_inject,
        "post_response_drift_m": drift,
        "drift_at_window_end_m": drift_end,
        "n_truth": sum(1 for t, _, _ in truth if t_inject <= t <= t_end),
        "n_belief": sum(1 for t, _, _ in belief if t_inject <= t <= t_end),
    }


def verdict(action: str, summary: dict, action_error: Optional[str] = None,
            fallback_mode: Optional[str] = None) -> str:
    """Apply the pre-registered criteria to one probe run."""
    if summary.get("t_estimate_jump_s") is None:
        return "INVALID: attack did not land (no estimate jump)"
    drift = summary.get("post_response_drift_m")
    if drift is None:
        return "INVALID: no ground truth after the action"
    if action == "loiter":
        if drift > CONTROL_MIN_DRIFT_M:
            return f"CONTROL OK: loiter drift {drift:.1f} m > {CONTROL_MIN_DRIFT_M:.0f} m"
        return f"CONTROL INVALID: loiter drift {drift:.1f} m does not reproduce the campaign"
    if action_error:
        return f"FAIL: action rejected ({action_error})"
    if fallback_mode:
        return f"FAIL: autopilot left the action (mode {fallback_mode})"
    if drift < PASS_MAX_DRIFT_M:
        return f"PASS: drift {drift:.1f} m < {PASS_MAX_DRIFT_M:.0f} m"
    return f"FAIL: drift {drift:.1f} m >= {PASS_MAX_DRIFT_M:.0f} m"
