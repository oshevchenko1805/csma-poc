"""
metrics/plots_regime.py — рис. 1: карта режимів 5 × 3.

Навіщо окремий тип рисунка
--------------------------
Сім попередніх рисунків кодували в комірці СКАЛЯР. Матриця 5 атак × 3
архітектури має 11-12 однакових комірок із 15, тому однакові скаляри
давали однакові стовпчики і рисунок чесно показував порожнечу.

Однаковість комірок — це і є результат. Дані структуровані не за
метриками, а за тим, ЯКИЙ ШАР системи скомпрометувала атака. Тут у
комірці кодується не скаляр, а КЛАС ІСХОДУ — порядкова величина. Повтори
складаються у блоки одного тону, і рисунок показує візерунок, а не
п'ятнадцять однакових висот.

Класи (порядкові, від гіршого до кращого)
-----------------------------------------
0  не виявлено
1  виявлено, деградацію не зупинено
2  часткове стримування
3  стримано, координацію втрачено
4  відновлено повністю

Пороги — не підібрані під результат
-----------------------------------
DETECT_MIN = 0.5      комірка рахується як «виявлено»
ON_PLAN_M  = 15.0     ON_PLAN_TOLERANCE_M із metrics/derived.py, той самий
                      поріг, за яким апарат рахується таким, що зійшов із
                      маршруту; застосовано і до відхилення, і до фази
PARTIAL    = 0.5      частка від найгіршої медіани в рядку, нижче якої
                      стримування рахується частковим

Джерело: runs_campaign/campaign_master.csv, valid == True. Більше нічого.

Запуск:
    python -m metrics.plots_regime runs_campaign/campaign_master.csv \
        --outdir figures
"""

from __future__ import annotations

import argparse
import os
import statistics
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from metrics.plots import (  # noqa: E402
    load, num, flag, save, valid_rows, ARCHS,
)

# --- пороги ------------------------------------------------------------

DETECT_MIN = 0.5
ON_PLAN_M = 15.0
PARTIAL_FRACTION = 0.5

# --- класи -------------------------------------------------------------

CLASS_LABEL = [
    "0 — не виявлено",
    "1 — виявлено, деградацію не зупинено",
    "2 — часткове стримування",
    "3 — стримано, координацію втрачено",
    "4 — відновлено повністю",
]
CLASS_FILL = ["0.30", "0.50", "0.68", "0.84", "0.97"]
CLASS_TEXT = ["white", "white", "black", "black", "black"]

# --- рядки, згруповані за режимом --------------------------------------

ROWS = [
    ("detector_takeout+gps_spoofing", "detector takeout + GPS"),
    ("monitor_takeout+gps_spoofing", "monitor takeout + GPS"),
    ("command_injection", "command injection"),
    ("gps_spoofing", "GPS spoofing"),
    ("comm_disruption", "comm disruption"),
]

REGIMES = [
    (0, 2, "I\nатака на плоскість\nбезпеки"),
    (2, 3, "II\nатака на\nкомандний канал"),
    (3, 4, "III\nатака на оцінку\nстану"),
    (4, 5, "IV\nконтроль:\nпоза плоскістю"),
]

ARCH_LABEL = ["A\nцентралізована", "B\nсегментована", "C\nCSMA + self-healing"]


# --- зведення по комірці -----------------------------------------------


def _m(v: float) -> str:
    """Один знак під 10 м, цілі вище: 0.2 не має ставати 0."""
    return "%.1f" % v if v < 10 else "%.0f" % v


def cell_stats(rows: list, attack: str, arch: str) -> dict:
    sel = [r for r in rows
           if r["attack"] == attack and r["architecture"] == arch
           and flag(r, "valid")]
    n = len(sel)
    det = [r for r in sel if flag(r, "detected")]
    degr = [num(r, "mission_degradation_m") for r in sel]
    degr = [v for v in degr if v is not None]
    phase = [num(r, "phase_excess_m") for r in sel]
    phase = [v for v in phase if v is not None]
    return {
        "n": n,
        "det_k": len(det),
        "det_rate": len(det) / n if n else 0.0,
        "degr": statistics.median(degr) if degr else None,
        "phase": statistics.median(phase) if phase else None,
    }


def classify(c: dict, degr_reference: float) -> int:
    """Порядковий клас ісходу. Читається згори вниз, перший збіг виграє."""
    if c["det_rate"] < DETECT_MIN:
        return 0
    d = c["degr"]
    if d is not None and d >= ON_PLAN_M:
        # деградація не зупинена; часткова вона чи ні — вирішує те,
        # наскільки вона нижча за найгіршу медіану цього ж рядка
        if degr_reference and d < PARTIAL_FRACTION * degr_reference:
            return 2
        return 1
    p = c["phase"]
    if p is not None and p >= ON_PLAN_M:
        return 3
    return 4


# --- рисунок -----------------------------------------------------------


