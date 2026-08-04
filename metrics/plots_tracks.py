"""
metrics/plots_tracks.py — рис. 4.3, треки апарата: A проти C.

Ґрунтова істина Gazebo (`trajectory.jsonl`), ланцюг подій
(`merged.jsonl`), місійний маршрут (`run_summary.json`). Три прогони,
кожен — медіанний у своїй комірці (перевірено по campaign_master.csv).

Орієнтація осей: `SIM_GPS_OFF_N` зсуває ОЦІНКУ на +50 м на північ, тому
апарат фізично йде на 50 м на південь. У даних екскурсія по `y` до
−50.1 м, отже y = північ, x = схід. Величина збігається з
`mission_degradation_m` = 49.84 м.

Канонічний вихід — `fig4_3_tracks` з драбиною подій. Драбина лишена
тому, що головне в цьому рисунку — це те, чого у A **немає**: рядок
«дія відновлення — не застосована». Без драбини відсутність хреста
читається лише тим, хто заздалегідь знає, що його треба шукати.

Варіант без драбини будується прапорцем `--no-ladder` у файл
`fig4_3_tracks_plain` і в наборі глави 4 не бере участі.

Запуск:  python -m metrics.plots_tracks
"""

from __future__ import annotations

import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from metrics.plots import save
from metrics.style import ACCENT, MUTED, apply, despine

ROOT = "figdata/runs_campaign"

TARGET = "#111827"
OTHER = "#C3C9D0"
PLAN = "#8E979F"

PANELS = [
    dict(
        run="gps_pass1/run_A_gps_spoofing_r4_1785562555",
        arch="A — централізована",
        attack="GPS spoofing",
        note="виявлено, дії не застосовано  ·  −49.8 м",
    ),
    dict(
        run="std_pass1/run_C_gps_spoofing_r3_1785309732",
        arch="C — CSMA + self-healing",
        attack="GPS spoofing",
        note="loiter: зупинився  ·  −19.7 м",
    ),
    dict(
        run="ci_pass1/run_C_command_injection_r1_1785395502",
        arch="C — CSMA + self-healing",
        attack="command injection",
        note="filter_commands: не зійшов  ·  −0.4 м",
    ),
]


# ---------------------------------------------------------------- завантаження
def load_run(rel: str) -> dict:
    d = os.path.join(ROOT, rel)
    traj: dict[str, list] = {}
    for line in open(os.path.join(d, "trajectory.jsonl")):
        r = json.loads(line)
        traj.setdefault(r["uav_id"], []).append(
            (r["t_wall"], r["x"], r["y"]))
    for u in traj:
        traj[u].sort()
    events = [json.loads(l) for l in open(os.path.join(d, "merged.jsonl"))]
    summary = json.load(open(os.path.join(d, "run_summary.json")))
    return dict(traj=traj, events=events, summary=summary,
                target=summary.get("target_uav", "uav_0"))


def plan_square(summary: dict):
    wps = (summary.get("mission_plan") or {}).get("lap_waypoints") or []
    if not wps:
        return None
    north = [w["north_m"] for w in wps]
    east = [w["east_m"] for w in wps]
    return east + [east[0]], north + [north[0]]


def milestones(events: list) -> dict:
    """inject / detect / recovery на шкалі t_wall."""
    out: dict = {}
    for e in events:
        et = e.get("event_type")
        if et == "attack" and e.get("phase") == "inject_start":
            out.setdefault("inject", e["timestamp"])
        elif et == "security":
            out.setdefault("detect", e["timestamp"])
            out.setdefault("detector", e.get("detector"))
        elif et == "isolation_announce":
            out.setdefault("isolate", e["timestamp"])
        elif et == "recovery_ack":
            out.setdefault("recovery", e["timestamp"])
            out.setdefault("action", e.get("action"))
    # підтвердження через меш, якщо воно є
    for e in events:
        if e.get("event_type") == "security" and e.get("detector") == "cross_check":
            out.setdefault("mesh", e["timestamp"])
            break
    return out


def at_time(track: list, t: float):
    """Найближча вибірка треку до моменту t."""
    arr = np.array([p[0] for p in track])
    i = int(np.argmin(np.abs(arr - t)))
    return track[i][1], track[i][2]


def ladder_lines(ms: dict) -> list[tuple[str, str]]:
    t0 = ms["inject"]
    rows = [("інʼєкція", "+0.00 с")]
    if "detect" in ms:
        rows.append((f"виявлення · {ms.get('detector', '')}",
                     "+%.2f с" % (ms["detect"] - t0)))
    if "isolate" in ms:
        rows.append(("ізоляція оголошена", "+%.2f с" % (ms["isolate"] - t0)))
    if "recovery" in ms:
        rows.append((f"дія · {ms.get('action', '')}",
                     "+%.2f с" % (ms["recovery"] - t0)))
    else:
        rows.append(("дія відновлення", "не застосована"))
    if "mesh" in ms:
        rows.append(("підтвердження через меш",
                     "+%.2f с" % (ms["mesh"] - t0)))
    return rows


