#!/usr/bin/env python3
"""
analyze_loss_sweep.py — aggregate a mesh-loss sweep into the headline
statistic for Chapter 5: mesh-mediated detection rate vs mesh loss, with
Wilson 95% confidence intervals, plus MTTD and realized-loss summaries.

Scenario assumption (C x detector_takeout+gps_spoofing)
-------------------------------------------------------
Local detectors on the target are silenced by detector_takeout, so the
ONLY way the target's GPS spoof is caught is a neighbour's cross_check
over the mesh. "Detected" for a trial therefore means: at least one
`cross_check` security event naming the target UAV was emitted by any
monitor. Under mesh loss this becomes probabilistic -> a rate with CI.

Reads every runs_sweep/<root>/run_*/run_summary.json, keys each trial by
its CONFIGURED loss (run_summary.mesh_settings.loss_prob — provenance is
in the data, not the folder name), and reports per level:
  n, detected, detection_rate [Wilson 95% CI], mean realized loss,
  MTTD mean±sd (detected trials only), error count.

Usage
-----
    python scripts/analyze_loss_sweep.py --root ./runs_sweep
    python scripts/analyze_loss_sweep.py --root ./runs_sweep \
        --target-uav uav_0 --plot ./runs_sweep/detection_vs_loss.png \
        --csv ./runs_sweep/detection_vs_loss.csv

matplotlib is only needed with --plot; the table and CSV work without it.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
from collections import defaultdict
from typing import Any, Optional


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval for a binomial proportion.

    Returns (point, low, high). Correct at the edges (0/n, n/n) where the
    normal approximation gives degenerate zero-width intervals — which is
    exactly where a loss sweep lives (full detection at loss 0, collapse
    at high loss).
    """
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / denom
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def _load_json(path: str) -> Optional[dict[str, Any]]:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _attack_onset(run_dir: str) -> Optional[float]:
    """Timestamp of the first attack inject_start in a run."""
    ap = os.path.join(run_dir, "attack.jsonl")
    if not os.path.exists(ap):
        return None
    for line in open(ap):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("phase") == "inject_start":
            return e.get("timestamp")
    return None


def _cross_check_hits(run_dir: str, target_uav: str) -> list[float]:
    """Timestamps of cross_check security events naming the target."""
    hits: list[float] = []
    for mf in glob.glob(os.path.join(run_dir, "monitor_*.jsonl")):
        for line in open(mf):
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                e.get("event_type") == "security"
                and e.get("detector") == "cross_check"
                and e.get("target_uav") == target_uav
            ):
                ts = e.get("timestamp")
                if ts is not None:
                    hits.append(ts)
    return sorted(hits)


def _realized_loss(summary: dict[str, Any]) -> Optional[float]:
    try:
        ft = summary["mesh_cost"]["fleet_total"]
        deliv = ft["delivered"]["total"]["msgs"]
        drop = ft["dropped"]["total"]["msgs"]
        tot = deliv + drop
        return drop / tot if tot else None
    except (KeyError, TypeError):
        return None


class Level:
    def __init__(self, loss: float):
        self.loss = loss
        self.n = 0
        self.detected = 0
        self.errors = 0
        self.mttds: list[float] = []
        self.realized: list[float] = []


def analyze(root: str, target_uav: str) -> list[Level]:
    levels: dict[float, Level] = {}
    summaries = sorted(glob.glob(os.path.join(root, "*", "run_*", "run_summary.json")))
    for sp in summaries:
        s = _load_json(sp)
        if s is None:
            continue
        ms = s.get("mesh_settings") or {}
        loss = ms.get("loss_prob")
        if loss is None:
            continue  # cannot key a trial without provenance
        loss = round(float(loss), 4)
        lvl = levels.setdefault(loss, Level(loss))
        lvl.n += 1
        if s.get("error"):
            lvl.errors += 1
        rl = _realized_loss(s)
        if rl is not None:
            lvl.realized.append(rl)
        run_dir = os.path.dirname(sp)
        hits = _cross_check_hits(run_dir, target_uav)
        if hits:
            lvl.detected += 1
            t0 = _attack_onset(run_dir)
            if t0 is not None:
                lvl.mttds.append(hits[0] - t0)
    return [levels[k] for k in sorted(levels)]


