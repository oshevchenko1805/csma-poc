"""
metrics/h3_analysis.py — pre-registered analysis of H3 (review stage 5, B1:
inter-UAV ranging).

Rules: H3_PREREGISTRATION.md ("Inclusion", "Metrics", "Decision rule",
[2b]/[2c] numbers). This module is the executable form of that document
and is committed BEFORE the first B1 flight. After the first flight a
rule changes only through a dated, reasoned entry in "Amendments", and
the original rule's result is still reported.

Time anchor
-----------
t0 = attack_evidence.gps_spoofing.t_target_set: the wall-clock instant
SIM_GPS_OFF_N was written. With a spoof rate, fire() first reads and
writes SIM_GPS_OFF_R, so the runner's inject_start marker
(attack_fired_wall) precedes the real onset; it is used only for
no-attack flights (no injection) and reported as inject_lag_s.
Every t_* below is relative to t0. Window W = 120 s.

Inclusion (per flight; an outcome is NEVER a reason to exclude)
--------------------------------------------------------------
attack flights:  no run error; t_target_set present; spoof rate
                 confirmed by read-back (rate_confirmed is True); the
                 GPS_RAW_INT offset against truth at the end of W is
                 >= 5 m (B0 spoof_offset_series, median over [W-1, W]).
no-attack:       no run error.
Excluded flights are listed with the reason and re-flown.

Per-flight metrics (B0 definitions reused from metrics.spoof_rate_probe)
-----------------------------------------------------------------------
t_rng_peer_s     first ranging alarm against uav_0 raised by another
                 monitor, in [0, W]; None if none.
t_rng_self_s     same, raised by uav_0's own monitor (self path).
t_rng_s          min of the two.
t_gps_s, t_cc_s  first gps / cross_check alarm against uav_0 in [0, W].
harm_at_alarm_m  |belief - truth| of uav_0 at t_rng (median within
                 +-0.25 s; frame offset removed over the 5 s before t0).
t_jump_s         first t in [0, W] with |belief - truth| > 25 m.
max_step_1s_m    largest 1 s increase of |belief - truth| in [0, W].
nav_error_end_m  median |belief - truth| over [W - 10, W].
misattributions  ranging alarms naming uav_1 or uav_2 in [0, W] of an
                 attack flight (split: by the victim's monitor / by peers).
false_alarms     every ranging alarm of a no-attack flight (whole flight).
S3:  drift_itt_m (H2 definition, window [t_ack, t0 + W]; +inf if the arm
     acts and no action succeeded), creep_mps (median truth horizontal
     speed of uav_0 over [t_ack + 5 s, t0 + W]), vel_err_mps (median
     |EKF velocity - truth velocity|, same interval; truth velocity =
     1 s central difference of the Gazebo track).

Decision (L1 @ detect_only, n = 5; no-attack, n = 3)
----------------------------------------------------
L1 flight passes iff ranging alarm against uav_0 within W, harm_at_alarm
<= H_max = 6.8 m, no misattribution.
  CONFIRMED       5/5 pass, 0 false alarms, v1 detectors silent at L1
  PARTIAL         3-4/5 pass, or 5/5 detect but some harm > H_max;
                  0 false alarms
  NOT CONFIRMED   otherwise, or any false alarm
  NOT APPLICABLE  a v1 detector fired at L1 (blind zone not reproduced)
Reported with the Wilson 95 % CI of k/5 and every per-flight value.
P-B1-2 (L10, L30): FALSIFIED if t_rng < t_jump - 0.5 s in any flight.

During the flights only `status` is allowed (batch counts, injection
check). `--final` computes the metrics; use it after S1-S3 are complete.

Usage:
    python3 -m metrics.h3_analysis <runs_root>            # status only
    python3 -m metrics.h3_analysis <runs_root> --final    # rows + verdict
"""

from __future__ import annotations

import json
import math
import os
import statistics
import sys
from typing import Optional

from detectors.ranging import RangingConsistencyDetector as _Rng
from metrics.derived import _attack_ts, load_events, load_trajectory
from metrics.h2_analysis import BOUND_M as H2_BOUND_M
from metrics.h2_analysis import first_ok_ack
from metrics.peer_separation import load_world_xyz
from metrics.peer_separation import summarize as peer_summary
from metrics.physical_outcomes import JUMP_M, NAV_END_TAIL_S, max_distance_from
from metrics.spoof_rate_probe import (
    INJECTED_MIN_M,
    interp,
    max_step,
    nav_error_series,
    spoof_offset_series,
    value_at,
)
from metrics.stats import wilson_bounds

