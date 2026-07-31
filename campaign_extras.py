"""
campaign_extras.py — the four results that are already in the campaign
data but were never reported.

Everything here reads FINISHED runs. No simulation, no new trials.

Sections
--------
1. EXCLUSION FLOW   — launched -> errored -> no-attack -> valid, per cell.
                      Needed for Ch.4 methodology: a reviewer must be able
                      to reconstruct why 657 runs on disk became N valid
                      trials without re-running the analysis.
2. FP BACKGROUND    — false positives during the clean pre-attack window,
                      attributed BY DETECTOR and normalised by real
                      exposure time. Separates the swappable component's
                      FP rate (gps, heartbeat) from the architecture's own
                      (cross_check, exists in C only).
3. MESH COST        — the price of the mesh layer in messages and bytes.
                      Zero by construction in A/B (NoOpMesh), so the
                      contrast is exact, not estimated.
4. COORDINATION     — coordination_loss / coordination_restored per cell.
                      Table 3.13 promises this metric; it is computed for
                      every run and has never appeared in a report.

The validity gate is IMPORTED from campaign_report, never re-implemented.
Tables and figures must not be able to disagree about which trials count.

Usage
-----
    python campaign_extras.py runs_campaign/std_pass1 \
        runs_campaign/ci_pass{1,2,3} \
        runs_campaign/dt_pass{1,2,3,4,5,6} \
        runs_campaign/mt_pass{1,2,3,4,5,6}

    python campaign_extras.py --only fp  <roots...>
    python campaign_extras.py --json extras.json <roots...>

Run from the repo root.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import statistics
from typing import Optional

import metrics.derived as D
from campaign_report import _attack_ts, collect

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _summary(run_dir: str) -> Optional[dict]:
    path = os.path.join(run_dir, "run_summary.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def _telemetry_start(run_dir: str) -> Optional[float]:
    """Wall-clock of the first telemetry sample in a run.

    The event logs hold events only, so their first entry is often the
    attack itself. Using it as the start of the observation window
    collapses the FP exposure to ~0 s and silently inflates any per-time
    rate by two orders of magnitude. Telemetry is the honest anchor.
    """
    starts = []
    for path in glob.glob(os.path.join(run_dir, "telemetry_*.jsonl")):
        try:
            with open(path) as fh:
                line = fh.readline()
            if line.strip():
                starts.append(float(json.loads(line)["timestamp"]))
        except Exception:
            continue
    return min(starts) if starts else None


def _mean_sd(values: list) -> tuple:
    vals = [v for v in values if isinstance(v, (int, float))]
    if not vals:
        return (None, None, 0)
    if len(vals) == 1:
        return (vals[0], 0.0, 1)
    return (statistics.mean(vals), statistics.pstdev(vals), len(vals))


def _fmt(mean_sd: tuple, digits: int = 2) -> str:
    mean, sd, n = mean_sd
    if mean is None:
        return "—"
    if n == 1:
        return "%.*f (1)" % (digits, mean)
    return "%.*f±%.*f (%d)" % (digits, mean, digits, sd, n)


def _iter_runs(roots: list):
    for root in roots:
        for run_dir in sorted(glob.glob(os.path.join(root, "run_*"))):
            summary = _summary(run_dir)
            if summary is None:
                continue
            yield run_dir, summary


# --------------------------------------------------------------------------
# 1. exclusion flow
# --------------------------------------------------------------------------


def exclusion_flow(roots: list) -> dict:
    counts = collect(roots)["counts"]
    on_disk = collections.Counter()
    for _run_dir, summary in _iter_runs(roots):
        key = (str(summary.get("architecture") or "?"),
               str(summary.get("attack_name") or "?"))
        on_disk[key] += 1

    print("=" * 78)
    print("1. EXCLUSION FLOW  (how runs on disk became valid trials)")
    print("=" * 78)
    print("%-32s %6s %8s %11s %9s %7s"
          % ("cell", "disk", "errored", "no_summary", "no_atk", "VALID"))
    totals = collections.Counter()
    out = {}
    for key in sorted(set(on_disk) | set(counts), key=str):
        arch, atk = key
        c = counts.get(key, {})
        row = {
            "on_disk": on_disk.get(key, 0),
            "errored": c.get("errored", 0),
            "no_summary": c.get("no_summary", 0),
            "no_atk": c.get("no_atk", 0),
            "valid": c.get("valid", 0),
        }
        out["%s|%s" % (arch, atk)] = row
        for k, v in row.items():
            totals[k] += v
        print("%-32s %6d %8d %11d %9d %7d"
              % ("%s  %s" % (arch, atk[:26]), row["on_disk"], row["errored"],
                 row["no_summary"], row["no_atk"], row["valid"]))
    print("-" * 78)
    print("%-32s %6d %8d %11d %9d %7d"
          % ("TOTAL", totals["on_disk"], totals["errored"],
             totals["no_summary"], totals["no_atk"], totals["valid"]))
    print("\nno_atk = GPS-family trial where the spoof did not land "
          "(belief/trajectory gate).\nA trial where the attack never "
          "happened is not a missed detection.")
    out["TOTAL"] = dict(totals)
    return out


# --------------------------------------------------------------------------
# 2. false-positive background
# --------------------------------------------------------------------------


def fp_background(roots: list) -> dict:
    """FP during normal operation, attributed by detector.

    Exposure window:
      * attack runs   — telemetry start .. injection instant (clean flight)
      * baseline runs — the whole run (there is no attack to bound it)
    Baseline therefore contributes a slightly more generous window; it is a
    minority of the corpus and the asymmetry is stated rather than hidden.
    """
    per = collections.defaultdict(
        lambda: {"runs": 0, "exposure_s": 0.0, "fp_runs": 0,
                 "by_detector": collections.Counter(), "bursts": []}
    )
    for run_dir, summary in _iter_runs(roots):
        if summary.get("error"):
            continue
        arch = str(summary.get("architecture") or "?")
        rec = per[arch]
        rec["runs"] += 1

        events = D.load_events(run_dir)
        t0 = _attack_ts(events)
        t_start = _telemetry_start(run_dir)

        if t0 is not None and t_start is not None and t0 > t_start:
            rec["exposure_s"] += t0 - t_start
        elif t0 is None:
            rec["exposure_s"] += float(summary.get("duration_sec") or 0.0)

        pre = [e for e in events
               if e.get("event_type") == "security"
               and (t0 is None or float(e["timestamp"]) < t0)]
        if pre:
            rec["fp_runs"] += 1
            rec["bursts"].append(len(pre))
        for e in pre:
            rec["by_detector"][e.get("detector") or "?"] += 1

    print("\n" + "=" * 78)
    print("2. FALSE-POSITIVE BACKGROUND  (clean-mode operation)")
    print("=" * 78)
    print("%-6s %6s %10s %8s %10s %12s"
          % ("arch", "runs", "clean_min", "FP_ev", "FP/min", "runs_with_FP"))
    out = {}
    for arch in sorted(per):
        rec = per[arch]
        mins = rec["exposure_s"] / 60.0
        total = sum(rec["by_detector"].values())
        rate = total / mins if mins else 0.0
        share = 100.0 * rec["fp_runs"] / rec["runs"] if rec["runs"] else 0.0
        print("%-6s %6d %10.1f %8d %10.3f %12s"
              % (arch, rec["runs"], mins, total, rate,
                 "%d (%.1f%%)" % (rec["fp_runs"], share)))
        out[arch] = {
            "runs": rec["runs"],
            "clean_min": round(mins, 1),
            "fp_events": total,
            "fp_per_min": round(rate, 4),
            "fp_runs": rec["fp_runs"],
            "by_detector": dict(rec["by_detector"]),
            "bursts": sorted(rec["bursts"], reverse=True),
        }

    print("\nby detector (events / rate per min):")
    for arch in sorted(per):
        rec = per[arch]
        mins = rec["exposure_s"] / 60.0
        parts = ["%s=%d (%.3f/min)" % (d, n, n / mins if mins else 0.0)
                 for d, n in sorted(rec["by_detector"].items())]
        print("  %s: %s" % (arch, ", ".join(parts) if parts else "none"))

    print("\nevents per FP-run (burst size — how far one false alarm spreads):")
    for arch in sorted(per):
        b = out[arch]["bursts"]
        print("  %s: %s" % (arch, b if b else "—"))
    print("\nRead: gps/heartbeat FP characterise the swappable detector and "
          "appear in every\narchitecture. cross_check exists only in C — it "
          "is the mesh layer's own FP cost.")
    return out


# --------------------------------------------------------------------------
# 3. mesh cost
# --------------------------------------------------------------------------


def mesh_cost(roots: list) -> dict:
    per = collections.defaultdict(
        lambda: {"runs": 0, "pub_msgs": [], "pub_bytes": [], "del_msgs": [],
                 "del_bytes": [], "drop_msgs": [], "dur": [],
                 "topics": collections.Counter()}
    )
    for _run_dir, summary in _iter_runs(roots):
        if summary.get("error"):
            continue
        arch = str(summary.get("architecture") or "?")
        cost = summary.get("mesh_cost") or {}
        fleet = cost.get("fleet_total") or {}
        rec = per[arch]
        rec["runs"] += 1
        rec["dur"].append(float(summary.get("duration_sec") or 0.0))
        for side, mkey, bkey in (("published", "pub_msgs", "pub_bytes"),
                                 ("delivered", "del_msgs", "del_bytes"),
                                 ("dropped", "drop_msgs", None)):
            block = (fleet.get(side) or {})
            rec[mkey].append((block.get("total") or {}).get("msgs", 0))
            if bkey:
                rec[bkey].append((block.get("total") or {}).get("bytes", 0))
        for topic, tv in ((fleet.get("published") or {}).get("per_topic") or {}).items():
            rec["topics"][topic] += tv.get("msgs", 0)

    print("\n" + "=" * 78)
    print("3. MESH COST  (price of the architecture, per run)")
    print("=" * 78)
    print("%-6s %6s %16s %16s %16s %10s"
          % ("arch", "runs", "published msgs", "published KB",
             "delivered msgs", "KB/s"))
    out = {}
    for arch in sorted(per):
        rec = per[arch]
        pm = _mean_sd(rec["pub_msgs"])
        pb = _mean_sd([b / 1024.0 for b in rec["pub_bytes"]])
        dm = _mean_sd(rec["del_msgs"])
        dur = _mean_sd(rec["dur"])
        kbs = (pb[0] / dur[0]) if (pb[0] and dur[0]) else 0.0
        print("%-6s %6d %16s %16s %16s %10.3f"
              % (arch, rec["runs"], _fmt(pm, 0), _fmt(pb, 1), _fmt(dm, 0), kbs))
        out[arch] = {
            "runs": rec["runs"],
            "published_msgs_mean": pm[0],
            "published_kb_mean": pb[0],
            "delivered_msgs_mean": dm[0],
            "dropped_msgs_mean": _mean_sd(rec["drop_msgs"])[0],
            "kb_per_s": round(kbs, 4),
            "topics_total": dict(rec["topics"]),
        }
    print("\npublished messages by topic (whole corpus):")
    for arch in sorted(per):
        t = per[arch]["topics"]
        print("  %s: %s" % (arch, dict(t) if t else "none (NoOpMesh)"))
    print("\nA and B are exactly zero by construction (NoOpMesh), so the "
          "overhead of the\nmesh layer is measured, not estimated.")
    return out


# --------------------------------------------------------------------------
# 4. coordination integrity
# --------------------------------------------------------------------------


def coordination(roots: list) -> dict:
    cells = collect(roots)["cells"]
    archs = sorted({a for (a, _) in cells})
    attacks = sorted({t for (_, t) in cells})

    print("\n" + "=" * 78)
    print("4. COORDINATION INTEGRITY  (Table 3.13, never reported)")
    print("=" * 78)
    print("Values are quantised to k/3 — three UAVs, so the metric resolves")
    print("only {0, 1/3, 2/3, 1}. Report as the share of desynchronised "
          "nodes.\n")
    out = {}
    for field, title in (("coordination_loss", "Coordination loss"),
                         ("coordination_restored", "Coordination restored")):
        print("%s:" % title)
        print("%-32s" % "attack" + "".join("%-22s" % a for a in archs))
        for atk in attacks:
            row = "%-32s" % atk[:31]
            for arch in archs:
                recs = cells.get((arch, atk), [])
                vals = [getattr(m, field) for (m, _) in recs]
                row += "%-22s" % _fmt(_mean_sd(vals), 2)
                out["%s|%s|%s" % (field, arch, atk)] = _mean_sd(vals)[0]
            print(row)
        print()

    print("distribution of coordination_loss (value: count):")
    for atk in attacks:
        for arch in archs:
            recs = cells.get((arch, atk), [])
            if not recs:
                continue
            dist = collections.Counter(
                round(m.coordination_loss, 2)
                for (m, _) in recs
                if isinstance(m.coordination_loss, (int, float))
            )
            print("  %-32s %s  %s" % (atk[:31], arch, dict(sorted(dist.items()))))
    return out


# --------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+", help="campaign pass directories")
    ap.add_argument("--only", default="all",
                    choices=["all", "flow", "fp", "mesh", "coord"])
    ap.add_argument("--json", default=None, help="dump results to JSON")
    args = ap.parse_args()

    result = {}
    if args.only in ("all", "flow"):
        result["exclusion_flow"] = exclusion_flow(args.roots)
    if args.only in ("all", "fp"):
        result["fp_background"] = fp_background(args.roots)
    if args.only in ("all", "mesh"):
        result["mesh_cost"] = mesh_cost(args.roots)
    if args.only in ("all", "coord"):
        result["coordination"] = coordination(args.roots)

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(result, fh, indent=2, default=str)
        print("\nwrote %s" % args.json)


if __name__ == "__main__":
    main()
