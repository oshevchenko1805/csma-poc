"""
metrics/plots_tradeoff.py — рис. 4.4: розмен «стримування × координація».

Питання рисунка
---------------
Скільки коштує стримування інциденту?

Дві виміряні осі, жодної похідної величини, жодного порога, нічого
перекодованого. Усе, що можна оспорити, — це визначення метрик, а вони
захищені в розділі 3 (табл. 3.14).

Два шари
--------
Сирі прогони йдуть у фон малими напівпрозорими точками — розкид видно,
нічого не приховано. Медіани по кожній парі «сценарій × архітектура»
винесені вперед великим маркером із вусами міжквартильного розмаху. Око
читає дванадцять медіан; хмара лишається як доказ, що за ними стоять
прогони, а не одне число.

Перша версія малювала лише сирі точки. Кластери comm_disruption
розтягнуті настільки, що геометрія розмену в них тонула.

Дві речі, без яких рисунок бреше
--------------------------------
1. **Вертикаль стелі інжекції.** Кластер A і B стоїть на 49.8 м не тому,
   що там зупинилась деградація, а тому, що це вся величина
   інжектованого зміщення (`SIM_GPS_OFF_N = 50`). Без лінії рисунок
   стверджує вимірювання там, де є цензура.
2. **Підписані кути.** Без них читач бачить A і B у «хорошій» нижній
   зоні, а C — угорі, і робить висновок «C гірша». Це рівно та помилка,
   на якій рисунок першого раунду прочитався навпаки. Обидві осі — це
   ЦІНА, тому кути підписані симетрично.

Чому comm_disruption лишено
---------------------------
Усі три архітектури лягають в одну область високо по y. Це доводить, що
високе фазове розходження виникає й без будь-якої дії архітектури, і
знімає читання «меш ламає координацію».

Запуск:
    python -m metrics.plots_tradeoff runs_campaign/campaign_master.csv \
        --outdir figures
"""

from __future__ import annotations

import argparse
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from metrics.plots import load, num, flag, save  # noqa: E402
from metrics import style as S  # noqa: E402

CEILING_M = 49.84
"""Медіана відхилення у baseline при GPS-сценаріях. Дорівнює величині
інжектованого зміщення, тобто стеля експерименту, а не вимірювання."""

SCENARIOS = [
    "command_injection",
    "gps_spoofing",
    "detector_takeout+gps_spoofing",
    "monitor_takeout+gps_spoofing",
    "comm_disruption",
]

# Підписуються шість змістовних груп, а не дванадцять медіан: частина
# медіан лягає одна на одну, і це саме те, що треба показати.
# (сценарій, архітектури, текст, зсув підпису в пунктах, вирівнювання)
NOTES = [
    ("gps_spoofing", "AB", "A, B — усі GPS-сценарії\nупор у стелю інжекції",
     (-18, 30), "right"),
    ("command_injection", "AB", "A, B — command injection",
     (-16, 22), "right"),
    ("gps_spoofing", "C", "C — GPS spoofing\nі monitor takeout",
     (24, -18), "left"),
    ("detector_takeout+gps_spoofing", "C", "C — detector takeout + GPS",
     (26, 8), "left"),
    ("command_injection", "C", "C — command injection",
     (30, 6), "left"),
    ("comm_disruption", "ABC", "усі три — comm disruption\n(контроль)",
     (34, -14), "left"),
]


