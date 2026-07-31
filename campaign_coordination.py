"""
campaign_coordination.py — coordination integrity across the campaign,
measured as inter-node consistency (metrics/coordination.py).

Runs over exactly the trials that `campaign_report` counts as valid: the
validity gate is not re-implemented here, it is read back as the set of
run_ids the report accepted. Tables and figures cannot disagree.

Reports, per (architecture, attack):
    phase excess, m       along-track lag behind the fleet, over the
                          run's own pre-attack spread
    geometry excess, m    departure of pairwise inter-UAV distances from
                          their own pre-attack medians

Median and IQR, not mean and sd: both quantities are skewed — a single
false-positive loiter on a healthy vehicle produces a large phase lag
and would drag a mean around.

Also prints the old `coordination_loss` beside the new numbers, so the
difference between "share of UAVs off the planned polyline" and actual
inter-node consistency is visible rather than asserted.

Usage
-----
    python campaign_coordination.py runs_campaign/std_pass1 \
        runs_campaign/ci_pass{1,2,3} \
        runs_campaign/dt_pass{1,2,3,4,5,6} \
        runs_campaign/mt_pass{1,2,3,4,5,6} --csv runs_campaign/coordination.csv
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import statistics
from typing import Optional

from campaign_report import collect
from metrics.coordination import analyse_run_dir


def _quartiles(values: list) -> Optional[tuple]:
    vals = sorted(v for v in values if isinstance(v, (int, float)))
    if not vals:
        return None
    n = len(vals)
    med = statistics.median(vals)
    lo = statistics.median(vals[: n // 2]) if n > 1 else vals[0]
    hi = statistics.median(vals[(n + 1) // 2:]) if n > 1 else vals[0]
    return (med, lo, hi, n)


def _fmt(q: Optional[tuple]) -> str:
    if q is None:
        return "—"
    med, lo, hi, n = q
    return "%.1f [%.1f-%.1f] (%d)" % (med, lo, hi, n)


def run_dir_index(roots: list) -> dict:
    """run_id -> run_dir, over every run on disk in the given roots."""
    index = {}
    for root in roots:
        for run_dir in sorted(glob.glob(os.path.join(root, "run_*"))):
            path = os.path.join(run_dir, "run_summary.json")
            if not os.path.exists(path):
                continue
            try:
                with open(path) as fh:
                    summary = json.load(fh)
            except Exception:
                continue
            rid = summary.get("run_id")
            if rid:
                index[rid] = run_dir
    return index


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    cells = collect(args.roots)["cells"]
    index = run_dir_index(args.roots)

    per_cell = collections.defaultdict(
        lambda: {"phase": [], "geom": [], "old_loss": [], "missing": 0}
    )
    rows = []
    for (arch, attack), recs in sorted(cells.items()):
        bucket = per_cell[(arch, attack)]
        for (m, _mttd) in recs:
            run_dir = index.get(m.run_id)
            cm = analyse_run_dir(run_dir) if run_dir else None
            if cm is None:
                bucket["missing"] += 1
                continue
            bucket["phase"].append(cm.phase_excess_m)
            bucket["geom"].append(cm.geometry_excess_m)
            if isinstance(m.coordination_loss, (int, float)):
                bucket["old_loss"].append(m.coordination_loss)
            rows.append({
                "run_id": m.run_id,
                "architecture": arch,
                "attack": attack,
                "phase_excess_m": cm.phase_excess_m,
                "phase_peak_m": cm.phase_divergence_peak_m,
                "phase_baseline_m": cm.phase_baseline_m,
                "geometry_excess_m": cm.geometry_excess_m,
                "geometry_peak_m": cm.geometry_deviation_peak_m,
                "geometry_baseline_m": cm.geometry_baseline_m,
                "old_coordination_loss": m.coordination_loss,
                "mission_degradation_m": m.mission_degradation_m,
                "residual_mission_func": m.residual_mission_func,
            })

    archs = sorted({a for (a, _) in per_cell})
    attacks = sorted({t for (_, t) in per_cell})

    for key, title in (("phase", "PHASE DIVERGENCE excess, m  (along-track lag behind fleet)"),
                       ("geom", "GEOMETRY DEVIATION excess, m  (inter-UAV distance change)"),
                       ("old_loss", "OLD coordination_loss  (share of UAVs off the polyline)")):
        print("\n" + "=" * 92)
        print(title + "   median [IQR] (n)")
        print("=" * 92)
        print("%-32s" % "attack" + "".join("%-20s" % a for a in archs))
        for atk in attacks:
            row = "%-32s" % atk[:31]
            for arch in archs:
                row += "%-20s" % _fmt(_quartiles(per_cell[(arch, atk)][key]))
            print(row)

    missing = sum(b["missing"] for b in per_cell.values())
    if missing:
        print("\n%d trials had no usable trajectory pair (skipped)." % missing)

    print("\nRead the two new rows TOGETHER with mission_degradation:")
    print("  large geometry + small phase  = the vehicle kept flying, off course")
    print("                                  (no recovery: A/B under a landed spoof)")
    print("  small geometry + large phase  = the vehicle was stopped and held")
    print("                                  (recovery fired: C loiter) — damage")
    print("                                  contained, mission phase lost")

    if args.csv and rows:
        import csv
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print("\nwrote %s (%d trials)" % (args.csv, len(rows)))


if __name__ == "__main__":
    main()