def _mean_sd(xs: list[float]) -> tuple[Optional[float], Optional[float]]:
    if not xs:
        return (None, None)
    m = sum(xs) / len(xs)
    if len(xs) < 2:
        return (m, 0.0)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return (m, math.sqrt(var))


def _fmt(x: Optional[float], nd: int = 3) -> str:
    return "-" if x is None else f"{x:.{nd}f}"


def print_table(levels: list[Level]) -> None:
    hdr = (
        f"{'loss':>5} {'n':>4} {'det':>4} {'rate':>6} "
        f"{'95% CI (Wilson)':>18} {'realized':>9} {'MTTD mean±sd':>16} {'err':>4}"
    )
    print(hdr)
    print("-" * len(hdr))
    for lv in levels:
        p, lo, hi = wilson_ci(lv.detected, lv.n)
        rl_m, _ = _mean_sd(lv.realized)
        mt_m, mt_sd = _mean_sd(lv.mttds)
        ci = f"[{_fmt(lo,2)}, {_fmt(hi,2)}]"
        mttd = "-" if mt_m is None else f"{mt_m:.2f}±{mt_sd:.2f}s"
        print(
            f"{lv.loss:>5.2f} {lv.n:>4} {lv.detected:>4} {_fmt(p,3):>6} "
            f"{ci:>18} {_fmt(rl_m,3):>9} {mttd:>16} {lv.errors:>4}"
        )


def write_csv(levels: list[Level], path: str) -> None:
    import csv

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["loss_prob", "n", "detected", "detection_rate",
             "ci_low", "ci_high", "realized_loss_mean",
             "mttd_mean_s", "mttd_sd_s", "errors"]
        )
        for lv in levels:
            p, lo, hi = wilson_ci(lv.detected, lv.n)
            rl_m, _ = _mean_sd(lv.realized)
            mt_m, mt_sd = _mean_sd(lv.mttds)
            w.writerow([
                lv.loss, lv.n, lv.detected, f"{p:.4f}",
                f"{lo:.4f}", f"{hi:.4f}",
                _fmt(rl_m, 4), _fmt(mt_m, 3), _fmt(mt_sd, 3), lv.errors,
            ])
    print(f"wrote {path}")


def make_plot(levels: list[Level], path: str, target_uav: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [lv.loss for lv in levels]
    ps, los, his = [], [], []
    for lv in levels:
        p, lo, hi = wilson_ci(lv.detected, lv.n)
        ps.append(p)
        los.append(p - lo)
        his.append(hi - p)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.errorbar(
        xs, ps, yerr=[los, his], fmt="o-", capsize=4, color="#1f4e79",
        ecolor="#1f4e79", markerfacecolor="white", linewidth=1.5,
    )
    ax.set_xlabel("mesh loss probability")
    ax.set_ylabel(f"mesh detection rate ({target_uav})")
    ax.set_ylim(-0.02, 1.02)
    ax.set_title(
        "CSMA mesh-mediated detection under channel loss\n"
        "C × detector_takeout+gps_spoofing (local detection silenced)"
    )
    ax.grid(True, alpha=0.3)
    for lv, p in zip(levels, ps):
        ax.annotate(f"{lv.detected}/{lv.n}", (lv.loss, p),
                    textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=8, color="#555")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print(f"wrote {path}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="./runs_sweep",
                    help="sweep root containing per-level batch dirs (default: ./runs_sweep)")
    ap.add_argument("--target-uav", default="uav_0")
    ap.add_argument("--plot", default=None, help="write a PNG here (needs matplotlib)")
    ap.add_argument("--csv", default=None, help="write a CSV here")
    args = ap.parse_args(argv)

    levels = analyze(args.root, args.target_uav)
    if not levels:
        print(f"no keyed trials found under {args.root} "
              f"(need run_summary.json with mesh_settings.loss_prob)")
        return 1

    print_table(levels)
    total = sum(lv.n for lv in levels)
    print(f"\ntotal trials: {total} across {len(levels)} loss levels")

    if args.csv:
        write_csv(levels, args.csv)
    if args.plot:
        make_plot(levels, args.plot, args.target_uav)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
