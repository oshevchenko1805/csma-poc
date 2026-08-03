"""
metrics/plots_extra.py — figures 8 and 9.

Two results existed only as numbers and would have been lost:

fig8_losssweep   mesh-mediated detection rate vs channel loss, Wilson 95%
                 CI per level (R10). Built from
                 `runs_final/detection_vs_loss.csv`, which is the FINAL
                 belief-gated sweep (255 valid trials). The pilot table
                 that once appeared in RESULTS_NOTES (30/30 at loss 0,
                 0/30 at loss 0.6) is superseded and must not be plotted.

fig9_recovery    Recovery Success Rate (share of runs where the growth of
                 the off-plan deviation stopped) and functional MTTR
                 (time from isolation to that stop), per attack and
                 architecture. Both are Table 3.14 metrics that were
                 computed for the whole campaign and never reported.
                 `command_injection` is the sharp cell: A 0/15, B 0/15,
                 C 14/15.

Style, colours, hatching and labels are imported from `metrics.plots`
so the whole figure set stays visually consistent. No new dependencies.

Usage
-----
    python -m metrics.plots_extra \\
        --master runs_campaign/campaign_master.csv \\
        --loss   runs_final/detection_vs_loss.csv \\
        --outdir figures
"""

from __future__ import annotations

import argparse
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from metrics.stats import wilson_bounds  # noqa: E402
from metrics.plots import (  # noqa: E402
    ARCHS, ARCH_LABEL, FILL, HATCH,
    load, num, flag, valid_rows, quartiles, present_attacks,
    save, _category_axis, _legend_above,
)


# --- fig 8: loss sweep -------------------------------------------------


def fig_loss_sweep(loss_csv: str, outdir: str) -> None:
    with open(loss_csv) as fh:
        rows = list(csv.DictReader(fh))

    xs, ys, los, his, ns = [], [], [], [], []
    for r in rows:
        n = int(r["n"])
        k = int(r["detected"])
        lo, hi = wilson_bounds(k, n)
        centre = k / n
        xs.append(float(r["loss_prob"]))
        ys.append(centre)
        los.append(max(0.0, centre - lo))
        his.append(max(0.0, hi - centre))
        ns.append(n)

    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    ax.errorbar(xs, ys, yerr=[los, his], marker="^", markersize=5,
                color="0.15", ecolor="0.45", capsize=3, linewidth=1.2,
                label="C — виявлення через mesh (cross_check)")
    ax.axhline(0.0, color="0.55", linestyle="--", linewidth=1.0)
    ax.text(0.655, 0.03, "A, B — без mesh, виявлення відсутнє",
            fontsize=7.5, ha="right", va="bottom", color="0.35")

    for x, y, n in zip(xs, ys, ns):
        ax.annotate("n=%d" % n, (x, y), textcoords="offset points",
                    xytext=(0, 9), ha="center", fontsize=6.5, color="0.35")

    ax.set_xlabel("Імовірність втрати повідомлення в mesh-середовищі")
    ax.set_ylabel("Частка виявлення (detection rate)")
    ax.set_ylim(-0.05, 1.08)
    ax.set_xticks(xs)
    ax.set_xticklabels(["%.2f" % x for x in xs], fontsize=8)
    _legend_above(ax, ncol=1)
    save(fig, outdir, "fig8_losssweep")


# --- fig 9: recovery ---------------------------------------------------


def _rate_bars(ax, rows: list, attacks: list, field: str) -> None:
    width = 0.26
    for i, arch in enumerate(ARCHS):
        xs, ys, los, his = [], [], [], []
        for j, attack in enumerate(attacks):
            sub = [r for r in rows
                   if r["architecture"] == arch and r["attack"] == attack]
            vals = [flag(r, field) for r in sub]
            vals = [v for v in vals if v is not None]
            if not vals:
                # an empty cell is a result here, not missing data
                xs.append(j + (i - 1) * width)
                ys.append(0.0)
                los.append(0.0)
                his.append(0.0)
                continue
            k, n = sum(1 for v in vals if v), len(vals)
            lo, hi = wilson_bounds(k, n)
            centre = k / n
            xs.append(j + (i - 1) * width)
            ys.append(centre)
            los.append(max(0.0, centre - lo))
            his.append(max(0.0, hi - centre))
        ax.bar(xs, ys, width, yerr=[los, his], capsize=2.5,
               color=FILL[arch], edgecolor="black", linewidth=0.7,
               hatch=HATCH[arch], label=ARCH_LABEL[arch],
               error_kw={"linewidth": 0.8})


def _median_bars(ax, rows: list, attacks: list, field: str) -> None:
    width = 0.26
    for i, arch in enumerate(ARCHS):
        for j, attack in enumerate(attacks):
            sub = [r for r in rows
                   if r["architecture"] == arch and r["attack"] == attack]
            q = quartiles([num(r, field) for r in sub])
            x = j + (i - 1) * width
            if q is None:
                # no run in this cell ever stabilised: mark it, do not skip
                ax.text(x, 0.075, "×", ha="center", va="center",
                        fontsize=11, color="0.15")
                continue
            med, q1, q3, _n = q
            ax.bar([x], [med], width,
                   yerr=[[max(0.0, med - q1)], [max(0.0, q3 - med)]],
                   capsize=2.5, color=FILL[arch], edgecolor="black",
                   linewidth=0.7, hatch=HATCH[arch],
                   label=ARCH_LABEL[arch] if j == 0 else None,
                   error_kw={"linewidth": 0.8})


def fig_recovery(rows: list, outdir: str) -> None:
    rows = valid_rows(rows)
    attacks = present_attacks(rows, skip_none=True)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.4, 6.4), sharex=True)

    _rate_bars(ax1, rows, attacks, "degradation_stopped")
    ax1.set_ylabel("Recovery success rate")
    ax1.set_ylim(0, 1.05)
    _legend_above(ax1, ncol=3)

    ax2.set_yscale("log")
    ax2.set_ylim(0.05, 300)
    _median_bars(ax2, rows, attacks, "mttr_functional_s")
    ax2.set_ylabel("MTTR functional, с (медіана, IQR)")
    ax2.set_yticks([0.1, 1, 10, 100])
    ax2.set_yticklabels(["0,1", "1", "10", "100"])
    ax2.text(0.995, 0.955,
             "× — у клітинці жоден запуск не стабілізувався",
             transform=ax2.transAxes, fontsize=7.5, va="top", ha="right",
             color="0.25")
    _category_axis(ax2, attacks)

    save(fig, outdir, "fig9_recovery")


# --- cli ---------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--master", default="runs_campaign/campaign_master.csv")
    ap.add_argument("--loss", default="runs_final/detection_vs_loss.csv")
    ap.add_argument("--outdir", default="figures")
    args = ap.parse_args()

    print("figures ->", args.outdir)
    fig_loss_sweep(args.loss, args.outdir)
    fig_recovery(load(args.master), args.outdir)


if __name__ == "__main__":
    main()