# --- frozen before the first B1 flight (H3_PREREGISTRATION.md) -------------

THETA_M = 1.8           # [2b] calibration on stage-3 pre-injection windows
THETA_OK_M = 1.3        # [2c] calibration max 1.24 m rounded up, no margin
SUSTAIN = 3             # k = 3 consecutive announcements
H_MAX_M = THETA_M + 5.0  # 6.8 m, same form as the H2 bound
WINDOW_S = 120.0        # observation after injection
VICTIM = "uav_0"
PEERS = ("uav_1", "uav_2")

LEVEL_RATES = {"L30": 0.02, "L10": 0.006667, "L3": 0.002, "L1": 0.0006667}
"""SIM_GPS_OFF_R per level (prereg "Attack"; v0 = r * 30 Hz * 50 m)."""
RATE_REL_TOL = 0.01

PLANNED = {
    "none@detect_only": 3,
    "L1@detect_only": 5,
    "L3@detect_only": 2,
    "L10@detect_only": 2,
    "L30@detect_only": 2,
    "DT+L1@detect_only": 2,
    "L1@proportionate": 2,
    "L1@trust_aware": 2,
}
SERIES = {
    "none@detect_only": "S1", "L1@detect_only": "S1", "L3@detect_only": "S1",
    "L10@detect_only": "S1", "L30@detect_only": "S1",
    "DT+L1@detect_only": "S2",
    "L1@proportionate": "S3", "L1@trust_aware": "S3",
}
CONFIRMATORY_CELL = "L1@detect_only"
NO_ATTACK_CELL = "none@detect_only"
FAST_CELLS = ("L10@detect_only", "L30@detect_only")
ACTING_POLICIES = ("proportionate", "trust_aware")

HARM_HALF_S = 0.25      # harm_at_alarm: median within +-0.25 s (B0)
JUMP_TOL_S = 0.5        # P-B1-2 tolerance
ACK_SETTLE_S = 5.0      # creep / vel_err start after the action ack
CREEP_LIMIT_MPS = 0.5   # prereg: creep >= 0.5 m/s -> limit of H2
VEL_DT_S = 1.0          # central difference for truth velocity

# --- cell assignment -------------------------------------------------------


def level_of_rate(rate) -> Optional[str]:
    """SIM_GPS_OFF_R -> level name, None if it matches no level."""
    if rate is None:
        return None
    for name, r in LEVEL_RATES.items():
        if abs(float(rate) - r) <= RATE_REL_TOL * r:
            return name
    return None


def gps_evidence(summary: dict) -> dict:
    return ((summary.get("attack_evidence") or {}).get("gps_spoofing")) or {}


def cell_of(summary: dict) -> str:
    """'<level>@<policy>', 'DT+<level>@<policy>' or 'none@<policy>'."""
    attack = summary.get("attack_name") or "none"
    policy = (summary.get("recovery_settings") or {}).get("policy")
    if attack == "none":
        return f"none@{policy}"
    level = level_of_rate(gps_evidence(summary).get("spoof_rate")) or "L?"
    prefix = "DT+" if attack.startswith("detector_takeout+") else ""
    if "gps_spoofing" not in attack.split("+"):
        return f"{attack}@{policy}"
    return f"{prefix}{level}@{policy}"


# --- events ----------------------------------------------------------------


def _monitor_of(e: dict) -> Optional[str]:
    ev = e.get("evidence") or {}
    m = ev.get("monitor_uav")
    if m:
        return m
    src = e.get("source") or ""
    return src[len("monitor_"):] if src.startswith("monitor_") else None


def ranging_alarms(events: list) -> list:
    """[(t_wall, monitor, target, path)] of every ranging SecurityEvent."""
    out = []
    for e in events:
        if e.get("event_type") != "security" or e.get("detector") != "ranging":
            continue
        mon = _monitor_of(e)
        tgt = e.get("target_uav")
        path = (e.get("evidence") or {}).get("path") or (
            "self" if mon == tgt else "peer")
        out.append((float(e["timestamp"]), mon, tgt, path))
    return sorted(out, key=lambda a: a[0])