def _q(v: list) -> tuple:
    v = sorted(v)
    n = len(v)
    med = statistics.median(v)
    lo = statistics.median(v[: n // 2]) if n > 1 else med
    hi = statistics.median(v[(n + 1) // 2:]) if n > 1 else med
    return med, lo, hi


def collect(rows: list) -> dict:
    """{(attack, arch): {"x": [...], "y": [...]}}"""
    out = {}
    for r in rows:
        if not flag(r, "valid") or r["attack"] not in SCENARIOS:
            continue
        key = (r["attack"], r["architecture"])
        x = num(r, "mission_degradation_m")
        y = num(r, "phase_excess_m")
        if x is None or y is None:
            continue
        out.setdefault(key, {"x": [], "y": []})
        out[key]["x"].append(x)
        out[key]["y"].append(y)
    return out


def _group_median(cells: dict, attack: str, archs: str) -> tuple:
    xs, ys = [], []
    for a in archs:
        c = cells.get((attack, a))
        if c:
            xs += c["x"]
            ys += c["y"]
    return statistics.median(xs), statistics.median(ys)


def fig_tradeoff(rows: list, outdir: str) -> None:
    S.apply()
    cells = collect(rows)

    fig, ax = plt.subplots(figsize=(9.0, 6.4))
    ax.set_xlim(-4, 61)
    ax.set_ylim(-16, 200)

    # --- стеля інжекції -------------------------------------------------
    ax.axvspan(CEILING_M, 61, color=S.ACCENT, alpha=0.06, zorder=0)
    ax.axvline(CEILING_M, color=S.ACCENT, linewidth=1.3,
               linestyle=(0, (5, 3)), zorder=1)
    ax.text(CEILING_M + 3.2, 100, "стеля інжекції 50 м", color=S.ACCENT,
            fontsize=8.4, rotation=90, ha="center", va="center")

    # --- шар 1: сирі прогони -------------------------------------------
    counts = {a: 0 for a in S.ARCHS}
    for (attack, arch), c in cells.items():
        counts[arch] += len(c["x"])
        ax.scatter(c["x"], c["y"], s=13, marker=S.MARKER[arch],
                   facecolor=S.COLOR[arch], edgecolor="none",
                   alpha=0.30, zorder=2)

    # --- шар 2: медіани з IQR -------------------------------------------
    for (attack, arch), c in cells.items():
        mx, lx, hx = _q(c["x"])
        my, ly, hy = _q(c["y"])
        ax.errorbar(mx, my,
                    xerr=[[mx - lx], [hx - mx]], yerr=[[my - ly], [hy - my]],
                    fmt="none", ecolor=S.EDGE[arch], elinewidth=1.1,
                    capsize=2.5, capthick=1.1, alpha=0.9, zorder=4)
        ax.scatter([mx], [my], s=96, marker=S.MARKER[arch],
                   facecolor=S.COLOR[arch], edgecolor=S.EDGE[arch],
                   linewidth=1.1, zorder=5)

    # --- підписи груп ---------------------------------------------------
    for attack, archs, text, off, ha in NOTES:
        x, y = _group_median(cells, attack, archs)
        ax.annotate(text, xy=(x, y), xytext=off, textcoords="offset points",
                    fontsize=8.3, color="#374151", linespacing=1.45,
                    ha=ha, va="center", zorder=6,
                    arrowprops=dict(arrowstyle="-", color="#9AA3AC",
                                    linewidth=0.7, shrinkA=0, shrinkB=9))

    # --- дві дії відновлення як два переміщення -------------------------
    # Це перетворює рисунок з викладки на аргумент: та сама архітектура C
    # рухається у два різні боки залежно від того, яку дію дозволила
    # вціліла інформація.
    # Кривина навмисно мала. При rad = -0.64 дуга gps-сценарію
    # провисала до y ≈ 10 і проходила крізь кластер C command_injection,
    # через що читалася як траєкторія ПО ДАНИХ — тобто нібито фазове
    # розходження неперервно залежить від відхилення від місії. Такої
    # залежності немає: це два дискретні сценарії. Майже пряма стрілка
    # читається як звʼязка, а не як крива.
    for attack, archs, label, rad, lab_xy in [
        ("gps_spoofing", "AB", "дія: loiter\nоцінка стану\nскомпрометована",
         -0.18, (44.0, 92.0)),
        ("command_injection", "AB",
         "дія: guard(sysid) + відновлення місії\nоцінка стану ціла",
         -0.12, (19.0, 40.0)),
    ]:
        x0, y0 = _group_median(cells, attack, archs)
        x1, y1 = _group_median(cells, attack, "C")
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                    zorder=3,
                    arrowprops=dict(arrowstyle="-|>,head_width=0.22,"
                                                "head_length=0.5",
                                    color=S.MUTED, linewidth=1.0,
                                    alpha=0.65, linestyle=(0, (4, 2.5)),
                                    shrinkA=12, shrinkB=12,
                                    connectionstyle="arc3,rad=%.2f" % rad))
        ax.text(lab_xy[0], lab_xy[1], label, fontsize=7.9, style="italic",
                color=S.MUTED, ha="center", va="center", linespacing=1.5,
                zorder=6,
                bbox=dict(boxstyle="round,pad=0.32", facecolor="white",
                          edgecolor="none", alpha=0.88))

    # --- семантика кутів; обидві осі це ЦІНА ----------------------------
    ax.text(-2.6, -12.5, "обидві цілі досягнуто", fontsize=8.4,
            style="italic", color=S.MUTED, ha="left", va="center")
    ax.text(60, -12.5, "маршрут втрачено  →", fontsize=8.4, style="italic",
            color=S.MUTED, ha="right", va="center")
    ax.text(-2.6, 196, "↑  стрій втрачено", fontsize=8.4, style="italic",
            color=S.MUTED, ha="left", va="top")

    ax.set_xlabel("Відхилення від місії, м   (ціна для маршруту)")
    ax.set_ylabel("Фазове розходження, м   (ціна для строю)")
    # Заголовок навмисно НЕ каузальний. Попередній казав «розмір плати
    # задає дія відновлення, а НЕ САМА АРХІТЕКТУРА» — це сильніше за
    # дизайн: дія не варіювалась незалежно від атаки (при інʼєкції завжди
    # guard+resume, при спуфі завжди loiter), тому відокремити внесок дії
    # від внеску сценарію цей експеримент не може.
    ax.set_title("Спостережуваний розмін між стримуванням і координацією "
                 "залежить від сценарію атаки\nта застосованої дії "
                 "реагування", pad=12)
    S.despine(ax)

    handles = [Line2D([], [], linestyle="", marker=S.MARKER[a],
                      markerfacecolor=S.COLOR[a], markeredgecolor=S.EDGE[a],
                      markersize=8, label="%s (n=%d)"
                      % (S.ARCH_LABEL[a], counts[a])) for a in S.ARCHS]
    handles.append(Line2D([], [], linestyle="", marker="o",
                          markerfacecolor="#9AA3AC", markeredgecolor="none",
                          alpha=0.5, markersize=5,
                          label="окремий прогін"))
    handles.append(Line2D([], [], color="#9AA3AC", linewidth=1.1,
                          label="медіана з міжквартильним розмахом"))
    ax.legend(handles=handles, loc="upper center", ncol=3,
              bbox_to_anchor=(0.5, -0.115), columnspacing=1.8)

    ax.text(0, -0.30,
            "Чотири сценарії атак плюс контроль. Обидві осі — метри "
            "відносно передатакового рівня цього ж прогону.\n"
            "Права межа не є результатом вимірювання: 49.8 м дорівнює "
            "величині інжектованого зміщення, тому деградація у A і B "
            "цензурована зверху, а розмір ефекту для C — нижня оцінка.\n"
            "Пунктирні стрілки — концептуальні звʼязки між медіанами "
            "комірок, а не переходи по даних: дія реагування не "
            "варіювалась незалежно від сценарію атаки,\nтому відокремити "
            "внесок дії від внеску сценарію цей експеримент не дозволяє.",
            transform=ax.transAxes, fontsize=8.4, color="#1F2937",
            va="top", ha="left", linespacing=1.7)

    save(fig, outdir, "fig4_4_tradeoff")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("master", nargs="?",
                   default="runs_campaign/campaign_master.csv")
    p.add_argument("--outdir", default="figures")
    a = p.parse_args()
    fig_tradeoff(load(a.master), a.outdir)


if __name__ == "__main__":
    main()
