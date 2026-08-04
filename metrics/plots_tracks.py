"""
metrics/plots_tracks.py — рис. 4.3, фізичні наслідки двох атак у трьох
архітектурних конфігураціях. Сітка 2 × 3.

Чому сітка, а не три панелі поспіль
-----------------------------------
Попередня версія ставила поруч A/GPS, C/GPS і C/injection і читалась як
драбина «виявлення без дії → стримування → повне відновлення». Драбини
немає: між першою і третьою панеллю одночасно змінювались атака,
механізм виявлення і дія відновлення, тому це були три різні
експерименти, а не три щаблі однієї шкали.

Тепер **у межах ряду змінюється тільки архітектура**:

    верхній ряд   GPS spoofing        A | B | C
    нижній ряд    command injection   A | B | C

Осі
---
Спільні **в межах ряду**, не на весь рисунок. GPS зносить апарат на
південь (y до −50 м), інʼєкція — на північ (y до +68 м); спільна на всі
шість вісь дала б розмах 126 м при 41 м по x, тобто панелі втричі вищі
за ширину і 40 % порожнечі в кожному ряду. Наукового висновку це не
додає: зіставляти треба A з B з C у межах однієї атаки, а між рядами
змінюється сама атака. Масштаб по x і y всередині панелі однаковий
завжди, інакше квадрат маршруту перестав би бути квадратом.

Діапазони оголошуються в підписі — інакше різні вікна між рядами
виглядають як маніпуляція.

Вибір прогонів
--------------
Правило виконуване, а не записане: у кожній комірці
`architecture × attack` береться прогін, найближчий до медіани
`mission_degradation_m`, з детермінованим тайбрейком по `run_id`. Якщо
мастер-файл зміниться, вибір поїде за ним або впаде з поясненням, які
саме прогони треба довезти з VM.

Запуск:  python -m metrics.plots_tracks
"""

from __future__ import annotations

import glob
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from metrics.plots import load, valid_rows, num, save
from metrics.style import ACCENT, MUTED, apply, despine

FIGDATA = "figdata/runs_campaign"
MASTER = "runs_campaign/campaign_master.csv"

TARGET = "#111827"
OTHER = "#C3C9D0"
PLAN = "#8E979F"

ARCHS = ["A", "B", "C"]
ARCH_LABEL = {
    "A": "A — централізована",
    "B": "B — сегментована",
    "C": "C — CSMA + self-healing",
}

# (атака, підпис ряду, межі y, підписи панелей за архітектурою)
ROWS = [
    dict(
        attack="gps_spoofing",
        label="GPS spoofing",
        ylim=(-54.0, 34.0),
        notes={
            "A": "атаку виявлено, коригувальну дію не застосовано;\n"
                 "відхилення досягло межі інжектованого зміщення",
            "B": "атаку виявлено, коригувальну дію не застосовано;\n"
                 "відхилення досягло межі інжектованого зміщення",
            "C": "стримування через loiter",
        },
    ),
    dict(
        attack="command_injection",
        label="command injection",
        ylim=(-4.0, 72.0),
        notes={
            "A": "атаку виявлено, стабілізація не настала\n"
                 "протягом вікна спостереження",
            "B": "атаку виявлено, стабілізація не настала\n"
                 "протягом вікна спостереження",
            "C": "блокування команди, місійний маршрут збережено",
        },
    ),
]
XLIM = (-3.0, 43.0)


