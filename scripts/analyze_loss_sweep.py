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
        self.n = 0                 # valid trials: no run error AND spoof landed
        self.detected = 0          # >=1 cross_check AFTER attack onset
        self.fp_preattack = 0      # >=1 cross_check BEFORE attack onset (FP)
        self.no_attack = 0         # spoof did not take effect (divergence < gate)
        self.errors = 0
        self.mttds: list[float] = []   # first POST-attack cross_check offset
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
        # A failed trial (e.g. TimeoutError — PX4 never flew) is not data:
        # exclude it from n / detection / MTTD, count it separately. This
        # also filters stale failed run dirs left on disk after a resume
        # (run_batch retries into NEW dirs and does not delete the old ones).
        if s.get("error"):
            lvl.errors += 1
            continue
        # Validity gate: the GPS spoof must have actually taken effect.
        # A trial where the target's believed position never diverged is
        # "no attack", not "not detected" — exclude it from the rate.
        peak = _target_spoof_peak_m(s, target_uav)
        if peak is None or peak < SPOOF_MIN_DIVERGENCE_M:
            lvl.no_attack += 1
            continue
        lvl.n += 1
        rl = _realized_loss(s)
        if rl is not None:
            lvl.realized.append(rl)
        run_dir = os.path.dirname(sp)
        t0 = _attack_onset(run_dir)
        hits = _cross_check_hits(run_dir, target_uav)
        if t0 is None:
            continue  # cannot classify pre/post without attack onset
        offsets = [h - t0 for h in hits]
        post = [o for o in offsets if o >= 0.0]
        pre = [o for o in offsets if o < 0.0]
        if post:
            lvl.detected += 1
            lvl.mttds.append(post[0])   # first cross_check after the attack
        if pre:
            lvl.fp_preattack += 1        # spurious cross_check before the attack
    return [levels[k] for k in sorted(levels)]


def _mean_sd(xs: list[float]) -> tuple[Optional[float], Optional[float]]:
    if not xs:
        return (None, None)
    m = sum(xs) / len(xs)
    if len(xs) < 2:
        return (m, 0.0)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return (m, math.sqrt(var))


def _median(xs: list[float]) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


# MTTD below this (seconds after attack onset) is too fast to be a real
# multi-round mesh consensus — flagged as a likely spurious/early cross_check.
EARLY_MTTD_S = 2.0

# A trial only counts if the GPS spoof actually took effect: uav_0's
# believed-vs-true horizontal divergence must exceed this (metres). The
# spoof targets a 50 m offset; a landed spoof peaks ~50 m, a no-op stays
# ~1 m (sensor noise). Trials below this are "attack did not happen" — a
# validity failure, NOT "not detected" — and are excluded from the
# detection denominator (counted separately as no_attack). This gate is
# what stops a flaky attack from masquerading as a detection result.
SPOOF_MIN_DIVERGENCE_M = 10.0


def _target_spoof_peak_m(summary: dict[str, Any], target_uav: str) -> Optional[float]:
    """Peak believed-vs-true horizontal divergence of the target (metres)."""
    bd = summary.get("belief_divergence") or {}
    node = (bd.get("uavs") or {}).get(target_uav) or {}
    return node.get("peak_horiz_m")


def _fmt(x: Optional[float], nd: int = 3) -> str:
    return "-" if x is None else f"{x:.{nd}f}"


def print_table(levels: list[Level]) -> None:
    hdr = (
        f"{'loss':>5} {'n':>4} {'det':>4} {'rate':>6} "
        f"{'95% CI (Wilson)':>18} {'realized':>9} {'no_atk':>7} {'fp_pre':>7} {'err':>4}"
    )
    print(hdr)
    print("-" * len(hdr))
    print("(n = valid trials: run ok AND spoof landed; no_atk = spoof did not take effect, excluded)")
    for lv in levels:
        p, lo, hi = wilson_ci(lv.detected, lv.n)
        rl_m, _ = _mean_sd(lv.realized)
        ci = f"[{_fmt(lo,2)}, {_fmt(hi,2)}]"
        print(
            f"{lv.loss:>5.2f} {lv.n:>4} {lv.detected:>4} {_fmt(p,3):>6} "
            f"{ci:>18} {_fmt(rl_m,3):>9} {lv.no_attack:>7} {lv.fp_preattack:>7} {lv.errors:>4}"
        )

    print("\nMTTD to first cross_check (detected trials only), robust stats:")
    mh = (
        f"{'loss':>5} {'ndet':>5} {'median':>8} {'min':>7} {'max':>8} "
        f"{'mean±sd':>15} {'early<2s':>8}"
    )
    print(mh)
    print("-" * len(mh))
    for lv in levels:
        md = _median(lv.mttds)
        mn = min(lv.mttds) if lv.mttds else None
        mx = max(lv.mttds) if lv.mttds else None
        m, sd = _mean_sd(lv.mttds)
        n_early = sum(1 for x in lv.mttds if x < EARLY_MTTD_S)
        mean_sd = "-" if m is None else f"{m:.2f}±{sd:.2f}s"
        print(
            f"{lv.loss:>5.2f} {len(lv.mttds):>5} {_fmt(md,2):>8} "
            f"{_fmt(mn,2):>7} {_fmt(mx,2):>8} {mean_sd:>15} {n_early:>8}"
        )


def write_csv(levels: list[Level], path: str) -> None:
    import csv

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["loss_prob", "n", "detected", "detection_rate",
             "ci_low", "ci_high", "realized_loss_mean",
             "mttd_median_s", "mttd_min_s", "mttd_max_s",
             "mttd_mean_s", "mttd_sd_s", "mttd_early_lt2s",
             "fp_preattack", "no_attack", "errors"]
        )
        for lv in levels:
            p, lo, hi = wilson_ci(lv.detected, lv.n)
            rl_m, _ = _mean_sd(lv.realized)
            mt_m, mt_sd = _mean_sd(lv.mttds)
            md = _median(lv.mttds)
            mn = min(lv.mttds) if lv.mttds else None
            mx = max(lv.mttds) if lv.mttds else None
            n_early = sum(1 for x in lv.mttds if x < EARLY_MTTD_S)
            w.writerow([
                lv.loss, lv.n, lv.detected, f"{p:.4f}",
                f"{lo:.4f}", f"{hi:.4f}", _fmt(rl_m, 4),
                _fmt(md, 3), _fmt(mn, 3), _fmt(mx, 3),
                _fmt(mt_m, 3), _fmt(mt_sd, 3), n_early,
                lv.fp_preattack, lv.no_attack, lv.errors,
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
