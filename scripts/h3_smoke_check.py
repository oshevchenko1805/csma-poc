"""H3 step 10: setup check of the technical L30 flight (runs_h3_smoke).

Pre-registered in H3_PREREGISTRATION.md, Implementation item 10. Prints
ONLY the declared setup fields and PASS/FAIL. It reads run_summary.json,
the attack phase markers (event_type == "attack") of merged.jsonl, and
the number of uav_0 rows in trajectory.jsonl. It never reads security
events, alarm times, residuals, harm, the GPS series or trajectory
coordinates.

    python3 scripts/h3_smoke_check.py runs_h3_smoke

Exit code 0 iff every run in the root passes.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

LEVEL_RATE_L30 = 0.02
RATE_REL_TOL = 0.01
WINDOW_S = 120.0
MIN_EVALUATED_SHARE = 0.95
N_MONITORS = 3
VICTIM = "uav_0"


def inject_end_marker(merged_path: str) -> Optional[float]:
    """Timestamp of the runner's inject_end marker; attack events only."""
    if not os.path.exists(merged_path):
        return None
    with open(merged_path) as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("event_type") != "attack":
                continue
            if e.get("phase") == "inject_end":
                return float(e["timestamp"])
    return None


def victim_rows(traj_path: str, uav: str = VICTIM) -> int:
    """Number of truth rows of `uav` (row count only, no coordinates)."""
    if not os.path.exists(traj_path):
        return 0
    n = 0
    with open(traj_path) as fh:
        for line in fh:
            try:
                if json.loads(line).get("uav_id") == uav:
                    n += 1
            except ValueError:
                continue
    return n


def check(summary: dict, inject_end: Optional[float], uav0_rows: int) -> list:
    """[(field, value, ok)] for the declared setup fields."""
    out = []

    def add(name, value, ok):
        out.append((name, value, bool(ok)))

    add("error", summary.get("error"), summary.get("error") is None)
    rs = summary.get("range_source")
    seed = rs.get("seed") if isinstance(rs, dict) else None
    add("range_source.seed", seed, seed is not None)

    ev = ((summary.get("attack_evidence") or {}).get("gps_spoofing")) or {}
    t0 = ev.get("t_target_set")
    add("t_target_set", t0, t0 is not None)
    add("rate_confirmed", ev.get("rate_confirmed"), ev.get("rate_confirmed") is True)
    rate = ev.get("spoof_rate")
    add("spoof_rate", rate, rate is not None
        and abs(float(rate) - LEVEL_RATE_L30) <= RATE_REL_TOL * LEVEL_RATE_L30)

    ts = summary.get("trajectory_stats") or {}
    add("trajectory_stats.samples_written", ts.get("samples_written"),
        (ts.get("samples_written") or 0) > 0)
    add("trajectory_stats.on_sample_errors", ts.get("on_sample_errors"),
        ts.get("on_sample_errors") == 0)
    add(f"{VICTIM}_truth_rows", uav0_rows, uav0_rows > 0)

    ms = summary.get("monitor_stats") or []
    add("monitors", len(ms), len(ms) == N_MONITORS)
    for i, m in enumerate(ms):
        ev_n = m.get("ranging_evaluated")
        own = m.get("ranging_no_own_position")
        rng = m.get("ranging_no_range")
        tot = (ev_n or 0) + (own or 0) + (rng or 0)
        share = (ev_n / tot) if (ev_n is not None and tot > 0) else None
        add(f"monitor[{i}].ranging (evaluated/no_own/no_range)",
            (ev_n, own, rng), ev_n is not None and ev_n > 0)
        add(f"monitor[{i}].evaluated_share",
            None if share is None else round(share, 4),
            share is not None and share >= MIN_EVALUATED_SHARE)
        add(f"monitor[{i}].handler_errors", m.get("handler_errors"),
            m.get("handler_errors") == 0)

    short = (max(0.0, t0 + WINDOW_S - inject_end)
             if (t0 is not None and inject_end is not None) else None)
    add("window_short_s", None if short is None else round(short, 3), short == 0.0)
    return out


def check_run(run_dir: str) -> list:
    with open(os.path.join(run_dir, "run_summary.json")) as fh:
        summary = json.load(fh)
    return check(summary,
                 inject_end_marker(os.path.join(run_dir, "merged.jsonl")),
                 victim_rows(os.path.join(run_dir, "trajectory.jsonl")))


def main(argv: list) -> int:
    root = argv[1] if len(argv) > 1 else "runs_h3_smoke"
    dirs = sorted(d for d in os.listdir(root) if d.startswith("run_"))
    if not dirs:
        print(f"no run_* in {root}")
        return 1
    all_ok = True
    for d in dirs:
        rows = check_run(os.path.join(root, d))
        ok = all(r[2] for r in rows)
        all_ok &= ok
        print(f"{d}: {'PASS' if ok else 'FAIL'}")
        for name, value, good in rows:
            print(f"  {'ok  ' if good else 'FAIL'} {name} = {value}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