def fig_regime_map(rows: list, outdir: str) -> None:
    grid = []
    for attack, _ in ROWS:
        cells = [cell_stats(rows, attack, a) for a in ARCHS]
        ref = max([c["degr"] for c in cells if c["degr"] is not None] or [0.0])
        grid.append([(c, classify(c, ref)) for c in cells])

    nr, nc = len(ROWS), len(ARCHS)
    fig, ax = plt.subplots(figsize=(8.4, 8.0))
    ax.set_xlim(0, nc)
    ax.set_ylim(0, nr)
    ax.invert_yaxis()
    ax.set_axisbelow(True)
    ax.grid(False)

    for i in range(nr):
        for j in range(nc):
            c, k = grid[i][j]
            ax.add_patch(plt.Rectangle((j, i), 1, 1, facecolor=CLASS_FILL[k],
                                       edgecolor="black", linewidth=0.8))
            tc = CLASS_TEXT[k]
            ax.text(j + 0.5, i + 0.22, str(k), ha="center", va="center",
                    fontsize=17, fontweight="bold", color=tc)
            lines = ["виявл. %d/%d" % (c["det_k"], c["n"])]
            if c["degr"] is not None:
                lines.append("відх. %s м" % _m(c["degr"]))
            if c["phase"] is not None:
                lines.append("фаза %s м" % _m(c["phase"]))
            ax.text(j + 0.5, i + 0.63, "\n".join(lines), ha="center",
                    va="center", fontsize=8.2, color=tc, linespacing=1.5)

    ax.set_xticks([j + 0.5 for j in range(nc)])
    ax.set_xticklabels(ARCH_LABEL, fontsize=9)
    ax.xaxis.set_ticks_position("top")
    ax.tick_params(axis="x", length=0, pad=6)
    ax.set_yticks([i + 0.5 for i in range(nr)])
    ax.set_yticklabels([lab for _, lab in ROWS], fontsize=9)
    ax.tick_params(axis="y", length=0)
    for s in ax.spines.values():
        s.set_visible(False)

    # дужки режимів праворуч
    for a, b, lab in REGIMES:
        ax.plot([nc + 0.06, nc + 0.14, nc + 0.14, nc + 0.06],
                [a + 0.06, a + 0.06, b - 0.06, b - 0.06],
                color="0.35", linewidth=1.0, clip_on=False)
        ax.text(nc + 0.20, (a + b) / 2, lab, fontsize=8.2, color="0.2",
                va="center", ha="left", linespacing=1.45, clip_on=False)

    ax.set_title("Ефективність відновлення обмежена тим, чи вціліла "
                 "інформація, на яку відновлення спирається",
                 fontsize=10, pad=34)

    handles = [Patch(facecolor=CLASS_FILL[k], edgecolor="black",
                     linewidth=0.8, label=CLASS_LABEL[k]) for k in range(5)]
    ax.legend(handles=handles, fontsize=8.2, frameon=False, ncol=2,
              loc="upper center", bbox_to_anchor=(0.5, -0.015),
              handlelength=1.6, columnspacing=1.4, labelspacing=0.5)

    ax.text(0.5, -0.145,
            "Пороги: виявлення < 0.5 — клас 0; відхилення від місії та "
            "фазове розходження — 15 м (ON_PLAN_TOLERANCE_M);\nчасткове "
            "стримування — нижче половини найгіршої медіани рядка. "
            "Числа в комірці — медіани валідних прогонів.\n"
            "Відхилення 50 м у A і B при GPS-сценаріях дорівнює величині "
            "інжектованого зміщення, тобто впирається у стелю експерименту, "
            "а не вимірює деградацію.",
            transform=ax.transAxes, ha="center", va="top", fontsize=7.6,
            color="0.25", linespacing=1.6)

    save(fig, outdir, "fig4_5_regimes")