def first_alarm(events: list, detector: str, target: str, t0: float,
                w: float = WINDOW_S, monitors=None,
                exclude_monitors=()) -> Optional[float]:
    """First alarm of `detector` against `target` in [t0, t0 + w], relative
    to t0. monitors / exclude_monitors filter on the raising monitor."""
    best = None
    for e in events:
        if e.get("event_type") != "security" or e.get("detector") != detector:
            continue
        if e.get("target_uav") != target:
            continue
        mon = _monitor_of(e)
        if monitors is not None and mon not in monitors:
            continue
        if mon in exclude_monitors:
            continue
        t = float(e["timestamp"]) - t0
        if 0.0 <= t <= w and (best is None or t < best):
            best = t
    return best


def config_problems(summary: dict, events: list) -> list:
    """Anything that makes the flight differ from the pre-registered setup
    (not an outcome): architecture, range source + seed, detector
    constants carried by the ranging events."""
    probs = []
    if summary.get("architecture") != "C":
        probs.append(f"architecture {summary.get('architecture')!r} != 'C'")
    rs = summary.get("range_source")
    if not isinstance(rs, dict) or rs.get("seed") is None:
        probs.append("run_summary has no range_source with a seed")
    for e in events:
        if e.get("event_type") != "security" or e.get("detector") != "ranging":
            continue
        ev = e.get("evidence") or {}
        got = (ev.get("theta_m"), ev.get("theta_ok_m"), ev.get("sustain"))
        if got != (THETA_M, THETA_OK_M, SUSTAIN):
            probs.append(f"ranging event constants {got} != "
                         f"{(THETA_M, THETA_OK_M, SUSTAIN)}")
            break
    return probs


# --- series ----------------------------------------------------------------


def load_telemetry(run_dir: str, uav: str = VICTIM) -> dict:
    """{'belief': [(t, n, e)], 'vel': [(t, vn, ve)], 'gps': [(t, lat, lon)]}
    from the uav's monitor telemetry log (LOCAL_POSITION_NED is NED:
    x = north, y = east; GPS_RAW_INT lat/lon in 1e-7 deg)."""
    out = {"belief": [], "vel": [], "gps": []}
    path = os.path.join(run_dir, f"telemetry_monitor_{uav}.jsonl")
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        for line in fh:
            try:
                r = json.loads(line)
                t, d, m = float(r["timestamp"]), r["data"], r.get("msg_type")
                if m == "LOCAL_POSITION_NED":
                    out["belief"].append((t, float(d["x"]), float(d["y"])))
                    if d.get("vx") is not None and d.get("vy") is not None:
                        out["vel"].append((t, float(d["vx"]), float(d["vy"])))
                elif m == "GPS_RAW_INT":
                    out["gps"].append((t, d["lat"] / 1e7, d["lon"] / 1e7))
            except (ValueError, KeyError, TypeError):
                continue
    for v in out.values():
        v.sort()
    return out


def truth_velocity(truth: list, t: float, dt: float = VEL_DT_S) -> Optional[tuple]:
    """(v_north, v_east) of the truth track at t, central difference over dt."""
    ts = [s[0] for s in truth]
    a = interp(truth, t - dt / 2, ts=ts)
    b = interp(truth, t + dt / 2, ts=ts)
    if a is None or b is None:
        return None
    return (b[0] - a[0]) / dt, (b[1] - a[1]) / dt


def creep_and_vel_err(truth: list, vel: list, t_from: float,
                      t_to: float) -> tuple:
    """(creep_mps, vel_err_mps) over [t_from, t_to]; None where no data."""
    speeds = []
    for t, _n, _e in truth:
        if t_from <= t <= t_to:
            v = truth_velocity(truth, t)
            if v is not None:
                speeds.append(math.hypot(*v))
    errs = []
    for t, vn, ve in vel:
        if t_from <= t <= t_to:
            v = truth_velocity(truth, t)
            if v is not None:
                errs.append(math.hypot(vn - v[0], ve - v[1]))
    return (statistics.median(speeds) if speeds else None,
            statistics.median(errs) if errs else None)


# --- per flight --------------------------------------------------------------


def _marker(events: list, phase: str) -> Optional[float]:
    for e in events:
        if e.get("event_type") == "attack" and e.get("phase") == phase:
            return float(e["timestamp"])
    return None


