"""
campaign_report.py — belief-gated aggregation of the full campaign.

Collects every run across the campaign pass directories, applies the
belief-divergence validity gate to the GPS-family cells, and aggregates
per (architecture, attack): detection rate with a Wilson 95% CI, MTTD,
and the Table 3.13 derived metrics (via metrics.derived) — over VALID
trials only.

Why the gate is mandatory (handoff critical fact #1)
----------------------------------------------------
`SIM_GPS_OFF_N` does not always take effect in a batch. A trial where
the spoof did not land is "no attack", NOT "attack missed". Counting it
as a false negative fabricates a false collapse — most dangerously in
detector_takeout+gps, where C's whole result depends on the spoof
landing so the neighbours' cross_check has something to catch. So a
GPS-family trial counts only if
    belief_divergence.uavs.<target>.peak_horiz_m > BELIEF_GATE_M.
Non-GPS attacks (comm_disruption) and baseline (none) are never gated —
belief_divergence is not interpretable for them (verified: comm's single
post-attack sample is a reconnection transient, not drift).

Usage
-----
    python campaign_report.py runs_campaign/std_pass1 runs_campaign/std_pass2 ...
    python campaign_report.py runs_campaign/*_pass*      # shell-expanded
    python campaign_report.py --csv out.csv runs_campaign/std_pass1 ...

Reads metrics.derived from the repo, so run it from the repo root (or
with the repo on PYTHONPATH).
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import statistics
from collections import defaultdict
from typing import Optional

import metrics.derived as D

BELIEF_GATE_M = 10.0
"""peak horizontal true-vs-believed divergence above which a GPS spoof is
deemed to have landed. Settled ~50 m; a no-op run sits near 1 m."""


def is_gps_family(attack: str) -> bool:
    return "gps" in (attack or "").lower()


def belief_peak(summary: dict) -> Optional[float]:
    target = summary.get("target_uav") or "uav_0"
    node = (
        (summary.get("belief_divergence") or {})
        .get("uavs", {})
        .get(target, {})
    )
    if not isinstance(node, dict):
        return None
    return node.get("peak_horiz_m")


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _attack_ts(events: list) -> Optional[float]:
    for e in events:
        if e.get("event_type") == "attack" and e.get("phase") == "inject_start":
            return float(e["timestamp"])
    for e in events:
        if e.get("event_type") == "attack":
            return float(e["timestamp"])
    return None


def mttd(run_dir: str) -> Optional[float]:
    events = D.load_events(run_dir)
    t0 = _attack_ts(events)
    if t0 is None:
        return None
    for e in events:
        if e.get("event_type") == "security":
            return float(e["timestamp"]) - t0
    return None


def collect(roots: list) -> dict:
    """(arch, attack) -> list of per-run records over VALID trials."""
    cells = defaultdict(list)
    counts = defaultdict(lambda: {"valid": 0, "no_atk": 0, "no_summary": 0})
    for root in roots:
        for run_dir in sorted(glob.glob(os.path.join(root, "run_*"))):
            spath = os.path.join(run_dir, "run_summary.json")
            if not os.path.exists(spath):
                continue
            with open(spath) as fh:
                summary = json.load(fh)
            arch = str(summary.get("architecture") or "?")
            attack = str(summary.get("attack_name") or "?")
            key = (arch, attack)

            # Belief gate — GPS family only.
            if is_gps_family(attack):
                peak = belief_peak(summary)
                if peak is None or peak <= BELIEF_GATE_M:
                    counts[key]["no_atk"] += 1
                    continue

            m = D.analyse_run(run_dir)
            if m is None:
                counts[key]["no_summary"] += 1
                continue
            counts[key]["valid"] += 1
            cells[key].append((m, mttd(run_dir)))
    return {"cells": cells, "counts": counts}


def _agg_float(values: list) -> Optional[tuple]:
    vals = [v for v in values if isinstance(v, (int, float))]
    if not vals:
        return None
    if len(vals) == 1:
        return (vals[0], 0.0, 1)
    return (statistics.mean(vals), statistics.pstdev(vals), len(vals))


def _fmt_agg(agg: Optional[tuple]) -> str:
    if agg is None:
        return "—"
    mean, sd, n = agg
    return "%.2f±%.2f (%d)" % (mean, sd, n) if n > 1 else "%.2f (1)" % mean


def report(roots: list, csv_path: Optional[str] = None) -> None:
    data = collect(roots)
    cells = data["cells"]
    counts = data["counts"]

    archs = sorted({a for (a, _) in cells} | {a for (a, _) in counts})
    attacks = sorted({t for (_, t) in cells} | {t for (_, t) in counts})

    print("=" * 72)
    print("DETECTION RATE (valid trials, Wilson 95%% CI)   gate=%.0fm" % BELIEF_GATE_M)
    print("=" * 72)
    for atk in attacks:
        print("\n%s" % atk)
        for arch in archs:
            recs = cells.get((arch, atk), [])
            c = counts.get((arch, atk), {})
            n = len(recs)
            if n == 0:
                extra = ""
                if c.get("no_atk"):
                    extra = "  (%d excluded: spoof did not land)" % c["no_atk"]
                print("  %s: —%s" % (arch, extra))
                continue
            k = sum(1 for (m, _) in recs if m.detected)
            lo, hi = wilson_ci(k, n)
            noatk = c.get("no_atk", 0)
            tail = "  [%d no_atk gated out]" % noatk if noatk else ""
            print("  %s: %d/%d = %.2f  CI[%.2f, %.2f]%s"
                  % (arch, k, n, k / n if n else 0, lo, hi, tail))

    # Derived metric summaries per cell.
    metric_fields = [
        ("mttd_s", "MTTD, s"),
        ("mission_degradation_m", "Mission degradation, m"),
        ("stabilisation_level_m", "Stabilisation level, m"),
        ("residual_mission_func", "Residual mission function"),
        ("coordination_loss", "Coordination loss"),
        ("total_response_time_s", "Total response time, s"),
    ]
    for field, title in metric_fields:
        print("\n" + "=" * 72)
        print(title + "  (valid trials)")
        print("=" * 72)
        header = "%-30s" % "Attack" + "".join("%-20s" % a for a in archs)
        print(header)
        for atk in attacks:
            row = "%-30s" % atk[:30]
            for arch in archs:
                recs = cells.get((arch, atk), [])
                if field == "mttd_s":
                    vals = [t for (_, t) in recs if t is not None]
                else:
                    vals = [getattr(m, field) for (m, _) in recs]
                row += "%-20s" % _fmt_agg(_agg_float(vals))
            print(row)

    if csv_path:
        import csv

        rows = []
        for (arch, atk), recs in sorted(cells.items()):
            for (m, t) in recs:
                d = dict(m.__dict__)
                d["mttd_s"] = t
                rows.append(d)
        if rows:
            with open(csv_path, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            print("\nwrote %s (%d valid trials)" % (csv_path, len(rows)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+", help="campaign pass directories")
    ap.add_argument("--csv", default=None, help="write per-trial CSV")
    args = ap.parse_args()
    report(args.roots, csv_path=args.csv)


if __name__ == "__main__":
    main()
