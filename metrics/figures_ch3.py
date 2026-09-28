"""
metrics/figures_ch3.py — schematic figures of Ch. 3 (thesis_text/CH3_V2_TEXT.md).

Fig. 3.1  Data-dependency graph under a position-only GNSS spoof of one
          UAV (п. 3.2.5): data sources, detectors as comparisons of two
          quantities, recovery actions. Which nodes the attack taints is
          fixed in NODES below (the table 3.8 of the thesis), not computed:
          two nodes are not plain transitive closure (the innovation carries
          the taint only while EKF2 rejects the spoof; the EKF velocity is
          clean only under the adversary model).
Fig. 3.2  Placement of monitors and failure domains in architectures A,
          B and C (п. 3.3.3), with the properties O1–O3 of the operational
          CSMA definition (п. 3.2.1) under each panel.

Same print style as metrics/figures_ch4_v2.py: 16.5 cm text width,
8–9 pt text, two colours plus a secondary encoding (border style), labels
on the figure, no in-figure title (the caption carries it).

Usage
-----
    python3 -m metrics.figures_ch3 [--outdir figures]
"""

from __future__ import annotations

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

WIDTH_IN = 6.5

INK = "#1f1f1d"
INK_2 = "#5c5b56"
LINE = "#8a8983"           # neutral edges
TAINT = "#eb6834"          # slot 2 orange (as LOITER in Ch. 4)
TAINT_FILL = "#fbdccb"
DET_FILL = "#e8eef6"       # detectors: pale blue-grey
DET_EDGE = "#2a78d6"       # slot 1 blue (as zero-velocity hold in Ch. 4)

# Taint states (table 3.8)
TAINTED = "tainted"        # always / once EKF2 accepts the spoof
CONDITIONAL = "conditional"  # clean only under the adversary model
CLEAN = "clean"

# id: (label, column, y, state)
NODES = {
    "gnss_pos": ("GNSS-позиція", 0, 4.00, TAINTED),
    "gnss_vel": ("GNSS-швидкість", 0, 3.38, CLEAN),
    "imu": ("Інерціальні\nвимірювання", 0, 2.76, CLEAN),
    "ekf_pos": ("Оцінка позиції\nEKF2", 1, 4.00, TAINTED),
    "ann": ("Оголошення\nпозиції в mesh", 1, 3.38, TAINTED),
    "innov": ("Інновація\npos_horiz_ratio", 1, 2.76, TAINTED),
    "ekf_vel": ("Оцінка швидкості\nEKF2", 1, 2.14, CONDITIONAL),
    "peer_pos": ("Власні позиції\nсусідів", 0, 0.92, CLEAN),
    "range": ("Міжагентні\nдальності", 0, 0.34, CLEAN),
}

# id: (label, y, note)
DETECTORS = {
    "gps": ("Детектор gps", 2.76, "бачить, поки EKF2\nвідхиляє підміну"),
    "cc": ("Перехресна\nперевірка", 3.74, "два оголошення жертви;\nбачить лише стрибок\nоцінки; на сусідах"),
    "rng": ("Перевірка за\nдальностями", 0.63, "бачить і поступове\nприйняття; на сусідах"),
}

# id: (label, y, state, note)
ACTIONS = {
    "loiter": ("Утримання позиції\n(LOITER)", 4.00, TAINTED, "спирається на\nзаражену оцінку"),
    "zerovel": ("Утримання нульової\nшвидкості", 2.14, CONDITIONAL, "коректне, поки\nGNSS-швидкість правдива"),
}

# (src, dst, style) — style: "solid" | "weak"
EDGES = [
    ("gnss_pos", "ekf_pos", "solid"),
    ("imu", "ekf_pos", "solid"),
    ("gnss_vel", "ekf_vel", "solid"),
    ("imu", "ekf_vel", "solid"),
    ("gnss_pos", "ekf_vel", "weak"),
    ("gnss_pos", "innov", "solid"),
    ("ekf_vel", "innov", "solid"),
    ("ekf_pos", "ann", "solid"),
    ("innov", "gps", "solid"),
    ("ann", "cc", "solid"),
    ("ann", "rng", "solid"),
    ("peer_pos", "rng", "solid"),
    ("range", "rng", "solid"),
    ("ekf_pos", "loiter", "solid"),
    ("ekf_vel", "zerovel", "solid"),
]

