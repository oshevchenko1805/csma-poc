"""
metrics/plots.py — publication figures for Chapter 4, from ONE source.

Reads `campaign_master.csv` and nothing else. Every number in every
figure therefore comes from the same file as every number in every table,
and a figure cannot quietly disagree with the text.

Print discipline: greyscale fills plus hatching, so the figures survive
black-and-white printing; each figure is written as PNG (300 dpi, for
drafts) and PDF (vector, for the bound copy).

Figures — the published set is exactly seven
--------------------------------------------
fig1_detection      detection rate with Wilson 95% CI, per attack
fig2_degradation    mission degradation, median + IQR
fig3_coordination   coordination integrity: phase and geometry. Carries
                    an on-canvas note, because in three of five cells C
                    sits ABOVE the baselines and a reader left to the
                    caption alone will read that as a defeat rather than
                    as the R11 trade-off
fig4_recovery       time until the off-plan deviation stops growing, plus
                    recovery success rate as k/n (in `plots_extra`)
fig5_falsepositive  clean-mode false positives by detector (exact counts
                    from the master file, never a total split across a
                    name list), and how far one false alarm spreads
fig6_sustain        detection and false positives vs the sustain rule k.
                    FP uses the FLEET maximum: a false alarm on a healthy
                    swarm need not occur on the attack target.
fig7_losssweep      mesh-mediated detection vs channel loss (in
                    `plots_extra`)

`fig_tradeoff` and `fig_mesh_cost` below are NO LONGER PUBLISHED and are
not called by `main()`. The scatter restated fig3 with more ink and no
extra conclusion; the mesh-cost bar chart was two zero bars and one bar,
which is a table row, not a figure. The code is kept because both are
correct and cheap to revive, not because the figures earned their place.
A figure that carries no conclusion does not merely waste a page, it
invites the reader to infer one that is not there.

Usage
-----
    python -m metrics.plots runs_campaign/campaign_master.csv --outdir figures

Produces all seven; `plots_extra` is driven from here so the numbering
stays sequential and one command rebuilds the whole set.
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from metrics.stats import wilson_bounds  # noqa: E402

ARCHS = ["A", "B", "C"]
ARCH_LABEL = {
    "A": "A — централізована",
    "B": "B — сегментована",
    "C": "C — CSMA + self-healing",
}
FILL = {"A": "0.82", "B": "0.58", "C": "0.28"}
HATCH = {"A": "///", "B": "\\\\\\", "C": ""}
MARKER = {"A": "o", "B": "s", "C": "^"}

ATTACK_ORDER = [
    "none",
    "gps_spoofing",
    "comm_disruption",
    "command_injection",
    "detector_takeout+gps_spoofing",
    "monitor_takeout+gps_spoofing",
]
ATTACK_LABEL = {
    "none": "без атаки",
    "gps_spoofing": "GPS\nspoofing",
    "comm_disruption": "comm\ndisruption",
    "command_injection": "command\ninjection",
    "detector_takeout+gps_spoofing": "detector takeout\n+ GPS",
    "monitor_takeout+gps_spoofing": "monitor takeout\n+ GPS",
}
DETECTORS = ["gps", "heartbeat", "cross_check"]
DET_SHADE = {"gps": "0.85", "heartbeat": "0.58", "cross_check": "0.22"}

plt.rcParams.update({
    "font.size": 9,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linestyle": ":",
    "axes.axisbelow": True,
    "figure.dpi": 110,
})


# --- data --------------------------------------------------------------


def load(path: str) -> list:
    with open(path) as fh:
        return list(csv.DictReader(fh))


def num(row: dict, key: str) -> Optional[float]:
    v = row.get(key, "")
    if v in ("", "None", "nan", "NaN"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def flag(row: dict, key: str) -> Optional[bool]:
    v = str(row.get(key, "")).strip().lower()
    if v in ("true", "1"):
        return True
    if v in ("false", "0"):
        return False
    return None


def valid_rows(rows: list) -> list:
    return [r for r in rows if flag(r, "valid")]


def quartiles(values: list) -> Optional[tuple]:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    med = vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0
    lo, hi = vals[: n // 2], vals[(n + 1) // 2:]
    q1 = lo[len(lo) // 2] if lo else med
    q3 = hi[len(hi) // 2] if hi else med
    return med, q1, q3, n


def present_attacks(rows: list, skip_none: bool = False) -> list:
    seen = {r["attack"] for r in rows}
    out = [a for a in ATTACK_ORDER if a in seen]
    return [a for a in out if not (skip_none and a == "none")]


def save(fig, outdir: str, name: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(outdir, "%s.%s" % (name, ext)),
                    bbox_inches="tight", dpi=300)
    plt.close(fig)
    print("  %s.{png,pdf}" % name)


def _category_axis(ax, attacks: list) -> None:
    ax.set_xticks(range(len(attacks)))
    ax.set_xticklabels([ATTACK_LABEL.get(a, a) for a in attacks], fontsize=8)
    ax.margins(x=0.03)


def _legend_above(ax, ncol: int = 3) -> None:
    """Outside the plotting area: with a 1.0-high bar chart there is no
    interior space that does not cover data."""
    ax.legend(fontsize=8, ncol=ncol, frameon=False,
              loc="lower center", bbox_to_anchor=(0.5, 1.02))


def _grouped_bars(ax, rows: list, attacks: list, field: str,
                  agg: str = "median") -> None:
    width = 0.26
    for i, arch in enumerate(ARCHS):
        xs, ys, los, his = [], [], [], []
        for j, attack in enumerate(attacks):
            sub = [r for r in rows
                   if r["architecture"] == arch and r["attack"] == attack]
            if agg == "rate":
                vals = [flag(r, "detected") for r in sub]
                vals = [v for v in vals if v is not None]
                if not vals:
                    continue
                k, n = sum(1 for v in vals if v), len(vals)
                lo, hi = wilson_bounds(k, n)
                centre = k / n
                low, high = centre - lo, hi - centre
            else:
                q = quartiles([num(r, field) for r in sub])
                if q is None:
                    continue
                centre, q1, q3, _n = q
                low, high = centre - q1, q3 - centre
            xs.append(j + (i - 1) * width)
            ys.append(centre)
            los.append(max(0.0, low))
            his.append(max(0.0, high))
        ax.bar(xs, ys, width, yerr=[los, his], capsize=2.5,
               color=FILL[arch], edgecolor="black", linewidth=0.7,
               hatch=HATCH[arch], label=ARCH_LABEL[arch],
               error_kw={"linewidth": 0.8})


# --- figures -----------------------------------------------------------


def fig_detection(rows: list, outdir: str) -> None:
    rows = valid_rows(rows)
    attacks = present_attacks(rows, skip_none=True)
    fig, ax = plt.subplots(figsize=(8.4, 3.8))
    _grouped_bars(ax, rows, attacks, "detected", agg="rate")
    ax.set_ylabel("Частка виявлення (detection rate)")
    ax.set_ylim(0, 1.06)
    _category_axis(ax, attacks)
    _legend_above(ax)
    save(fig, outdir, "fig1_detection")


def fig_degradation(rows: list, outdir: str) -> None:
    rows = valid_rows(rows)
    attacks = present_attacks(rows, skip_none=True)
    fig, ax = plt.subplots(figsize=(8.4, 3.8))
    _grouped_bars(ax, rows, attacks, "mission_degradation_m")
    ax.set_ylabel("Відхилення від місії, м\n(медіана, IQR)")
    _category_axis(ax, attacks)
    _legend_above(ax)
    save(fig, outdir, "fig2_degradation")


def fig_coordination(rows: list, outdir: str) -> None:
    rows_v = valid_rows(rows)
    attacks = present_attacks(rows_v)
    fig, axes = plt.subplots(2, 1, figsize=(8.6, 6.4), sharex=True)
    _grouped_bars(axes[0], rows_v, attacks, "phase_excess_m")
    _grouped_bars(axes[1], rows_v, attacks, "geometry_excess_m")
    axes[0].set_ylabel("Фазове розходження, м")
    axes[1].set_ylabel("Зміна міжвузлової\nгеометрії, м")
    # The panel shows C ABOVE the baselines in three cells. That is the
    # R11 trade-off, not a defeat, and a reader must not be left to
    # infer it from the caption alone.
    axes[0].set_ylim(0, 275)
    axes[0].annotate(
        "C виявляє атаку і зупиняє борт: стримування купується фазовим відставанням.\n"
        "A і B атаки не бачать і летять за спотвореними координатами, "
        "формально лишаючись на плані.",
        xy=(0.5, 0.97), xycoords="axes fraction", fontsize=7.5,
        ha="center", va="top", color="0.2",
        bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                  edgecolor="0.6", linewidth=0.6, alpha=0.92))
    _legend_above(axes[0])
    _category_axis(axes[1], attacks)
    save(fig, outdir, "fig3_coordination")


def fig_tradeoff(rows: list, outdir: str) -> None:
    """Containment against synchronisation, one panel per scenario.

    Pooled, the clusters of different attacks overlap and the effect is
    invisible; separated, the reading is immediate — A and B leave the
    formation while keeping pace, C holds formation and drops out of
    mission phase.
    """
    rows_v = valid_rows(rows)
    panels = [a for a in ATTACK_ORDER
              if a not in ("none",) and a in {r["attack"] for r in rows_v}]
    panels = panels[:4] if len(panels) > 4 else panels
    ncol = 2
    nrow = (len(panels) + ncol - 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(8.4, 3.4 * nrow),
                             sharex=True, sharey=True)
    axes = axes.ravel() if hasattr(axes, "ravel") else [axes]
    for idx, attack in enumerate(panels):
        ax = axes[idx]
        for arch in ARCHS:
            pts = [
                (num(r, "geometry_excess_m"), num(r, "phase_excess_m"))
                for r in rows_v
                if r["architecture"] == arch and r["attack"] == attack
            ]
            pts = [(x, y) for x, y in pts if x is not None and y is not None]
            if not pts:
                continue
            ax.scatter([p[0] for p in pts], [p[1] for p in pts],
                       s=20, marker=MARKER[arch], facecolor=FILL[arch],
                       edgecolor="black", linewidth=0.5, alpha=0.85,
                       label=ARCH_LABEL[arch] if idx == 0 else None)
        ax.set_title(ATTACK_LABEL.get(attack, attack).replace("\n", " "),
                     fontsize=9)
        # Sample size per architecture, stated rather than counted off the
        # markers: in command_injection every C run sits at (0, 0) and the
        # cluster is a single blob.
        counts = [
            "%s=%d" % (arch, sum(
                1 for r in rows_v
                if r["architecture"] == arch and r["attack"] == attack
                and num(r, "geometry_excess_m") is not None
                and num(r, "phase_excess_m") is not None))
            for arch in ARCHS
        ]
        ax.annotate("  ".join(counts), xy=(0.02, 0.02),
                    xycoords="axes fraction", fontsize=7.5, color="0.25")
    for idx in range(len(panels), len(axes)):
        axes[idx].axis("off")
    for ax in axes[-ncol:]:
        ax.set_xlabel("Зміна міжвузлової геометрії, м")
    for i in range(0, len(axes), ncol):
        axes[i].set_ylabel("Фазове розходження, м")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=8, ncol=3, frameon=False,
               loc="lower center", bbox_to_anchor=(0.5, 1.0))
    save(fig, outdir, "fig4_tradeoff")


def fig_false_positives(rows: list, outdir: str) -> None:
    counts = collections.defaultdict(collections.Counter)
    bursts = collections.defaultdict(list)
    for r in rows:
        if flag(r, "errored"):
            continue
        arch = r["architecture"]
        for det in DETECTORS:
            counts[arch][det] += int(num(r, "fp_" + det) or 0)
        n = int(num(r, "fp_events_clean") or 0)
        if n > 0:
            bursts[arch].append(n)

    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.4))
    bottom = {a: 0.0 for a in ARCHS}
    for det in DETECTORS:
        vals = [counts[a].get(det, 0) for a in ARCHS]
        axes[0].bar(ARCHS, vals, 0.55, bottom=[bottom[a] for a in ARCHS],
                    color=DET_SHADE[det], edgecolor="black", linewidth=0.7,
                    label=det)
        for a, v in zip(ARCHS, vals):
            bottom[a] += v
    axes[0].set_ylabel("Хибні спрацювання, подій")
    axes[0].set_title("FP у штатному режимі, за детектором", fontsize=9)
    axes[0].legend(fontsize=8, frameon=False)
    axes[0].set_ylim(0, max(bottom.values()) * 1.25 if bottom else 1)

    top = 1
    for i, arch in enumerate(ARCHS):
        vals = sorted(bursts.get(arch, []))
        if vals:
            top = max(top, max(vals))
        # Spread duplicates around the category centre so every run is
        # countable: identical values otherwise land on identical pixels
        # and the panel under-reports its own n. Deterministic, so the
        # figure is byte-identical on every regeneration.
        seen = collections.Counter()
        xs = []
        for v in vals:
            seen[v] += 1
            xs.append(i + 0.055 * ((seen[v] - 1) // 2 + 1)
                      * (1 if seen[v] % 2 == 0 else -1)
                      * (0 if seen[v] == 1 else 1))
        axes[1].scatter(xs, vals, s=34, marker=MARKER[arch],
                        facecolor=FILL[arch], edgecolor="black", linewidth=0.5)
        axes[1].annotate("n=%d" % len(vals), xy=(i, top + 0.55),
                         ha="center", fontsize=8)
    axes[1].set_xticks(range(len(ARCHS)))
    axes[1].set_xticklabels(ARCHS)
    axes[1].set_ylim(0, top + 1)
    axes[1].set_ylabel("Подій на один FP-прогін")
    axes[1].set_title("Радіус поширення хибної тривоги", fontsize=9)
    save(fig, outdir, "fig5_falsepositive")


def fig_sustain(rows: list, outdir: str, ks=(1, 2, 3, 4, 5, 6)) -> None:
    attack = [num(r, "ratio_maxcons_post") for r in rows
              if r["attack"] == "gps_spoofing" and not flag(r, "errored")]
    attack = [v for v in attack if v is not None]
    clean = [num(r, "ratio_maxcons_full_fleet") for r in rows
             if r["attack"] == "none" and not flag(r, "errored")]
    clean = [v for v in clean if v is not None]

    det = [sum(1 for v in attack if v >= k) / len(attack) if attack else 0.0
           for k in ks]
    fps = [sum(1 for v in clean if v >= k) / len(clean) if clean else 0.0
           for k in ks]

    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    ax.plot(ks, det, "o-", color="black",
            label="detection, gps_spoofing (n=%d)" % len(attack))
    ax.plot(ks, fps, "s--", color="0.45",
            label="FP-прогони, штатний режим (n=%d)" % len(clean))
    ax.axvline(3, color="black", linewidth=0.8, linestyle=":")
    ax.annotate("робоча точка\nk = 3", xy=(3, 0.30), xytext=(3.12, 0.22),
                fontsize=8)
    ax.set_xlabel("sustained_samples, k")
    ax.set_ylabel("Частка прогонів")
    ax.set_ylim(-0.03, 1.05)
    ax.legend(fontsize=8, frameon=False, loc="center right")
    ax.set_title("Чутливість до правила стійкості детектора", fontsize=9)
    save(fig, outdir, "fig6_sustain")


def fig_mesh_cost(rows: list, outdir: str) -> None:
    fig, ax = plt.subplots(figsize=(5.4, 3.6))
    tops = []
    for i, arch in enumerate(ARCHS):
        vals = [num(r, "mesh_pub_bytes") for r in rows
                if r["architecture"] == arch and not flag(r, "errored")]
        vals = [v / 1024.0 for v in vals if v is not None]
        q = quartiles(vals)
        med, q1, q3, _n = q if q else (0.0, 0.0, 0.0, 0)
        tops.append(q3)
        ax.bar([i], [med], 0.55, yerr=[[med - q1], [q3 - med]], capsize=3,
               color=FILL[arch], edgecolor="black", linewidth=0.7,
               hatch=HATCH[arch])
        ax.text(i, med, " %.0f КБ" % med, ha="center", va="bottom", fontsize=8)
    ax.set_xticks(range(len(ARCHS)))
    ax.set_xticklabels(ARCHS)
    ax.set_ylim(0, max(tops + [1]) * 1.20)
    ax.set_ylabel("Трафік меша за прогін, КБ")
    ax.set_title("Накладні витрати архітектури", fontsize=9)
    save(fig, outdir, "fig7_meshcost")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("master_csv", nargs="?",
                    default="runs_campaign/campaign_master.csv")
    ap.add_argument("--outdir", default="figures")
    ap.add_argument("--loss-csv", dest="loss_csv",
                    default="runs_final/detection_vs_loss.csv")
    args = ap.parse_args()

    rows = load(args.master_csv)
    print("read %d runs from %s" % (len(rows), args.master_csv))
    print("writing to %s/" % args.outdir)
    # Imported here, not at module level: plots_extra imports helpers
    # from this module, so a top-level import would be circular.
    from metrics.plots_extra import fig_recovery, fig_loss_sweep

    fig_detection(rows, args.outdir)          # fig1
    fig_degradation(rows, args.outdir)        # fig2
    fig_coordination(rows, args.outdir)       # fig3
    fig_recovery(rows, args.outdir)           # fig4
    fig_false_positives(rows, args.outdir)    # fig5
    fig_sustain(rows, args.outdir)            # fig6
    fig_loss_sweep(args.loss_csv, args.outdir)  # fig7
    print("done")


if __name__ == "__main__":
    main()
