"""POST-HOC, exploratory (written 2026-09-28, AFTER the H3 results).

Not part of the pre-registered H3 decision. Question: does the S3
trust_aware drift (9.6 m over [t_ack, t0 + 120 s], above the H2 bound
7.91 m) come from the longer window or from the action itself? The H2
bound was calibrated for a 60 s window from injection; H3 uses 120 s.

For every S3 flight: drift_itt_m (H2 definition: max horizontal truth
displacement from the position at the first successful ack) evaluated
up to t0 + 30 / 60 / 90 / 120 s, t0 = t_target_set.

    python3 scripts/h3_posthoc_s3_windows.py runs_h3
"""

from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from metrics import h3_analysis as H  # noqa: E402
from metrics.derived import load_events, load_trajectory  # noqa: E402
from metrics.h2_analysis import first_ok_ack  # noqa: E402
from metrics.physical_outcomes import max_distance_from  # noqa: E402

WINDOWS_S = (30.0, 60.0, 90.0, 120.0)
S3_POLICIES = ("proportionate", "trust_aware")


def drift_by_window(track: list, t_ack: float, t0: float,
                    windows=WINDOWS_S) -> dict:
    return {w: max_distance_from(track, t_ack, t0 + w) for w in windows}


def s3_rows(root: str) -> list:
    rows = []
    for d in sorted(glob.glob(os.path.join(root, "run_*"))):
        with open(os.path.join(d, "run_summary.json")) as fh:
            s = json.load(fh)
        policy = (s.get("recovery_settings") or {}).get("policy")
        if (policy not in S3_POLICIES or H.cell_of(s) != f"L1@{policy}"):
            continue
        t0 = H.gps_evidence(s).get("t_target_set")
        ack = first_ok_ack(load_events(d), t0, H.VICTIM)
        track = load_trajectory(d).get(H.VICTIM) or []
        rows.append({
            "run_id": os.path.basename(d), "policy": policy,
            "t_ack_s": None if ack is None else ack[0] - t0,
            "drift_m": None if ack is None else drift_by_window(track, ack[0], t0),
        })
    return rows


def main(argv: list) -> int:
    root = argv[1] if len(argv) > 1 else "runs_h3"
    print(f"POST-HOC (exploratory). H2 bound {H.H2_BOUND_M} m, H2 window 60 s.")
    for r in s3_rows(root):
        d = r["drift_m"] or {}
        cols = "  ".join(f"@{int(w)}s {d[w]:.2f}" for w in WINDOWS_S if w in d)
        print(f"{r['policy']:<14} ack {r['t_ack_s']:.2f} s  {cols}  {r['run_id'][-12:]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