def exclusion_reason(summary: dict, is_attack: bool,
                     spoof_end_m: Optional[float]) -> Optional[str]:
    """Pre-registered inclusion; None = included. Never looks at outcomes."""
    if summary.get("error"):
        return f"run error: {summary['error']}"
    if not is_attack:
        return None
    ev = gps_evidence(summary)
    if ev.get("t_target_set") is None:
        return "no t_target_set (injection instant unknown)"
    if ev.get("rate_confirmed") is not True:
        return f"spoof rate not confirmed by read-back ({ev.get('rate_confirmed')})"
    if spoof_end_m is None or spoof_end_m < INJECTED_MIN_M:
        return f"injection not observed: GPS offset at W = {spoof_end_m} m < {INJECTED_MIN_M} m"
    return None


def analyse_flight(summary: dict, events: list, truth: list, belief: list,
                   vel: list, gps: list, track: Optional[list] = None,
                   world_xyz: Optional[dict] = None) -> dict:
    """One flight -> one row. truth/belief/vel/gps are uav_0's series
    (see load_telemetry; truth = [(t, north, east)] from load_trajectory).
    track = uav_0's own-frame truth for drift (default: truth)."""
    track = truth if track is None else track
    cell = cell_of(summary)
    policy = (summary.get("recovery_settings") or {}).get("policy")
    is_attack = not cell.startswith("none@")
    ev = gps_evidence(summary)
    t_start = _marker(events, "inject_start") or _attack_ts(events)
    t_end = _marker(events, "inject_end")
    t0 = ev.get("t_target_set") if is_attack else t_start
    rs = summary.get("range_source") if isinstance(summary.get("range_source"), dict) else {}
    row = {
        "run_id": summary.get("run_id"), "cell": cell, "series": SERIES.get(cell),
        "policy": policy, "attack": summary.get("attack_name"),
        "spoof_rate": ev.get("spoof_rate"), "range_seed": rs.get("seed"),
        "error": summary.get("error"),
        "inject_lag_s": (t0 - t_start) if (t0 is not None and t_start is not None) else None,
        "window_short_s": (max(0.0, t0 + WINDOW_S - t_end)
                           if (t0 is not None and t_end is not None) else None),
        "config_problems": config_problems(summary, events),
    }
    alarms = ranging_alarms(events)
    spoof_end = None
    if is_attack and t0 is not None:
        spoof = spoof_offset_series(gps, truth, t0)
        spoof_end = value_at(spoof, WINDOW_S - 1.0, 1.0)
    row["spoof_at_window_end_m"] = spoof_end
    reason = exclusion_reason(summary, is_attack, spoof_end)
    row["included"] = reason is None
    row["exclusion_reason"] = reason
    if not is_attack:
        row["false_alarms"] = len(alarms)
        row["false_alarm_list"] = [
            {"t_rel_s": (a[0] - t0) if t0 is not None else None,
             "monitor": a[1], "target": a[2], "path": a[3]} for a in alarms]
        return row
    if t0 is None:
        return row

    row["ranging_alarms_before_injection"] = sum(1 for a in alarms if a[0] < t0)
    row["t_rng_peer_s"] = first_alarm(events, "ranging", VICTIM, t0,
                                      exclude_monitors=(VICTIM,))
    row["t_rng_self_s"] = first_alarm(events, "ranging", VICTIM, t0,
                                      monitors=(VICTIM,))
    got = [x for x in (row["t_rng_peer_s"], row["t_rng_self_s"]) if x is not None]
    row["t_rng_s"] = min(got) if got else None
    row["t_gps_s"] = first_alarm(events, "gps", VICTIM, t0)
    row["t_cc_s"] = first_alarm(events, "cross_check", VICTIM, t0)
    mis = [a for a in alarms
           if 0.0 <= a[0] - t0 <= WINDOW_S and a[2] != VICTIM]
    row["misattributions"] = len(mis)
    row["misattr_by_victim_monitor"] = sum(1 for a in mis if a[1] == VICTIM)
    row["misattr_by_peer_monitors"] = sum(1 for a in mis if a[1] != VICTIM)
    row["misattribution_list"] = [
        {"t_rel_s": a[0] - t0, "monitor": a[1], "target": a[2]} for a in mis]

    nav = nav_error_series(truth, belief, t0)
    navw = [(t, e) for t, e in nav if 0.0 <= t <= WINDOW_S]
    row["t_jump_s"] = next((t for t, e in navw if e > JUMP_M), None)
    row["max_step_1s_m"] = max_step(nav, 1.0, 0.0, WINDOW_S)
    row["nav_error_end_m"] = value_at(navw, WINDOW_S - NAV_END_TAIL_S / 2,
                                      NAV_END_TAIL_S / 2)
    row["nav_error_max_m"] = max((e for _, e in navw), default=None)
    row["harm_at_alarm_m"] = (value_at(navw, row["t_rng_s"], HARM_HALF_S)
                              if row["t_rng_s"] is not None else None)
    row["harm_at_peer_alarm_m"] = (value_at(navw, row["t_rng_peer_s"], HARM_HALF_S)
                                   if row["t_rng_peer_s"] is not None else None)

    ack = first_ok_ack(events, t0, VICTIM)
    row.update(action_ok=ack is not None, action=ack[1] if ack else None,
               t_action_s=(ack[0] - t0) if ack else None,
               drift_itt_m=None, creep_mps=None, vel_err_mps=None)
    if ack is not None:
        row["drift_itt_m"] = max_distance_from(track, ack[0], t0 + WINDOW_S)
        row["creep_mps"], row["vel_err_mps"] = creep_and_vel_err(
            truth, vel, ack[0] + ACK_SETTLE_S, t0 + WINDOW_S)
    elif policy in ACTING_POLICIES:
        row["drift_itt_m"] = math.inf
    if world_xyz:
        row.update({f"peer_{k}": v for k, v in
                    peer_summary(world_xyz, VICTIM, t0, WINDOW_S).items()})

    if cell == CONFIRMATORY_CELL:
        row["passes"] = bool(
            row["t_rng_s"] is not None
            and row["harm_at_alarm_m"] is not None
            and row["harm_at_alarm_m"] <= H_MAX_M
            and row["misattributions"] == 0)
    return row


