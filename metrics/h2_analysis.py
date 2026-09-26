"""
metrics/h2_analysis.py — pre-registered analysis of H2 (review stage 3).

Rules: H2_PREREGISTRATION.md. This module is the executable form of that
document and is committed BEFORE the first campaign run; changing a rule
after that needs a dated, reasoned entry in the document, and the
original rule stays reported next to the changed one.

Per run (row)
-------------
included          injection_confirmed is True (param read back = offset
                  at window end). False / None / crashed run -> excluded,
                  counted and reported, never silently dropped.
action_ok         a SUCCESSFUL recovery_ack for the target after injection.
drift_itt_m       max horizontal truth displacement from the target's
                  position at the first successful ack, over
                  [t_ack, t_inject + 60 s] (= post_response_drift_m of
                  metrics.physical_outcomes, but anchored on a SUCCESSFUL
                  ack). If the arm's policy requests an action and none
                  succeeded, drift_itt_m = +inf: a failed action is the
                  worst outcome (intention to treat), never an exclusion.
                  detect_only has no action -> None (not part of H2 tests).
fallback_mode     first flight mode after the response mode was entered,
                  within the window (None = held).
before_jump       response acknowledged before the EKF estimate jump
                  (stratum, secondary).

Per cell (GPS, MT): H2 accepted iff
    one-sided Mann-Whitney trust_aware < proportionate on drift_itt_m,
    Holm-adjusted over the 2 cells, p_adj < ALPHA
    AND median(trust_aware drift_itt_m) <= BOUND_M.
Overall: CONFIRMED (both cells) / PARTIAL (one) / NOT CONFIRMED (none).
DT: difference of medians with bootstrap CI only — no claim.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import sys
from typing import Optional

from metrics.derived import _attack_ts, load_events, load_trajectory
from metrics.peer_separation import load_world_xyz
from metrics.peer_separation import summarize as peer_summary
from metrics.physical_outcomes import WINDOW_S, analyse_run, max_distance_from
from metrics.stats import bootstrap_diff_median, holm, mann_whitney_u

ALPHA = 0.05
BOUND_M = 7.91          # STAGE3_PILOT.md Part A: 2.91 m + 5 m, fixed before H2
CONFIRMATORY_CELLS = ("gps_spoofing", "monitor_takeout+gps_spoofing")
DESCRIPTIVE_CELLS = ("detector_takeout+gps_spoofing",)
ARMS = ("proportionate", "trust_aware", "detect_only")
ACTING_ARMS = ("proportionate", "trust_aware")
EXPECTED_MODE = {"proportionate": "HOLD", "trust_aware": "OFFBOARD"}


# --- per run -------------------------------------------------------------


def first_ok_ack(events: list, t0: float, target: str) -> Optional[tuple]:
    """(timestamp, action) of the first successful recovery_ack >= t0."""
    hits = [
        (float(e["timestamp"]), e.get("action"))
        for e in events
        if e.get("event_type") == "recovery_ack"
        and e.get("target_uav") == target
        and e.get("success") is True
        and float(e["timestamp"]) >= t0
    ]
    return min(hits) if hits else None


def fallback_after(modes: list, expected: str, t_from: float, t_to: float) -> Optional[str]:
    """First mode other than `expected` after `expected` was in effect,
    within [t_from, t_to]. modes = [{t_wall, mode}] (changes only).
    'never:<expected>' if the expected mode was never in effect."""
    recs = sorted((m for m in modes if m.get("mode") is not None), key=lambda m: m["t_wall"])
    in_effect = None
    for m in recs:
        if m["t_wall"] <= t_from:
            in_effect = m["mode"]
    seen = in_effect == expected
    for m in recs:
        if m["t_wall"] <= t_from or m["t_wall"] > t_to:
            continue
        if m["mode"] == expected:
            seen = True
        elif seen:
            return m["mode"]
    return None if seen else f"never:{expected}"


def run_row(run_dir: str) -> dict:
    with open(os.path.join(run_dir, "run_summary.json")) as fh:
        s = json.load(fh)
    policy = (s.get("recovery_settings") or {}).get("policy")
    ev = (s.get("attack_evidence") or {}).get("gps_spoofing") or {}
    row = {
        "run_id": os.path.basename(run_dir.rstrip("/")),
        "policy": policy,
        "attack": s.get("attack_name"),
        "layer_step_m": (s.get("mission_plan") or {}).get("altitude_layer_step_m"),
        "injection_confirmed": ev.get("injection_confirmed"),
        "error": s.get("error"),
        "included": ev.get("injection_confirmed") is True and not s.get("error"),
        "action_ok": False, "action": None, "t_action_s": None,
        "drift_itt_m": None, "fallback_mode": None, "before_jump": None,
    }
    events = load_events(run_dir)
    t0 = _attack_ts(events)
    target = s.get("target_uav") or "uav_0"
    po = analyse_run(run_dir) or {}
    for k in ("t_estimate_jump_s", "nav_error_end_m", "waypoints_captured"):
        row[k] = po.get(k)
    if t0 is not None:
        row.update({f"peer_{k}": v for k, v in peer_summary(
            load_world_xyz(run_dir), target, t0).items()})
    if t0 is None or not row["included"]:
        return row
    ack = first_ok_ack(events, t0, target)
    if ack is not None:
        row.update(action_ok=True, action=ack[1], t_action_s=ack[0] - t0)
        samples = load_trajectory(run_dir).get(target) or []
        row["drift_itt_m"] = max_distance_from(samples, ack[0], t0 + WINDOW_S)
        jump = row.get("t_estimate_jump_s")
        row["before_jump"] = None if jump is None else (ack[0] - t0) < jump
        exp = EXPECTED_MODE.get(policy)
        modes = (s.get("flight_modes") or {}).get(target) or []
        if exp is not None and modes:
            row["fallback_mode"] = fallback_after(modes, exp, ack[0], t0 + WINDOW_S)
    elif policy in ACTING_ARMS:
        row["drift_itt_m"] = math.inf
    return row


# --- per cell / verdict --------------------------------------------------


def _median(v: list) -> Optional[float]:
    return statistics.median(v) if v else None


def one_sided_mw_less(x: list, y: list) -> Optional[float]:
    """P-value for 'x tends to be smaller than y' (normal approximation,
    ties + continuity corrected, via metrics.stats.mann_whitney_u).
    +inf values rank worst, as intended for failed actions."""
    big = 1e12
    xx = [big if math.isinf(v) else v for v in x]
    yy = [big if math.isinf(v) else v for v in y]
    r = mann_whitney_u(xx, yy)
    if r is None:
        return None
    u1, p2 = r
    return p2 / 2.0 if u1 < len(xx) * len(yy) / 2.0 else 1.0 - p2 / 2.0


def verdict(rows: list) -> dict:
    inc = [r for r in rows if r["included"]]
    out = {"n_runs": len(rows), "n_included": len(inc),
           "excluded": sorted(r["run_id"] for r in rows if not r["included"]),
           "cells": {}}
    raw_p = {}
    for cell in CONFIRMATORY_CELLS + DESCRIPTIVE_CELLS:
        arm = {a: [r["drift_itt_m"] for r in inc
                   if r["attack"] == cell and r["policy"] == a and r["drift_itt_m"] is not None]
               for a in ACTING_ARMS}
        t, c = arm["trust_aware"], arm["proportionate"]
        finite = lambda v: [x for x in v if not math.isinf(x)]
        info = {"n_trust": len(t), "n_prop": len(c),
                "median_trust_m": _median(t), "median_prop_m": _median(c),
                "action_failures_trust": sum(math.isinf(x) for x in t),
                "action_failures_prop": sum(math.isinf(x) for x in c),
                "diff_median_ci": bootstrap_diff_median(finite(t), finite(c))}
        if cell in CONFIRMATORY_CELLS:
            info["p_one_sided"] = one_sided_mw_less(t, c)
            if info["p_one_sided"] is not None:
                raw_p[cell] = info["p_one_sided"]
        out["cells"][cell] = info
    adj = holm(raw_p) if raw_p else {}
    accepted = 0
    for cell in CONFIRMATORY_CELLS:
        info = out["cells"][cell]
        info["p_holm"] = adj.get(cell)
        med = info["median_trust_m"]
        info["accepted"] = bool(
            info["p_holm"] is not None and info["p_holm"] < ALPHA
            and med is not None and med <= BOUND_M)
        accepted += info["accepted"]
    out["H2"] = {2: "CONFIRMED", 1: "PARTIAL", 0: "NOT CONFIRMED"}[accepted]
    return out


def main(argv: list) -> int:
    root = argv[1] if len(argv) > 1 else "runs_stage3"
    dirs = sorted(os.path.join(root, d) for d in os.listdir(root) if d.startswith("run_"))
    rows = [run_row(d) for d in dirs]
    with open(os.path.join(root, "h2_rows.json"), "w") as fh:
        json.dump(rows, fh, indent=1, default=str)
    print(json.dumps(verdict(rows), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