def regime_table(rows: list) -> str:
    """Таблиця 5 × 3 — те, чим став рис. 4.5 після рецензії.

    Чому таблиця, а не рисунок
    --------------------------
    Рисунок кодував у комірці порядковий клас 0…4. Три заперечення, які
    він не пережив:

    1. **Порядок вигаданий.** «Часткова втрата маршруту» і «маршрут
       збережено, стрій втрачено» — різні властивості, а не сусідні
       щаблі. Світлотна шкала стверджує впорядкованість, якої немає.
    2. **Клас «відновлено повністю» не спирався на відновлення.**
       `classify()` читає детекцію, деградацію і фазу, і жодного разу —
       `degradation_stopped`. Але й додати її не можна: вона розрізняє
       архітектури лише в одному рядку з пʼяти, а в решті висока у A і B
       через насичення спуфу на 50 м, а не через дію архітектури. Тобто
       **неконфаундленої покомірочної міри відновлення в даних немає.**
    3. **Дужки режимів назначені за підписом рядка**, тобто за тим, який
       шар атаковано — це вхідні дані, а не вимір. Рисунок показував, що
       вони узгоджуються з класами, які я ж і задав порогами.

    З чотирьох величин, які могла б нести комірка, три потребують
    застереження: деградація 49.8 м цензурована стелею інжекції,
    відновлення змішує дію з насиченням, фаза змінює знак між режимами.
    Застереження несе таблиця зі виносками. Кольорова шкала — ні.

    Таблиця ГЕНЕРУЄТЬСЯ з мастер-файла, а не набирається. Це єдиний
    спосіб не дати їй розʼїхатись із даними, як уже сталося з R13 і R14.

        python -m metrics.plots_regime --table
    """
    out = [
        "| режим | атака | A | B | C |",
        "|---|---|---|---|---|",
    ]
    regime_of = {}
    for a, b, lab in REGIMES:
        name = lab.split("\n")[0] + " " + " ".join(lab.split("\n")[1:])
        for i in range(a, b):
            regime_of[i] = name

    for i, (attack, label) in enumerate(ROWS):
        cells = [cell_stats(rows, attack, arch) for arch in ARCHS]
        # У таблиці один знак після коми скрізь: `_m()` округлює 49.84 до
        # «50», а виноска говорить про 49.8 м як про стелю інжекції, і
        # читач має бачити те саме число в обох місцях.
        vals = []
        for c in cells:
            vals.append("%d/%d · %s · %s" % (
                c["det_k"], c["n"],
                "—" if c["degr"] is None else "%.1f м" % c["degr"],
                "—" if c["phase"] is None else "%.1f м" % c["phase"]))
        out.append("| %s | %s | %s |"
                   % (regime_of.get(i, ""), label, " | ".join(vals)))

    out += [
        "",
        "У комірці: **виявлення · відхилення від місії · фазове "
        "розходження**. Відхилення і фаза — медіани валідних прогонів.",
        "",
        "Застереження, без яких рядки читаються неправильно:",
        "",
        "1. **49.8 м у A і B в GPS-сценаріях — це стеля інжекції**, тобто "
        "величина внесеного зміщення, а не виміряна деградація. Число "
        "цензуроване зверху; розміру ефекту для C воно дає нижню оцінку.",
        "2. **Фаза у C висока там, де дія відновлення паркує апарат.** "
        "Два сусідні борти продовжують маршрут, атакований стоїть — "
        "звідси 145…173 м. Це ціна стримування, а не втрата керованості; "
        "рядок `comm disruption` показує 107…117 м в усіх трьох, тобто "
        "високе розходження буває і без будь-якої дії архітектури.",
        "3. **`0/28` — це 0.00 [0.00, 0.12] за Вілсоном, а не «ніколи».** "
        "Правило про інтервал діє симетрично для нуля і для одиниці.",
        "4. **Відновлення в цю таблицю не винесено навмисно.** "
        "`degradation_stopped` високий у A і B в GPS-сценаріях тому, що "
        "рампа спуфу насичується на 50 м, а не тому, що архітектура "
        "спрацювала. Механізм різний, величина одна, тому в клітинку "
        "поруч із рештою її ставити не можна. Відновлення відчитується "
        "окремою таблицею з розкладанням на дію та насичення.",
    ]
    return "\n".join(out)


def sensitivity(rows: list, thresholds=(10.0, 15.0, 20.0)) -> list:
    """Чи тримається картина при інших порогах «на плані».

    Класифікація спирається на один поріг, `ON_PLAN_M`. Якщо картина
    розсипається при його зсуві, вона є артефактом порога, а не
    результатом. Друкує сітку класів для кожного порога і позначає
    рядки, де вона змінилася.

    Викликається окремо, у набір рисунків не входить: це один абзац
    тексту, а не рисунок.
    """
    global ON_PLAN_M
    saved = ON_PLAN_M
    attacks = [a for a, _ in ROWS]
    grids = {}
    try:
        for t in thresholds:
            ON_PLAN_M = t
            g = []
            for at in attacks:
                cells = [cell_stats(rows, at, a) for a in ARCHS]
                ref = max([c["degr"] for c in cells
                           if c["degr"] is not None] or [0.0])
                g.append([classify(c, ref) for c in cells])
            grids[t] = g
    finally:
        ON_PLAN_M = saved

    changed = []
    head = "  ".join("%.0f м" % t for t in thresholds)
    print("поріг «на плані»:".ljust(32), head)
    for i, at in enumerate(attacks):
        cols = [" ".join(str(v) for v in grids[t][i]) for t in thresholds]
        same = len(set(cols)) == 1
        if not same:
            changed.append(at)
        print(at.ljust(32), " | ".join(c.center(5) for c in cols),
              "" if same else "  <- змінилася")
    print("\nрядків змінилося: %d з %d" % (len(changed), len(attacks)))
    return changed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("master", nargs="?",
                   default="runs_campaign/campaign_master.csv")
    p.add_argument("--outdir", default="figures")
    p.add_argument("--sensitivity", action="store_true",
                   help="надрукувати перевірку стійкості порога, "
                        "рисунок не будувати")
    p.add_argument("--table", action="store_true",
                   help="надрукувати таблицю 5x3 у markdown (це і є чинна "
                        "форма подання; рисунок з набору вилучено)")
    p.add_argument("--figure", action="store_true",
                   help="все одно побудувати забракований рисунок")
    a = p.parse_args()
    rows = load(a.master)
    if a.sensitivity:
        sensitivity(valid_rows(rows))
    elif a.figure:
        fig_regime_map(rows, a.outdir)
    else:
        print(regime_table(valid_rows(rows)))


if __name__ == "__main__":
    main()