COL_X = [0.05, 1.75, 3.65, 5.10]
COL_W = [1.40, 1.60, 1.25, 1.40]
BOX_H = 0.46


def all_ids() -> set:
    return set(NODES) | set(DETECTORS) | set(ACTIONS)


def state_of(node_id: str) -> str:
    """Taint state of a data node or an action (detectors have none)."""
    if node_id in NODES:
        return NODES[node_id][3]
    if node_id in ACTIONS:
        return ACTIONS[node_id][2]
    raise KeyError(node_id)


def detector_sides_clean(det_id: str) -> list:
    """Clean inputs of a detector: a detector can see an attack that the
    estimator has accepted only if at least one side is clean."""
    return [s for s, d, st in EDGES if d == det_id and st == "solid"
            and NODES[s][3] == CLEAN]


def _box(node_id):
    if node_id in NODES:
        _, col, y, _ = NODES[node_id]
    elif node_id in DETECTORS:
        col, y = 2, DETECTORS[node_id][1]
    else:
        col, y = 3, ACTIONS[node_id][1]
    return COL_X[col], y - BOX_H / 2, COL_W[col], BOX_H


def _style(state):
    if state == TAINTED:
        return dict(fc=TAINT_FILL, ec=TAINT, lw=1.3, ls="-")
    if state == CONDITIONAL:
        return dict(fc="white", ec=TAINT, lw=1.1, ls=(0, (3, 2)))
    return dict(fc="white", ec=LINE, lw=0.8, ls="-")


def _draw_box(ax, node_id, label, st, rounded=False, bold=False):
    x, y, w, h = _box(node_id)
    patch = FancyBboxPatch((x, y), w, h,
                           boxstyle="round,pad=0,rounding_size=0.08" if rounded
                           else "square,pad=0",
                           facecolor=st["fc"], edgecolor=st["ec"],
                           linewidth=st["lw"], linestyle=st["ls"], zorder=3)
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            fontsize=8, color=INK, zorder=4,
            fontweight="bold" if bold else "normal", linespacing=1.1)


def _anchor(node_id, side):
    x, y, w, h = _box(node_id)
    if side == "right":
        return (x + w, y + h / 2)
    if side == "left":
        return (x, y + h / 2)
    if side == "top":
        return (x + w / 2, y + h)
    return (x + w / 2, y)


def _col(node_id):
    if node_id in NODES:
        return NODES[node_id][1]
    return 2 if node_id in DETECTORS else 3


def _draw_edge(ax, src, dst, style):
    cs, cd = _col(src), _col(dst)
    if cs == cd:  # vertical inside one column
        ys, yd = _box(src)[1], _box(dst)[1]
        a, b = (_anchor(src, "bottom"), _anchor(dst, "top")) if ys > yd \
            else (_anchor(src, "top"), _anchor(dst, "bottom"))
    else:
        a, b = _anchor(src, "right"), _anchor(dst, "left")
    tainted = src in NODES and NODES[src][3] == TAINTED
    color = TAINT if tainted else LINE
    ls = (0, (1, 1.6)) if style == "weak" else "-"
    arr = FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=7,
                          color=color, lw=0.9 if style == "solid" else 0.8,
                          linestyle=ls, shrinkA=1, shrinkB=1, zorder=2)
    ax.add_patch(arr)
    return a, b