def run_row(run_dir: str) -> dict:
    with open(os.path.join(run_dir, "run_summary.json")) as fh:
        s = json.load(fh)
    s.setdefault("run_id", os.path.basename(run_dir.rstrip("/")))
    tel = load_telemetry(run_dir, VICTIM)
    truth = load_trajectory(run_dir).get(VICTIM) or []
    return analyse_flight(s, load_events(run_dir), truth, tel["belief"],
                          tel["vel"], tel["gps"], world_xyz=load_world_xyz(run_dir))


# --- verdict -----------------------------------------------------------------


def status(rows: list) -> dict:
    """What may be looked at during the flights: counts and exclusions."""
    cells = {}
    for c, n in PLANNED.items():
        inc = [r for r in rows if r["cell"] == c and r["included"]]
        cells[c] = {"planned": n, "included": len(inc), "missing": max(0, n - len(inc))}
    return {
        "cells": cells,
        "complete": all(v["missing"] == 0 for v in cells.values()),
        "excluded": [(r["run_id"], r["cell"], r["exclusion_reason"])
                     for r in rows if not r["included"]],
        "unplanned": sorted(r["run_id"] for r in rows if r["cell"] not in PLANNED),
        "config_problems": [(r["run_id"], p) for r in rows
                            for p in r.get("config_problems") or []],
    }


def h3_decision(l1: list, no_attack: list) -> str:
    if len(l1) != PLANNED[CONFIRMATORY_CELL] or len(no_attack) != PLANNED[NO_ATTACK_CELL]:
        return "INCOMPLETE"
    if any(r.get("t_gps_s") is not None or r.get("t_cc_s") is not None for r in l1):
        return "NOT APPLICABLE"
    if sum(r.get("false_alarms", 0) for r in no_attack) > 0:
        return "NOT CONFIRMED"
    k = sum(bool(r.get("passes")) for r in l1)
    n = len(l1)
    detected = sum(r.get("t_rng_s") is not None for r in l1)
    harm_over = any(r.get("harm_at_alarm_m") is not None
                    and r["harm_at_alarm_m"] > H_MAX_M for r in l1)
    if k == n:
        return "CONFIRMED"
    if 3 <= k <= 4 or (detected == n and harm_over):
        return "PARTIAL"
    return "NOT CONFIRMED"


