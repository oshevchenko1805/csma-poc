"""
metrics/plots_extra.py — figures 4 and 7.

Kept separate from `metrics.plots` only because they were added later;
`metrics.plots.main()` drives both, so the whole set is produced by one
command and the numbering is sequential.

fig4_recovery    How long the off-plan deviation keeps growing after the
                 attack, and whether it stops at all. Lower is better,
                 and the axis says so. Two honesty devices are built into
                 the figure rather than left to the caption:

                   * cells where NO run ever stabilised (A and B under
                     command injection) are drawn as full-height hatched
                     bars labelled "не настає" — an empty slot would read
                     as missing data;
                   * the 40-60 s band, where A and B sit under every GPS
                     scenario, is shaded and labelled as saturation of
                     the 50 m offset. Their deviation stops growing
                     because the spoof runs out of room, not because the
                     architecture did anything. Without that label the
                     bar claims a recovery that did not happen.

                 Each bar carries its Recovery Success Rate as k/n, so
                 the second Table 3.14 metric is on the same panel
                 instead of a second, ceiling-bound one.

fig7_losssweep   Mesh-mediated detection rate vs channel loss, Wilson 95%
                 CI and n per level (R10). Built from
                 `runs_final/detection_vs_loss.csv`, the FINAL
                 belief-gated sweep of 255 valid trials. The pilot table
                 that once appeared in RESULTS_NOTES (30/30 at loss 0,
                 0/30 at loss 0.6) is superseded and must not be plotted.

Deliberately NOT plotted
------------------------
* Mesh overhead. A 0, B 0, C 122 kB/run is a table row; a bar chart with
  two zero bars informs nobody.
* Phase-vs-geometry per-run scatter. It restated fig3 with more ink and
  no extra conclusion.
* Recovery Success Rate as its own panel. Twelve of fifteen cells sit at
  the ceiling; only command injection discriminates, and that cell is
  carried here as an annotation.

Usage
-----
    python -m metrics.plots runs_campaign/campaign_master.csv --outdir figures
"""

from __future__ import annotations

import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from metrics.stats import wilson_bounds  # noqa: E402
from metrics.plots import (  # noqa: E402
    ARCHS, ARCH_LABEL, FILL, HATCH,
    num, flag, valid_rows, quartiles, present_attacks,
    save, _category_axis, _legend_above,
)

_TOP = 400.0      # top of the log axis for fig4
_BOTTOM = 0.05    # bottom of the log axis for fig4


# --- fig 4: recovery ---------------------------------------------------


def _success(rows: list, arch: str, attack: str) -> tuple:
    sub = [r for r in rows
           if r["architecture"] == arch and r["attack"] == attack]
    vals = [flag(r, "degradation_stopped") for r in sub]
    vals = [v for v in vals if v is not None]
    return sum(1 for v in vals if v), len(vals)


def fig_recovery(rows: list, outdir: str) -> None:
    rows = valid_rows(rows)
    attacks = present_attacks(rows, skip_none=True)

    fig, ax = plt.subplots(figsize=(8.8, 4.6))
    ax.set_yscale("log")
    ax.set_ylim(_BOTTOM, _TOP)

    # room on the right for the band label, so it never sits on a bar
    ax.set_xlim(-0.55, len(attacks) - 1 + 1.35)

    # saturation band: where A and B land under every GPS scenario
    ax.axhspan(40, 60, color="0.90", zorder=0)
    ax.text(len(attacks) - 1 + 0.50, 49,
            "смуга насичення\nспуфу 50 м:\nвідхилення\nперестає зростати\nсамо, без дії\nархітектури",
            fontsize=6.5, ha="left", va="center", color="0.30", zorder=1)

    width = 0.26
    labelled = set()
    for i, arch in enumerate(ARCHS):
        for j, attack in enumerate(attacks):
            sub = [r for r in rows
                   if r["architecture"] == arch and r["attack"] == attack]
            q = quartiles([num(r, "mttr_functional_s") for r in sub])
            k, n = _success(rows, arch, attack)
            x = j + (i - 1) * width
            lab = ARCH_LABEL[arch] if arch not in labelled else None

            if q is None:
                # nothing in this cell ever stabilised: full-height bar,
                # so the eye reads "longest of all", not "no data"
                ax.bar([x], [_TOP - _BOTTOM], width, bottom=_BOTTOM,
                       color="white", edgecolor="black", linewidth=0.9,
                       hatch="xxx", label=lab, zorder=2)
                ax.text(x, 3.0, "не настає", fontsize=7.5, rotation=90,
                        ha="center", va="center", color="0.1", zorder=3,
                        bbox=dict(boxstyle="square,pad=0.15",
                                  facecolor="white", edgecolor="none"))
            else:
                med, q1, q3, _n = q
                ax.bar([x], [med], width,
                       yerr=[[max(0.0, med - q1)], [max(0.0, q3 - med)]],
                       capsize=2.5, color=FILL[arch], edgecolor="black",
                       linewidth=0.7, hatch=HATCH[arch], label=lab,
                       error_kw={"linewidth": 0.8}, zorder=2)
            labelled.add(arch)

            if n:
                ax.text(x, _TOP * 1.12, "%d/%d" % (k, n), fontsize=6.5,
                        ha="center", va="bottom", color="0.35")

    ax.set_ylabel("Час до припинення зростання відхилення\n"
                  "від місійного плану, с (медіана, IQR)")
    ax.set_yticks([0.1, 1, 10, 100])
    ax.set_yticklabels(["0,1", "1", "10", "100"])
    ax.text(0.988, 0.03, "менше = краще", transform=ax.transAxes,
            fontsize=8, va="bottom", ha="right", color="0.25")
    _category_axis(ax, attacks)
    ax.set_xlim(-0.55, len(attacks) - 1 + 1.35)   # _category_axis resets margins
    _legend_above(ax, ncol=3)
    fig.text(0.5, -0.02,
             "Над стовпчиками: частка запусків, у яких відхилення "
             "стабілізувалося (recovery success rate)",
             fontsize=7, ha="center", color="0.35")
    save(fig, outdir, "fig4_recovery")


# --- fig 7: loss sweep -------------------------------------------------


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

    fig, ax = plt.subplots(figsize=(7.6, 3.9))
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
    save(fig, outdir, "fig7_losssweep")