def fig_data_dependency(outdir: str) -> None:
    y0, y1 = -0.98, 4.55
    fig = plt.figure(figsize=(WIDTH_IN + 0.05, y1 - y0))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(-0.02, WIDTH_IN + 0.03)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")

    # failure domain of the victim (its autopilot and its monitor)
    ax.add_patch(Rectangle((0.0, 1.84), 3.42, 2.42, fill=False, ec=INK_2,
                           lw=0.8, ls=(0, (4, 2)), zorder=1))
    ax.text(0.02, 1.80, "Домен відмови жертви: автопілот і монітор",
            fontsize=7.5, color=INK_2, va="top")
    # neighbours
    ax.add_patch(Rectangle((0.0, 0.03), 1.50, 1.22, fill=False, ec=INK_2,
                           lw=0.8, ls=(0, (4, 2)), zorder=1))
    ax.text(0.02, -0.01, "Сусіди: поза доменом відмови жертви", fontsize=7.5,
            color=INK_2, va="top")

    # column heads
    for i, t_ in [(0, "Дані"), (1, "Похідні дані"), (2, "Детектори"),
                  (3, "Дії відновлення")]:
        ax.text(COL_X[i] + COL_W[i] / 2, 4.33, t_, fontsize=8, color=INK_2,
                ha="center", va="bottom", fontweight="bold", linespacing=1.0)

    for s, d, st in EDGES:
        a, b = _draw_edge(ax, s, d, st)

    for nid, (label, _c, _y, state) in NODES.items():
        _draw_box(ax, nid, label, _style(state))
    for did, (label, _y, note) in DETECTORS.items():
        _draw_box(ax, did, label, dict(fc=DET_FILL, ec=DET_EDGE, lw=1.0, ls="-"),
                  rounded=True)
        x, y, w, _h = _box(did)
        ax.text(x + w / 2, y - 0.04, note, fontsize=7.5, color=INK_2,
                ha="center", va="top", style="italic", linespacing=1.05)
    for aid, (label, _y, state, note) in ACTIONS.items():
        _draw_box(ax, aid, label, _style(state))
        x, y, w, _h = _box(aid)
        ax.text(x + w / 2, y - 0.04, note, fontsize=7.5, color=INK_2,
                ha="center", va="top", style="italic", linespacing=1.05)

    # key
    ky = -0.55
    items = [(TAINTED, "заражено атакою"),
             (CONDITIONAL, "не заражено лише за\nприйнятої моделі противника"),
             (CLEAN, "не залежить від атаки"),
             ("weak", "слабкий зв'язок\n(не виміряно)")]
    for i, (st, t_) in enumerate(items):
        x0 = 0.05 + (i % 2) * 3.25
        ky = -0.42 - (i // 2) * 0.36
        if st == "weak":
            ax.add_patch(FancyArrowPatch((x0, ky), (x0 + 0.30, ky), arrowstyle="-|>",
                                         mutation_scale=7, color=TAINT, lw=0.8,
                                         linestyle=(0, (1, 1.6))))
        else:
            s = _style(st)
            ax.add_patch(Rectangle((x0, ky - 0.09), 0.30, 0.18, facecolor=s["fc"],
                                   edgecolor=s["ec"], lw=s["lw"], ls=s["ls"]))
        ax.text(x0 + 0.38, ky, t_, fontsize=7.5, color=INK, va="center",
                linespacing=1.05)

    _save(fig, outdir, "fig3_1_data_dependency")



# ------------------------------------------------------------------ Fig. 3.2

# architecture: (title, shared_domain, mesh, coordinator, properties O1..O3)
ARCHS = {
    "A": ("A — централізована", True, False, False, (False, False, False)),
    "B": ("B — сегментована", False, False, False, (True, False, False)),
    "C": ("C — CSMA із самовідновленням", False, True, True, (True, True, True)),
}


def properties_of(arch: str) -> tuple:
    """(O1, O2, O3) of an architecture, as in table 3.5."""
    return ARCHS[arch][4]


def fig_architectures(outdir: str) -> None:
    y0, y1 = 0.02, 2.36
    fig = plt.figure(figsize=(WIDTH_IN + 0.05, y1 - y0))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(-0.02, WIDTH_IN + 0.03)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")

    pw, gap = 2.10, 0.10
    bw, bh, step = 0.50, 0.34, 0.68
    ap_y, mon_y = 0.48, 1.22          # bottoms of autopilot and monitor boxes
    bus_y = mon_y + bh + 0.16         # mesh bus above the monitors

    for p, arch in enumerate("ABC"):
        title, shared, mesh, coord, props = ARCHS[arch]
        x0 = p * (pw + gap)
        ax.text(x0 + pw / 2, 2.33, title, ha="center", va="top", fontsize=8.5,
                fontweight="bold", color=INK)
        cols = [x0 + 0.10 + k * step for k in range(3)]

        # failure domains
        if shared:
            fx, fw = cols[0] - 0.05, cols[2] + bw + 0.05 - (cols[0] - 0.05)
            ax.add_patch(Rectangle((fx, mon_y - 0.07), fw, bh + 0.14, fill=False,
                                   ec=INK_2, lw=0.8, ls=(0, (4, 2))))
            note = "один домен відмови:\nназемна станція"
        else:
            for cx in cols:
                ax.add_patch(Rectangle((cx - 0.04, ap_y - 0.07), bw + 0.08,
                                       mon_y + bh - ap_y + 0.14, fill=False,
                                       ec=INK_2, lw=0.8, ls=(0, (4, 2))))
            note = "домен відмови\nна кожен апарат"
        ax.text(x0 + pw / 2, 2.12, note, ha="center", va="top", fontsize=7.5,
                color=INK_2, linespacing=1.05)

        for k, cx in enumerate(cols):
            ax.add_patch(FancyBboxPatch((cx, ap_y), bw, bh, boxstyle="square,pad=0",
                                        facecolor="white", edgecolor=LINE,
                                        linewidth=0.8, zorder=3))
            ax.text(cx + bw / 2, ap_y + bh / 2, "uav_%d" % k, ha="center", va="center",
                    fontsize=8, color=INK, zorder=4)
            ax.add_patch(FancyBboxPatch((cx, mon_y), bw, bh,
                                        boxstyle="round,pad=0,rounding_size=0.06",
                                        facecolor=DET_FILL, edgecolor=DET_EDGE,
                                        linewidth=1.0, zorder=3))
            ax.text(cx + bw / 2, mon_y + bh / 2, "М%s" % "₀₁₂"[k], ha="center",
                    va="center", fontsize=8.5, color=INK, zorder=4)
            ax.add_patch(FancyArrowPatch((cx + bw / 2, ap_y + bh), (cx + bw / 2, mon_y),
                                         arrowstyle="-|>", mutation_scale=7, color=LINE,
                                         lw=0.9, shrinkA=1, shrinkB=1, zorder=2))
            if mesh:
                ax.plot([cx + bw / 2, cx + bw / 2], [mon_y + bh, bus_y], color=DET_EDGE,
                        lw=1.1, zorder=2)
        if mesh:
            ax.plot([cols[0] + bw / 2, cols[2] + bw / 2], [bus_y, bus_y], color=DET_EDGE,
                    lw=1.6, solid_capstyle="round", zorder=2)
            ax.text(cols[2] + bw / 2 + 0.08, bus_y, "mesh", ha="left", va="center",
                    fontsize=7.5, color=DET_EDGE, style="italic")
        if coord:
            cx = cols[0]
            ax.add_patch(plt.Circle((cx + 0.02, mon_y + bh - 0.02), 0.085,
                                    fc="white", ec=DET_EDGE, lw=1.0, zorder=5))
            ax.text(cx + 0.02, mon_y + bh - 0.025, "К", ha="center", va="center",
                    fontsize=7, color=DET_EDGE, zorder=6, fontweight="bold")

        marks = "   ".join("%s %s" % (n, "✓" if v else "✗")
                           for n, v in zip(("О1", "О2", "О3"), props))
        ax.text(x0 + pw / 2, 0.17, marks, ha="center", va="center", fontsize=8,
                color=INK)

    _save(fig, outdir, "fig3_2_architectures")


def _save(fig, outdir: str, name: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(outdir, "%s.%s" % (name, ext)),
                    bbox_inches="tight", facecolor="white", dpi=300)
    plt.close(fig)
    print("  %s/%s.{png,pdf}" % (outdir, name))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--outdir", default="figures")
    args = ap.parse_args(argv)
    fig_data_dependency(args.outdir)
    fig_architectures(args.outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