# ---------------------------------------------------------------- побудова
def draw_panel(ax, spec, xlim, ylim):
    run = load_run(spec["run"])
    tgt = run["target"]

    sq = plan_square(run["summary"])
    if sq:
        ax.plot(sq[0], sq[1], color=PLAN, lw=1.0, ls=(0, (5, 3)), zorder=1)

    for uav, track in sorted(run["traj"].items()):
        if uav == tgt:
            continue
        ax.plot([p[1] for p in track], [p[2] for p in track],
                color=OTHER, lw=1.4, zorder=2, solid_capstyle="round")

    t = run["traj"][tgt]
    ax.plot([p[1] for p in t], [p[2] for p in t],
            color=TARGET, lw=1.7, zorder=4, solid_capstyle="round")

    ms = milestones(run["events"])
    if "inject" in ms:
        x, y = at_time(t, ms["inject"])
        ax.plot(x, y, "o", ms=9, mfc="white", mec=ACCENT, mew=1.9, zorder=6)
    # Коли виявлення і дія збігаються в часі (0.01 с), маркери лягають один
    # на одного. Тоді темне кільце навколо хреста читається як «обидві
    # події тут», і це чесніше, ніж зсувати маркер від його точки на треку.
    coincide = ("recovery" in ms and "detect" in ms
                and abs(ms["recovery"] - ms["detect"]) < 0.5)
    if "detect" in ms:
        x, y = at_time(t, ms["detect"])
        ax.plot(x, y, "o", ms=13 if coincide else 8,
                mfc=TARGET, mec="white", mew=1.0, zorder=6)
    if "recovery" in ms:
        x, y = at_time(t, ms["recovery"])
        ax.plot(x, y, "X", ms=8 if coincide else 11,
                mfc=ACCENT, mec="white", mew=1.0, zorder=7)

    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal", adjustable="box")
    ax.text(0.0, 1.085, spec["arch"], transform=ax.transAxes,
            fontsize=9.6, fontweight="bold", color="#111827",
            ha="left", va="bottom")
    ax.text(0.0, 1.043, spec["attack"], transform=ax.transAxes,
            fontsize=9.0, color="#374151", ha="left", va="bottom")
    ax.text(0.0, 1.005, spec["note"], transform=ax.transAxes,
            fontsize=8.4, color=MUTED, style="italic", ha="left", va="bottom")
    despine(ax)
    return ms


def legend_handles(with_recovery=True):
    h = [
        Line2D([], [], color=TARGET, lw=1.7, label="атакований апарат"),
        Line2D([], [], color=OTHER, lw=1.7, label="два інші апарати"),
        Line2D([], [], color=PLAN, lw=1.0, ls=(0, (5, 3)),
               label="місійний маршрут"),
        Line2D([], [], marker="o", ls="none", ms=8, mfc="white", mec=ACCENT,
               mew=1.9, label="інʼєкція"),
        Line2D([], [], marker="o", ls="none", ms=7.5, mfc=TARGET, mec="white",
               label="виявлення"),
    ]
    if with_recovery:
        h.append(Line2D([], [], marker="X", ls="none", ms=10, mfc=ACCENT,
                        mec="white", label="дія відновлення"))
    return h


def build(with_ladder: bool, outdir: str, name: str):
    apply()
    xlim, ylim = (-4, 42), (-56, 36)
    figsize = (13.5, 8.6) if with_ladder else (13.5, 7.2)
    fig, axes = plt.subplots(1, 3, figsize=figsize)
    fig.subplots_adjust(left=0.055, right=0.985, top=0.815,
                        bottom=0.30 if with_ladder else 0.175, wspace=0.16)

    for ax, spec in zip(axes, PANELS):
        ms = draw_panel(ax, spec, xlim, ylim)
        ax.set_xlabel("Схід, м")
        if with_ladder:
            y = -0.135
            for label, val in ladder_lines(ms):
                miss = val.startswith("не")
                col = "#8C1D18" if miss else "#374151"
                ax.text(0.0, y, label, transform=ax.transAxes, fontsize=8.0,
                        color=col, ha="left", va="top")
                ax.text(1.0, y, val, transform=ax.transAxes, fontsize=8.0,
                        color=col, ha="right", va="top",
                        fontweight="bold" if miss else "normal")
                y -= 0.052
    axes[0].set_ylabel("Північ, м")
    for ax in axes[1:]:
        ax.tick_params(labelleft=False)

    fig.legend(handles=legend_handles(), loc="lower center",
               ncol=6, bbox_to_anchor=(0.5, 0.015 if with_ladder else 0.02),
               fontsize=8.6)

    fig.suptitle("Що фізично робить відновлення: виявлення без дії, "
                 "стримування, і повне відновлення",
                 fontsize=12.6, fontweight="bold", x=0.055, ha="left", y=0.975)
    fig.text(0.055, 0.938,
             "Ґрунтова істина Gazebo, ~5 Гц. Прогони — медіанні у своїх "
             "комірках. Осі спільні: екскурсії −50, −20 і 0 м зіставні "
             "безпосередньо.",
             fontsize=8.5, color=MUTED, ha="left")
    save(fig, outdir, name)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outdir", default="figures")
    ap.add_argument("--no-ladder", action="store_true",
                    help="побудувати варіант без драбини подій")
    args = ap.parse_args()
    if args.no_ladder:
        build(False, args.outdir, "fig4_3_tracks_plain")
    else:
        build(True, args.outdir, "fig4_3_tracks")


if __name__ == "__main__":
    main()
