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

from metrics import style  # noqa: E402
from metrics.stats import wilson_bounds  # noqa: E402
from metrics.plots import (  # noqa: E402
    ARCHS, ARCH_LABEL, FILL, HATCH,
    num, flag, valid_rows, quartiles, present_attacks,
    save, _category_axis, _legend_above,
)

_TOP = 68.0       # top of the linear axis for fig4
_WINDOW_S = 60.0  # observation window after injection
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
    ax.set_ylim(0, _TOP)

    # saturation band: where A and B land under every GPS scenario.
    # Placed over the comm-disruption group, the only stretch of the band
    # with no bars in it.
    ax.axhspan(40, 60, color="0.90", zorder=0)
    ax.text(1.0, 50.0,
            "смуга насичення\nспуфу 50 м: відхилення\nперестає зростати\n"
            "само, без дії архітектури",
            fontsize=6.3, ha="center", va="center", color="0.30", zorder=1,
            bbox=dict(boxstyle="square,pad=0.25", facecolor="white",
                      edgecolor="none", alpha=0.85))
    # end of the observation window: bars are capped here, so nobody
    # reads the height of a "never stabilised" bar as a measured value
    ax.axhline(_WINDOW_S, color="0.35", linewidth=0.9, linestyle="--",
               zorder=1)
    ax.text(len(attacks) - 1 + 0.42, _WINDOW_S,
            "кінець вікна\nспостереження", fontsize=6.5, ha="right",
            va="bottom", color="0.35", zorder=3)

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
                ax.bar([x], [_TOP], width, color="white",
                       edgecolor="black", linewidth=0.9, hatch="xxx",
                       label=lab, zorder=2)
                ax.annotate("", xy=(x, _TOP * 1.005), xytext=(x, _TOP * 0.86),
                            arrowprops=dict(arrowstyle="-|>", color="black",
                                            linewidth=1.1), zorder=3)
                ax.text(x, _TOP * 0.45, "не настає", fontsize=7.5,
                        rotation=90, ha="center", va="center", color="0.1",
                        zorder=3,
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
                # inside the axes: above the frame it collides with the
                # legend, and the top strip here is free in every column
                y_lab = (q[0] + max(0.0, q[2] - q[0]) + 1.6) if q else 62.0
                ax.text(x, y_lab, "%d/%d" % (k, n), fontsize=6.5,
                        ha="center", va="bottom", color="0.30", zorder=4,
                        bbox=dict(boxstyle="square,pad=0.12",
                                  facecolor="white", edgecolor="none",
                                  alpha=0.85))

    ax.set_ylabel("Час до припинення зростання відхилення від\n"
                  "місійного плану, с (медіана, IQR; менше = краще)")
    ax.set_yticks([0, 10, 20, 30, 40, 50, 60])
    _category_axis(ax, attacks)
    ax.set_xlim(-0.55, len(attacks) - 1 + 0.55)
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

    style.apply()
    fig, ax = plt.subplots(figsize=(7.6, 3.9))
    ax.errorbar(xs, ys, yerr=[los, his], marker="^", markersize=5,
                color=style.COLOR["C"], ecolor=style.COLOR["B"], capsize=3,
                linewidth=1.6,
                label="C — виявлення через mesh (cross_check)")
    # Нульова лінія A і B НЕ є результатом цього свипу: у
    # `detection_vs_loss.csv` виміряна тільки архітектура C. Раніше тут
    # стояв підпис «A, B — без mesh, виявлення відсутнє», який читався
    # як виміряна на цьому графіку величина. Насправді нуль береться з
    # кампанії (0/28 і 0/30 під detector_takeout, вже після виправлення
    # гейта детекції), тобто з іншого експерименту, і підпис має це
    # називати. Лінію лишаємо як опорну, але не як дані свипу.
    ax.axhline(0.0, color=style.EDGE["A"], linestyle=":", linewidth=1.0)
    ax.text(0.02, 0.035,
            "A і B у цьому свипі не оцінювались: резервного mesh-каналу\n"
            "в них немає за побудовою. У кампанії — 0/28 і 0/30.",
            fontsize=7.4, ha="left", va="bottom", color=style.EDGE["A"],
            linespacing=1.5)

    for x, y, n in zip(xs, ys, ns):
        ax.annotate("n=%d" % n, (x, y), textcoords="offset points",
                    xytext=(0, 9), ha="center", fontsize=6.5,
                    color=style.MUTED)

    ax.set_xlabel("Імовірність втрати повідомлення в mesh-середовищі")
    ax.set_ylabel("Частка виявлення (detection rate)")
    ax.set_ylim(-0.05, 1.08)
    ax.set_xticks(xs)
    ax.set_xticklabels(["%.2f" % x for x in xs], fontsize=8)
    style.despine(ax)
    _legend_above(ax, ncol=1)
    save(fig, outdir, "fig4_1_losssweep")