def p_b1_2(fast: list) -> dict:
    """L10/L30: ranging must not fire before the EKF jump (- 0.5 s)."""
    per = [{"run_id": r["run_id"], "cell": r["cell"], "t_rng_s": r.get("t_rng_s"),
            "t_jump_s": r.get("t_jump_s"),
            "t_rng_minus_jump_s": (r["t_rng_s"] - r["t_jump_s"])
            if r.get("t_rng_s") is not None and r.get("t_jump_s") is not None else None}
           for r in fast]
    bad = [p for p in per if p["t_rng_minus_jump_s"] is not None
           and p["t_rng_minus_jump_s"] < -JUMP_TOL_S]
    if bad:
        res = "FALSIFIED"
    elif per and all(p["t_rng_minus_jump_s"] is not None for p in per):
        res = "HOLDS"
    else:
        res = "UNDETERMINED"
    return {"result": res, "flights": per}


def _med(v: list) -> Optional[float]:
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None


def verdict(rows: list) -> dict:
    st = status(rows)
    inc = [r for r in rows if r["included"]]
    by = lambda c: [r for r in inc if r["cell"] == c]
    l1, na = by(CONFIRMATORY_CELL), by(NO_ATTACK_CELL)
    seeds = [r.get("range_seed") for r in inc if r.get("range_seed") is not None]
    dup = sorted({s for s in seeds if seeds.count(s) > 1})
    if st["config_problems"]:
        h3 = "INVALID CONFIG"
    else:
        h3 = h3_decision(l1, na)
    k = sum(bool(r.get("passes")) for r in l1)
    attack = [r for r in inc if r["cell"] != NO_ATTACK_CELL and r["cell"] in PLANNED]
    s3 = {}
    for c in ("L1@proportionate", "L1@trust_aware"):
        rr = by(c)
        s3[c] = {"drift_itt_m": [r.get("drift_itt_m") for r in rr],
                 "median_drift_m": _med([r.get("drift_itt_m") for r in rr]),
                 "creep_mps": [r.get("creep_mps") for r in rr],
                 "vel_err_mps": [r.get("vel_err_mps") for r in rr],
                 "action_failures": sum(1 for r in rr if not r.get("action_ok"))}
    ta = by("L1@trust_aware")
    s3["trust_aware_within_h2_bound"] = (
        bool(ta) and all(r.get("drift_itt_m") is not None
                         and r["drift_itt_m"] <= H2_BOUND_M for r in ta))
    s3["creep_limit_of_h2"] = any(r.get("creep_mps") is not None
                                  and r["creep_mps"] >= CREEP_LIMIT_MPS for r in ta)
    return {
        "H3": h3,
        "status": st,
        "L1": {"n": len(l1), "passes": k, "wilson95": wilson_bounds(k, len(l1)),
               "detected": sum(r.get("t_rng_s") is not None for r in l1),
               "v1_fired": [r["run_id"] for r in l1
                            if r.get("t_gps_s") is not None or r.get("t_cc_s") is not None]},
        "false_alarms_no_attack": sum(r.get("false_alarms", 0) for r in na),
        "misattributions": {
            "total": sum(r.get("misattributions", 0) for r in attack),
            "by_victim_monitor": sum(r.get("misattr_by_victim_monitor", 0) for r in attack),
            "by_peer_monitors": sum(r.get("misattr_by_peer_monitors", 0) for r in attack)},
        "ranging_alarms_before_injection": sum(
            r.get("ranging_alarms_before_injection", 0) for r in attack),
        "P_B1_2": p_b1_2([r for c in FAST_CELLS for r in by(c)]),
        "S2_DT_L1": [{k2: r.get(k2) for k2 in ("run_id", "t_rng_peer_s", "t_rng_self_s",
                                               "harm_at_peer_alarm_m")}
                     for r in by("DT+L1@detect_only")],
        "S3": s3,
        "duplicate_range_seeds": dup,
        "constants": {"theta_m": THETA_M, "theta_ok_m": THETA_OK_M,
                      "h_max_m": H_MAX_M, "window_s": WINDOW_S},
    }


def main(argv: list) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    final = "--final" in argv
    root = args[0] if args else "runs_h3"
    dirs = sorted(os.path.join(root, d) for d in os.listdir(root) if d.startswith("run_"))
    rows = [run_row(d) for d in dirs]
    if not final:
        print(json.dumps(status(rows), indent=2, default=str))
        return 0
    with open(os.path.join(root, "h3_rows.json"), "w") as fh:
        json.dump(rows, fh, indent=1, default=str)
    print(json.dumps(verdict(rows), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
