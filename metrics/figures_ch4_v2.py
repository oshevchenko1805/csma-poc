"""
metrics/figures_ch4_v2.py — new Fig. 4.3 (mechanism) and Fig. 4.4 (H2
result) for Ch. 4, replacing the route-distance figures (review P1/P4).

One message per figure (4.2 below):
  4.3  The attack corrupts the position estimate identically in every
       arm (≈50 m at ≈7.5 s); what differs is only what the response does
       with that estimate. Three small multiples on shared axes:
       LOITER before the jump, LOITER after the jump, zero-velocity hold.
  4.4  H2: per-run drift after the response, LOITER vs zero-velocity
       hold, three GPS scenarios. Every run is a dot; the median is
       labelled.

Data: stage-3 campaign (runs_stage3, 5 m altitude layers, 0 contacts),
because it holds both actions under identical conditions; its LOITER arm
reproduces thesis-campaign-v1 C (drift 50.1 vs 50.0 m, jump 7.8 vs 7.7 s).

Print-first: 16.5 cm text width, 8–9 pt text, two series colours that
pass the CVD/contrast checks plus a secondary encoding (line style /
marker shape), neutral grey for context, labels on the data instead of
legends, no in-figure title (the caption carries it).

  4.2  Architecture comparison map (thesis-campaign-v1): A, B, C x GPS
       spoofing, command injection; per cell the run nearest to the cell
       median of its physical metric (C/GPS: drift after response; others:
       route distance, which is physical where the estimate is not
       shifted, and equals the whole-route 50 m shift for A/B/GPS).

Usage
-----
    python3 -m metrics.figures_ch4_v2 <runs_stage3_dir> <stage3_h2_rows.json> <v1_runs_root> [--outdir figures]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from metrics.derived import _attack_ts, load_events  # noqa: E402

WIDTH_IN = 6.5
WINDOW_S = 60.0
GRID = [float(t) for t in range(0, 61)]

INK = "#1f1f1d"
INK_2 = "#5c5b56"
GRID_C = "#e4e3de"
NAV = "#8a8983"            # context: navigation error (neutral)
LOITER = "#eb6834"         # slot 2 orange
ZEROVEL = "#2a78d6"        # slot 1 blue

SCEN = [("gps_spoofing", "GPS spoofing"),
        ("monitor_takeout+gps_spoofing", "Monitor takeout\n+ GPS spoofing"),
        ("detector_takeout+gps_spoofing", "Detector takeout\n+ GPS spoofing")]

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 8.5,
    "axes.edgecolor": INK_2,
    "axes.labelcolor": INK,
    "axes.linewidth": 0.6,
    "xtick.color": INK_2,
    "ytick.color": INK_2,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": GRID_C,
    "grid.linewidth": 0.6,
    "axes.axisbelow": True,
    "savefig.dpi": 300,
})


# ------------------------------------------------------------------ data

def _interp(ts: list, vs: list, t: float):
    if not ts or t < ts[0] or t > ts[-1]:
        return None
    import bisect
    i = bisect.bisect_left(ts, t)
    if i < len(ts) and ts[i] == t:
        return vs[i]
    t0, t1, v0, v1 = ts[i - 1], ts[i], vs[i - 1], vs[i]
    if t1 - t0 > 2.5:
        return None
    return v0 + (v1 - v0) * (t - t0) / (t1 - t0)


def run_series(run_dir: str, t_action: float) -> dict:
    """nav error and drift-from-hold-point on the 1 s grid, t since injection."""
    with open(os.path.join(run_dir, "run_summary.json")) as fh:
        s = json.load(fh)
    target = s.get("target_uav") or "uav_0"
    t0 = _attack_ts(load_events(run_dir))
    bd = s["belief_divergence"]
    shift = bd["attack_at_wall"] - t0
    u = bd["uavs"][target]
    nts = [t + shift for t in u["t_rel_sec"]]
    nav = [_interp(nts, u["divergence_horiz_m"], t) for t in GRID]

    tr = []
    with open(os.path.join(run_dir, "trajectory.jsonl")) as fh:
        for line in fh:
            r = json.loads(line)
            if r["uav_id"] == target:
                tr.append((float(r["t_wall"]) - t0, float(r["x"]), float(r["y"])))
    tr.sort()
    tt = [p[0] for p in tr]
    hx = _interp(tt, [p[1] for p in tr], t_action)
    hy = _interp(tt, [p[2] for p in tr], t_action)
    drift = []
    for t in GRID:
        if t < t_action or hx is None:
            drift.append(None)
            continue
        x = _interp(tt, [p[1] for p in tr], t)
        y = _interp(tt, [p[2] for p in tr], t)
        drift.append(None if x is None else math.hypot(x - hx, y - hy))
    return {"nav": nav, "drift": drift}


def band(series: list) -> tuple:
    med, lo, hi = [], [], []
    for i in range(len(GRID)):
        v = sorted(s[i] for s in series if s[i] is not None)
        if len(v) < max(3, len(series) // 2):
            med.append(math.nan), lo.append(math.nan), hi.append(math.nan)
            continue
        q = statistics.quantiles(v, n=4)
        med.append(statistics.median(v)), lo.append(q[0]), hi.append(q[2])
    return med, lo, hi


def load_rows(path: str) -> list:
    with open(path) as fh:
        return [r for r in json.load(fh) if r.get("included")]


# ------------------------------------------------------------------ fig 4.3

def fig_mechanism(runs_dir: str, rows: list, outdir: str) -> None:
    panels = [
        ("gps_spoofing", "proportionate", LOITER, "-",
         "а) LOITER до стрибка оцінки", "GPS spoofing"),
        ("detector_takeout+gps_spoofing", "proportionate", LOITER, "-",
         "б) LOITER після стрибка оцінки", "Detector takeout + GPS"),
        ("gps_spoofing", "trust_aware", ZEROVEL, (0, (4, 1.5)),
         "в) утримання нульової швидкості", "GPS spoofing"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH_IN, 2.55), sharey=True)
    for ax, (att, pol, colr, ls, title, sub) in zip(axes, panels):
        sel = [r for r in rows if r["attack"] == att and r["policy"] == pol
               and r.get("t_action_s") is not None]
        ser = [run_series(os.path.join(runs_dir, r["run_id"]), r["t_action_s"])
               for r in sel]
        nm, nl, nh = band([s["nav"] for s in ser])
        dm, dl, dh = band([s["drift"] for s in ser])
        ta = statistics.median(r["t_action_s"] for r in sel)

        ax.fill_between(GRID, nl, nh, color=NAV, alpha=0.18, lw=0)
        ax.plot(GRID, nm, color=NAV, lw=1.4)
        ax.fill_between(GRID, dl, dh, color=colr, alpha=0.20, lw=0)
        ax.plot(GRID, dm, color=colr, lw=2.0, ls=ls)

        # response marker: short tick on the time axis + label
        ax.axvline(ta, color=INK_2, lw=0.7, ls=":", zorder=1)
        ax.text(ta + 1.0, 61.5, "дія\n%.1f с" % ta, fontsize=7.5, color=INK,
                va="top", ha="left", linespacing=1.0)

        # direct labels at the right end, in text ink
        end_d = next(v for v in reversed(dm) if not math.isnan(v))
        end_n = next(v for v in reversed(nm) if not math.isnan(v))
        # label value = the tabulated metric (median of per-run max drift)
        drift_metric = statistics.median(r["drift_itt_m"] for r in sel
                                         if r.get("drift_itt_m") is not None)
        ax.text(59, end_n + 2.5, "помилка навігації", fontsize=7.5,
                color=INK_2, ha="right", va="bottom")
        dy = -2.5 if abs(end_d - end_n) < 6 else 2.5
        ax.text(59, end_d + dy, "знос %.1f м" % drift_metric, fontsize=8, color=INK,
                ha="right", va="top" if dy < 0 else "bottom", fontweight="bold")

        ax.set_title("%s\n%s, n=%d" % (title, sub, len(sel)), fontsize=8,
                     loc="left", color=INK, linespacing=1.25)
        ax.set_xlim(0, 60)
        ax.set_ylim(0, 62)
        ax.set_xticks([0, 20, 40, 60])
        ax.set_yticks([0, 10, 20, 30, 40, 50, 60])
    axes[0].set_ylabel("Відстань, м")
    axes[1].set_xlabel("Час від початку атаки, с")
    fig.tight_layout(w_pad=1.2)
    _save(fig, outdir, "fig4_3_mechanism")


# ------------------------------------------------------------------ fig 4.4

def fig_h2(rows: list, outdir: str, p_holm: dict) -> None:
    arms = [("proportionate", "LOITER", LOITER, "o"),
            ("trust_aware", "нульова швидкість", ZEROVEL, "D")]
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 3.1))
    rng = random.Random(7)
    y = 0.0
    yticks, ylabels, headers = [], [], []
    for att, name in SCEN:
        headers.append((y - 0.75, name.replace("\n", " "), att))
        ys = []
        for pol, lab, colr, mk in arms:
            v = [r["drift_itt_m"] for r in rows
                 if r["attack"] == att and r["policy"] == pol
                 and r.get("drift_itt_m") is not None]
            jit = [y + rng.uniform(-0.17, 0.17) for _ in v]
            ax.scatter(v, jit, s=16, color=colr, marker=mk, alpha=0.75,
                       edgecolors="white", linewidths=0.6, zorder=3)
            m = statistics.median(v)
            ax.plot([m, m], [y - 0.32, y + 0.32], color=INK, lw=1.6, zorder=4)
            right = m > 30
            ax.text(m + (-1.2 if right else 1.2), y + 0.33,
                    "%.1f м" % m, fontsize=8, color=INK, fontweight="bold",
                    ha="right" if right else "left", va="bottom")
            yticks.append(y)
            ylabels.append("%s (n=%d)" % (lab, len(v)))
            ys.append(y)
            y += 1.0
        y += 1.0
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=7.5)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(-1, 57)
    ax.set_xticks([0, 10, 20, 30, 40, 50])
    ax.set_xlabel("Знос після реагування, м (істина Gazebo)")
    ax.axvline(50, color=NAV, lw=0.8, ls="--", zorder=1)
    ax.text(50.6, y - 0.75, "величина\nпідміни", fontsize=7, color=INK_2,
            va="bottom", ha="left", linespacing=1.0)
    for hy, name, att in headers:
        p = p_holm.get(att)
        ax.text(-0.02, hy, name, transform=ax.get_yaxis_transform(),
                fontsize=8, color=INK, ha="right", va="center",
                fontweight="bold")
        ax.text(0.0, hy, ("  p(Holm) = %s" % p) if p else "  описово, без перевірки гіпотези",
                transform=ax.get_yaxis_transform(), fontsize=7.5,
                color=INK_2, ha="left", va="center")
    ax.set_ylim(y - 0.6, -1.25)
    fig.tight_layout()
    _save(fig, outdir, "fig4_4_h2")


def _save(fig, outdir: str, name: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(outdir, "%s.%s" % (name, ext)),
                    bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  %s/%s.{png,pdf}" % (outdir, name))




# ------------------------------------------------------------------ architecture map (v1)

def _truth_xy(run_dir: str, target: str, t0: float, t_from: float, t_to: float) -> list:
    out = []
    with open(os.path.join(run_dir, "trajectory.jsonl")) as fh:
        for line in fh:
            r = json.loads(line)
            if r["uav_id"] != target:
                continue
            t = float(r["t_wall"]) - t0
            if t_from <= t <= t_to:
                out.append((t, float(r["x"]), float(r["y"])))
    out.sort()
    return out


ARCH_TITLE = {"A": "A — централізована", "B": "B — сегментована",
              "C": "C — CSMA із самовідновленням"}


def _phys_rows(path: str) -> list:
    import csv
    with open(path) as fh:
        return list(csv.DictReader(fh))


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pick_v1(rows: list, attack: str, arch: str) -> dict:
    """Run nearest to the cell median of its key physical metric."""
    rs = [r for r in rows if r["attack"] == attack and r["architecture"] == arch]
    key = ("post_response_drift_m" if attack == "gps_spoofing" and arch == "C"
           else "route_distance_m")
    rs = [dict(r, _k=_f(r[key])) for r in rs if _f(r[key]) is not None]
    m = statistics.median(r["_k"] for r in rs)
    return min(rs, key=lambda r: (abs(r["_k"] - m), r["run_id"]))


def fig_arch_map(v1_root: str, phys_csv: str, outdir: str) -> None:
    import glob
    rows = _phys_rows(phys_csv)
    dirs = {os.path.basename(d)[4:]: d
            for d in glob.glob(os.path.join(v1_root, "*", "run_*"))}
    fig, axes = plt.subplots(2, 3, figsize=(WIDTH_IN, 8.0),
                             gridspec_kw={"height_ratios": [98, 96]})
    for i, attack in enumerate(("gps_spoofing", "command_injection")):
        for j, arch in enumerate("ABC"):
            ax = axes[i][j]
            r = _pick_v1(rows, attack, arch)
            d = dirs[r["run_id"]]
            with open(os.path.join(d, "run_summary.json")) as fh:
                s = json.load(fh)
            target = s.get("target_uav") or "uav_0"
            t0 = _attack_ts(load_events(d))
            plan = s["mission_plan"]["lap_waypoints"]
            px = [w["east_m"] for w in plan] + [plan[0]["east_m"]]
            py = [w["north_m"] for w in plan] + [plan[0]["north_m"]]
            ax.plot(px, py, color=NAV, lw=0.9, ls=(0, (3, 2)), zorder=1)
            pre = _truth_xy(d, target, t0, -25.0, 0.0)
            post = _truth_xy(d, target, t0, 0.0, WINDOW_S)
            # orange = LOITER in every figure; other post-attack paths in ink
            colr = LOITER if (arch == "C" and attack == "gps_spoofing") else INK
            ax.plot([p[1] for p in pre], [p[2] for p in pre], color=NAV, lw=1.2, zorder=2)
            ax.plot([p[1] for p in post], [p[2] for p in post], color=colr,
                    lw=2.0, zorder=3)
            a, e = post[0], post[-1]
            ax.scatter([a[1]], [a[2]], s=46, facecolors="white", edgecolors=INK,
                       linewidths=1.3, zorder=5)
            ax.scatter([e[1]], [e[2]], s=30, color=INK, zorder=6)
            t_act = _f(r.get("t_first_response_s"))
            if t_act is not None:
                h = min(post, key=lambda p: abs(p[0] - t_act))
                ax.scatter([h[1]], [h[2]], s=40, marker="x", color=INK,
                           linewidths=1.5, zorder=7)

            # one quantitative label per panel, the cell's physical metric
            if attack == "gps_spoofing" and arch != "C":
                ax.annotate("", xy=(12, -50), xytext=(12, 0),
                            arrowprops=dict(arrowstyle="<->", color=INK, lw=0.9))
                ax.text(13.5, -25, "зсув\n50 м", fontsize=8.5, color=INK,
                        fontweight="bold", va="center")
                note = "атаку виявлено, реагування\nнемає: місія триває\nу зсунутих координатах"
            elif attack == "gps_spoofing":
                ax.annotate("", xy=(e[1] + 4, e[2]), xytext=(h[1] + 4, h[2]),
                            arrowprops=dict(arrowstyle="<->", color=INK, lw=0.9))
                ax.text(h[1] + 5.5, (h[2] + e[2]) / 2,
                        "знос\n%.0f м" % _f(r["post_response_drift_m"]),
                        fontsize=8.5, color=INK, fontweight="bold", va="center")
                note = "LOITER утримує оцінену\nпозицію — апарат\nзноситься"
            elif arch != "C":
                far = max(post, key=lambda p: math.hypot(p[1] - 20, p[2] - 30))
                ax.text(far[1] + 2.5, far[2], "%.0f м від\nмаршруту" % _f(r["route_distance_m"]),
                        fontsize=8.5, color=INK, fontweight="bold", va="top")
                note = "атаку виявлено, команду\nвиконано: апарат\nзалишає маршрут"
            else:
                ax.text(33, 34, "%.1f м від\nмаршруту" % _f(r["route_distance_m"]),
                        fontsize=8.5, color=INK, fontweight="bold", va="bottom",
                        ha="right")
                note = "команду відфільтровано —\nмісія триває"
            ax.text(0.03, 0.02, note, transform=ax.transAxes, fontsize=7.2,
                    color=INK_2, va="bottom", ha="left", linespacing=1.15)

            ax.set_aspect("equal")
            ax.set_xlim(-6, 44)
            ax.set_ylim(*((-62, 36) if attack == "gps_spoofing" else (-24, 72)))
            ax.set_xticks([0, 15, 30])
            if i == 0:
                ax.set_title(ARCH_TITLE[arch], fontsize=8.5, color=INK,
                             fontweight="bold", loc="left")
            if j == 0:
                ax.set_ylabel(("GPS spoofing" if attack == "gps_spoofing"
                               else "Command injection") + "\n\nПівніч, м",
                              fontsize=8.5)
            else:
                ax.set_yticklabels([])
            if i == 1 and j == 1:
                ax.set_xlabel("Схід, м")
    from matplotlib.lines import Line2D
    hnd = [Line2D([], [], color=NAV, lw=0.9, ls=(0, (3, 2))),
           Line2D([], [], color=NAV, lw=1.2),
           Line2D([], [], marker="o", ls="", mfc="white", mec=INK, ms=6),
           Line2D([], [], marker="x", ls="", color=INK, ms=6),
           Line2D([], [], marker="o", ls="", color=INK, ms=5)]
    fig.legend(hnd, ["маршрут", "до атаки", "початок атаки", "дія реагування",
                     "кінець вікна 60 с"], loc="lower center", ncol=5,
               frameon=False, fontsize=7.5, bbox_to_anchor=(0.5, 0.0),
               handlelength=1.8, columnspacing=1.2)
    fig.tight_layout(rect=(0, 0.035, 1, 1), h_pad=1.0, w_pad=0.4)
    _save(fig, outdir, "fig4_2_arch_map")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs_stage3", help="dir with stage-3 run_* folders")
    ap.add_argument("rows_json", help="runs_campaign/stage3_h2_rows.json")
    ap.add_argument("v1_root", help="dir with thesis-campaign-v1 pass folders")
    ap.add_argument("--phys", default="runs_campaign/physical_outcomes.csv")
    ap.add_argument("--outdir", default="figures")
    a = ap.parse_args(argv)
    rows = load_rows(a.rows_json)
    fig_arch_map(a.v1_root, a.phys, a.outdir)          # 4.2
    fig_mechanism(a.runs_stage3, rows, a.outdir)       # 4.3
    # p_Holm from H2_PREREGISTRATION.md "Results" (metrics/h2_analysis.py)
    fig_h2(rows, a.outdir, {"gps_spoofing": "3.7·10⁻⁶",   # 4.4
                            "monitor_takeout+gps_spoofing": "3.4·10⁻⁶"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