# ------------------------------------------------------------- вибір прогонів
def select_runs(master: str = MASTER) -> dict:
    """(arch, attack) -> (run_id, mission_degradation_m).

    Найближчий до медіани комірки; тайбрейк по `run_id`, щоб вибір
    відтворювався побайтово.
    """
    rows = valid_rows(load(master))
    out = {}
    for row in ROWS:
        attack = row["attack"]
        for arch in ARCHS:
            sel = [(r["run_id"], num(r, "mission_degradation_m"))
                   for r in rows
                   if r["attack"] == attack and r["architecture"] == arch]
            sel = [(rid, d) for rid, d in sel if d is not None]
            if not sel:
                continue
            vals = sorted(d for _, d in sel)
            n = len(vals)
            med = (vals[n // 2] if n % 2
                   else (vals[n // 2 - 1] + vals[n // 2]) / 2.0)
            rid, dev = min(sel, key=lambda p: (abs(p[1] - med), p[0]))
            out[(arch, attack)] = (rid, dev)
    return out


def run_dir(run_id: str) -> str:
    hits = glob.glob(os.path.join(FIGDATA, "*", "run_" + run_id))
    if not hits:
        raise SystemExit(
            "немає даних треку для %s.\n"
            "Довезти з VM:\n"
            "  cd ~/csma_poc_v2 && d=$(find runs_campaign -maxdepth 2 "
            "-type d -name 'run_%s')\n"
            "  mkdir -p figdata && tar czf - $d/trajectory.jsonl "
            "$d/run_summary.json $d/merged.jsonl | tar xzf - -C figdata"
            % (run_id, run_id))
    return hits[0]


# ---------------------------------------------------------------- завантаження
def load_run(rid: str) -> dict:
    d = run_dir(rid)
    traj: dict[str, list] = {}
    for line in open(os.path.join(d, "trajectory.jsonl")):
        r = json.loads(line)
        traj.setdefault(r["uav_id"], []).append((r["t_wall"], r["x"], r["y"]))
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


def milestones(events: list, target: str) -> dict:
    """inject / detect / recovery, з тим самим гейтом, що й `detected`:
    подія після інʼєкції і про атакований борт."""
    out: dict = {}
    t0 = None
    for e in events:
        if (e.get("event_type") == "attack"
                and e.get("phase") == "inject_start"):
            t0 = float(e["timestamp"])
            out["inject"] = t0
            break
    if t0 is None:
        return out
    for e in events:
        ts = float(e["timestamp"])
        if ts < t0 or e.get("target_uav") not in (None, target):
            continue
        et = e.get("event_type")
        if et == "security":
            out.setdefault("detect", ts)
        elif et == "recovery_ack":
            out.setdefault("recovery", ts)
            out.setdefault("action", e.get("action"))
    return out


def at_time(track: list, t: float):
    arr = np.array([p[0] for p in track])
    i = int(np.argmin(np.abs(arr - t)))
    return track[i][1], track[i][2]


# -------------------------------------------------------------------- панель
def draw_panel(ax, rid: str, dev: float, ylim, note: str):
    run = load_run(rid)
    tgt = run["target"]

    sq = plan_square(run["summary"])
    if sq:
        ax.plot(sq[0], sq[1], color=PLAN, lw=1.0, ls=(0, (5, 3)), zorder=1)

    for uav, track in sorted(run["traj"].items()):
        if uav == tgt:
            continue
        ax.plot([p[1] for p in track], [p[2] for p in track],
                color=OTHER, lw=1.3, zorder=2, solid_capstyle="round")

    t = run["traj"][tgt]
    ax.plot([p[1] for p in t], [p[2] for p in t],
            color=TARGET, lw=1.6, zorder=4, solid_capstyle="round")

    ms = milestones(run["events"], tgt)
    # Виявлення і дія розділені сотими долями секунди, тому лягають в
    # одну точку треку. Темне кільце навколо хреста чесніше, ніж рознести
    # маркери штучно.
    coincide = ("recovery" in ms and "detect" in ms
                and abs(ms["recovery"] - ms["detect"]) < 0.5)
    if "inject" in ms:
        x, y = at_time(t, ms["inject"])
        ax.plot(x, y, "o", ms=8, mfc="white", mec=ACCENT, mew=1.8, zorder=6)
    if "detect" in ms:
        x, y = at_time(t, ms["detect"])
        ax.plot(x, y, "o", ms=12 if coincide else 7,
                mfc=TARGET, mec="white", mew=1.0, zorder=6)
    if "recovery" in ms:
        x, y = at_time(t, ms["recovery"])
        ax.plot(x, y, "X", ms=8 if coincide else 10,
                mfc=ACCENT, mec="white", mew=1.0, zorder=7)

    ax.set_xlim(*XLIM)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal", adjustable="box")
    despine(ax)
    return dev, note


def legend_handles():
    return [
        Line2D([], [], color=TARGET, lw=1.6, label="атакований апарат"),
        Line2D([], [], color=OTHER, lw=1.6, label="два інші апарати"),
        Line2D([], [], color=PLAN, lw=1.0, ls=(0, (5, 3)),
               label="місійний маршрут"),
        Line2D([], [], marker="o", ls="none", ms=8, mfc="white", mec=ACCENT,
               mew=1.8, label="інʼєкція"),
        Line2D([], [], marker="o", ls="none", ms=7, mfc=TARGET, mec="white",
               label="виявлення"),
        Line2D([], [], marker="X", ls="none", ms=9, mfc=ACCENT, mec="white",
               label="дія відновлення"),
    ]


def build(outdir: str = "figures", name: str = "fig4_3_tracks"):
    apply()
    picks = select_runs()

    spans = [r["ylim"][1] - r["ylim"][0] for r in ROWS]
    fig, axes = plt.subplots(2, 3, figsize=(12.6, 14.0),
                             gridspec_kw={"height_ratios": spans})
    fig.subplots_adjust(left=0.105, right=0.985, top=0.900, bottom=0.235,
                        wspace=0.10, hspace=0.40)

    for i, row in enumerate(ROWS):
        for j, arch in enumerate(ARCHS):
            ax = axes[i][j]
            rid, dev = picks[(arch, row["attack"])]
            draw_panel(ax, rid, dev, row["ylim"], row["notes"][arch])
            ax.set_xlabel("Схід, м", labelpad=2)
            if j == 0:
                ax.set_ylabel("Північ, м")
            else:
                ax.tick_params(labelleft=False)

    # Позиції підписів беремо з РЕАЛЬНИХ боксів осей, а не з відносних
    # координат панелі. При aspect="equal" matplotlib стискає бокс під
    # квадратний масштаб, і два ряди різної висоти дають різну абсолютну
    # відстань для того самого відносного зсуву — через це підписи
    # налазили одна на одну.
    fig.canvas.draw()
    for i, row in enumerate(ROWS):
        boxes = [axes[i][j].get_position() for j in range(len(ARCHS))]
        for j, arch in enumerate(ARCHS):
            _, dev = picks[(arch, row["attack"])]
            b = boxes[j]
            cx = b.x0 + b.width / 2.0
            if i == 0:
                fig.text(cx, b.y1 + 0.008, ARCH_LABEL[arch], fontsize=10.5,
                         fontweight="bold", ha="center", va="bottom",
                         color="#111827")
            fig.text(cx, b.y0 - 0.032, "відхилення від місії %.1f м" % dev,
                     fontsize=9.0, fontweight="bold", ha="center", va="top",
                     color="#111827")
            fig.text(cx, b.y0 - 0.049, row["notes"][arch], fontsize=8.2,
                     ha="center", va="top", color=MUTED, linespacing=1.6)

        fig.text(boxes[0].x0 - 0.072,
                 (boxes[0].y0 + boxes[0].y1) / 2.0,
                 "%s\ny ∈ [%+.0f; %+.0f] м"
                 % (row["label"], row["ylim"][0], row["ylim"][1]),
                 fontsize=10.5, fontweight="bold", rotation=90,
                 ha="center", va="center", color="#111827", linespacing=1.9)

    fig.legend(handles=legend_handles(), loc="lower center", ncol=6,
               bbox_to_anchor=(0.5, 0.092), fontsize=8.8)

    fig.suptitle("Фізичні наслідки GPS spoofing та command injection "
                 "у трьох архітектурних конфігураціях",
                 fontsize=12.8, fontweight="bold", x=0.075, ha="left",
                 y=0.972)
    fig.text(0.075, 0.940,
             "Ґрунтова істина Gazebo, ~5 Гц. У кожній комірці показано "
             "прогін, найближчий до медіани відхилення від місії "
             "в цій комірці.",
             fontsize=8.6, color=MUTED, ha="left")

    fig.text(0.075, 0.055,
             "У межах кожного ряду використано спільні осі; між рядами "
             "масштаби можуть відрізнятися, оскільки порівнюються різні "
             "типи атак. Масштаб по x і y всередині\n"
             "кожної панелі однаковий. Прогони не є парними реалізаціями "
             "зі спільним seed, тому рисунок ілюструє механізм, а не "
             "доводить причинність. MTTD між рядами\nне зіставляється.",
             fontsize=8.2, color=MUTED, ha="left", va="top", linespacing=1.7)

    save(fig, outdir, name)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outdir", default="figures")
    args = ap.parse_args()
    build(args.outdir)


if __name__ == "__main__":
    main()
