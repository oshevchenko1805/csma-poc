"""
metrics/plots_idiom_sheet.py — лист порівняння ідіом.

НЕ рисунок для дисертації. Це інструмент вибору: ті самі дані
(`mission_degradation_m`) відрисовані в чотирьох конвенційних формах
поруч, плюс дві форми, які працюють лише для параметричних даних.

Мета: вибрати форму поглядом, а не ще одним раундом переробок.

Запуск:  python -m metrics.plots_idiom_sheet
Вихід:   figures/idiom_sheet.png
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from metrics.style import (
    ARCHS, COLOR, EDGE, MARKER, ACCENT, MUTED, apply, despine,
)

MASTER = "runs_campaign/campaign_master.csv"
SWEEP = "runs_final/detection_vs_loss.csv"
OUT = "figures/idiom_sheet.png"

ATTACKS = [
    "detector_takeout+gps_spoofing",
    "monitor_takeout+gps_spoofing",
    "command_injection",
    "gps_spoofing",
    "comm_disruption",
]
SHORT = {
    "detector_takeout+gps_spoofing": "det.takeout\n+GPS",
    "monitor_takeout+gps_spoofing": "mon.takeout\n+GPS",
    "command_injection": "command\ninjection",
    "gps_spoofing": "GPS\nspoofing",
    "comm_disruption": "comm\ndisruption",
}
CEILING = 49.84  # величина інжектованого зміщення


def load():
    v = pd.read_csv(MASTER).query("valid == True")
    return v[v.attack != "none"].copy()


def verdict(ax, text, ok):
    mark = "працює" if ok else "не працює"
    col = "#1B5E20" if ok else "#8C1D18"
    ax.text(0.0, -0.34, f"[{mark}]  {text}", transform=ax.transAxes,
            fontsize=8.0, color=col, va="top", ha="left")


# --------------------------------------------------------------------------
def panel_bars(ax, v):
    """1. Стовпчики з розмахом — форма, відхилена тричі."""
    w, x = 0.26, np.arange(len(ATTACKS))
    for i, a in enumerate(ARCHS):
        med, lo, hi = [], [], []
        for at in ATTACKS:
            s = v[(v.architecture == a) & (v.attack == at)].mission_degradation_m
            m = s.median()
            med.append(m)
            lo.append(m - s.quantile(0.25))
            hi.append(s.quantile(0.75) - m)
        ax.bar(x + (i - 1) * w, med, w, yerr=[lo, hi], capsize=2,
               color=COLOR[a], edgecolor=EDGE[a], linewidth=0.8,
               error_kw=dict(elinewidth=0.8, ecolor="#4B5563"), label=a)
    ax.axhline(CEILING, color=ACCENT, ls="--", lw=1.1)
    ax.text(4.4, CEILING + 1.5, "стеля інжекції", color=ACCENT, fontsize=7.5,
            ha="right")
    ax.set_xticks(x)
    ax.set_xticklabels([SHORT[a] for a in ATTACKS], fontsize=7.2)
    ax.set_ylabel("Відхилення від місії, м")
    ax.set_title("1.  Стовпчики з розмахом", loc="left", fontweight="bold")
    despine(ax)
    verdict(ax, "A і B дають однакові стовпчики в усіх пʼяти клітинках;\n"
                "без лінії стелі 49.8 м читається як вимірювання. "
                "Форма, відхилена тричі.", False)


def panel_box(ax, v):
    """2. Боксплот по атаках × архітектурах."""
    w, x = 0.26, np.arange(len(ATTACKS))
    for i, a in enumerate(ARCHS):
        data = [v[(v.architecture == a) & (v.attack == at)]
                .mission_degradation_m.dropna().values for at in ATTACKS]
        bp = ax.boxplot(data, positions=x + (i - 1) * w, widths=w * 0.85,
                        patch_artist=True, showfliers=True,
                        flierprops=dict(marker=".", markersize=2.5,
                                        markerfacecolor=MUTED,
                                        markeredgecolor="none"),
                        medianprops=dict(color="#111827", lw=1.2),
                        whiskerprops=dict(lw=0.8, color=EDGE[a]),
                        capprops=dict(lw=0.8, color=EDGE[a]))
        for b in bp["boxes"]:
            b.set(facecolor=COLOR[a], edgecolor=EDGE[a], linewidth=0.8)
    ax.axhline(CEILING, color=ACCENT, ls="--", lw=1.1)
    ax.set_xticks(x)
    ax.set_xticklabels([SHORT[a] for a in ATTACKS], fontsize=7.2)
    ax.set_xlim(-0.6, len(ATTACKS) - 0.4)
    ax.set_ylabel("Відхилення від місії, м")
    ax.set_title("2.  Боксплот", loc="left", fontweight="bold")
    despine(ax)
    verdict(ax, "видно, що у A і B розкиду немає взагалі — вони впираються\n"
                "у стелю. Стовпчики цього не показували. Конвенційна форма.", True)


def panel_ecdf(ax, v):
    """3. ECDF — розподіл по всіх атакуючих прогонах."""
    for a in ARCHS:
        s = np.sort(v[v.architecture == a].mission_degradation_m.dropna().values)
        y = np.arange(1, len(s) + 1) / len(s)
        ax.step(np.concatenate([[0], s]), np.concatenate([[0], y]),
                where="post", color=COLOR[a] if a != "A" else EDGE[a],
                lw=2.0, label=f"{a}  (n={len(s)})")
    ax.axvline(CEILING, color=ACCENT, ls="--", lw=1.1)
    ax.text(CEILING - 1.5, 0.10, "стеля інжекції", color=ACCENT, fontsize=7.5,
            rotation=90, ha="right", va="bottom")
    ax.set_xlabel("Відхилення від місії, м")
    ax.set_ylabel("Частка прогонів ≤ x")
    ax.set_ylim(0, 1.02)
    ax.legend(loc="lower right")
    ax.set_title("3.  ECDF (накопичений розподіл)", loc="left",
                 fontweight="bold")
    despine(ax)
    verdict(ax, "одна панель на всю кампанію: у C половина прогонів нижче 20 м,\n"
                "у A і B 70 % сидять на стелі. Але сценарії злиті в купу.", True)


def panel_strip(ax, v):
    """4. Кожен прогін — точка, з медіанами."""
    rng = np.random.default_rng(7)
    w, x = 0.26, np.arange(len(ATTACKS))
    for i, a in enumerate(ARCHS):
        for j, at in enumerate(ATTACKS):
            s = v[(v.architecture == a) & (v.attack == at)] \
                .mission_degradation_m.dropna().values
            if not len(s):
                continue
            px = x[j] + (i - 1) * w + rng.uniform(-0.075, 0.075, len(s))
            ax.scatter(px, s, s=9, marker=MARKER[a],
                       facecolor=COLOR[a], edgecolor=EDGE[a],
                       linewidth=0.4, alpha=0.75, zorder=2)
            ax.plot([x[j] + (i - 1) * w - 0.11, x[j] + (i - 1) * w + 0.11],
                    [np.median(s)] * 2, color="#111827", lw=1.6, zorder=3)
    ax.axhline(CEILING, color=ACCENT, ls="--", lw=1.1)
    ax.set_xticks(x)
    ax.set_xticklabels([SHORT[a] for a in ATTACKS], fontsize=7.2)
    ax.set_xlim(-0.6, len(ATTACKS) - 0.4)
    ax.set_ylabel("Відхилення від місії, м")
    ax.set_title("4.  Точковий рій (кожен прогін)", loc="left",
                 fontweight="bold")
    despine(ax)
    verdict(ax, "показує n і форму розподілу одночасно; видно поодинокі\n"
                "викиди. Найчесніша форма, але щільна при 414 прогонах.", True)


def panel_sweep(ax):
    """5. Свип по параметру — інші дані, параметрична залежність."""
    s = pd.read_csv(SWEEP)
    ax.fill_between(s.loss_prob, s.ci_low, s.ci_high, color=COLOR["C"],
                    alpha=0.16, linewidth=0)
    ax.plot(s.loss_prob, s.detection_rate, marker="^", ms=5,
            color=COLOR["C"], lw=1.8, label="C  (меш)")
    ax.axhline(0, color=EDGE["A"], lw=1.8, ls="-")
    ax.text(0.33, 0.035, "A і B ≈ 0 на всіх рівнях", color=EDGE["A"],
            fontsize=7.8)
    for _, r in s.iterrows():
        ax.annotate(f"{int(r.n)}", (r.loss_prob, r.detection_rate),
                    textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=6.4, color=MUTED)
    ax.set_xlabel("Імовірність втрати пакета меша")
    ax.set_ylabel("Частка виявлення")
    ax.set_ylim(-0.06, 1.12)
    ax.legend(loc="upper right")
    ax.set_title("5.  Свип по параметру з інтервалами", loc="left",
                 fontweight="bold")
    despine(ax)
    verdict(ax, "форма, для якої тут узагалі є матеріал: залежність від\n"
                "параметра. Читається миттєво. Цю ідіому нікому не забракували.", True)


def panel_matrix(ax, v):
    """6. Теплова матриця 5 × 3."""
    M = np.zeros((len(ATTACKS), 3))
    for i, at in enumerate(ATTACKS):
        for j, a in enumerate(ARCHS):
            M[i, j] = v[(v.architecture == a) & (v.attack == at)] \
                .mission_degradation_m.median()
    ax.imshow(M, cmap="Greys", vmin=0, vmax=CEILING, aspect="auto")
    for i in range(len(ATTACKS)):
        for j in range(3):
            ax.text(j, i, f"{M[i, j]:.1f}", ha="center", va="center",
                    fontsize=10, fontweight="bold",
                    color="white" if M[i, j] > CEILING * 0.55 else "#111827")
    ax.set_xticks(range(3))
    ax.set_xticklabels(ARCHS, fontsize=10)
    ax.set_yticks(range(len(ATTACKS)))
    ax.set_yticklabels([SHORT[a].replace("\n", " ") for a in ATTACKS],
                       fontsize=7.6)
    ax.grid(False)
    ax.set_title("6.  Теплова матриця (медіани, м)", loc="left",
                 fontweight="bold")
    verdict(ax, "візерунок замість значень: два темні стовпці й один світлий.\n"
                "Розкид втрачено повністю — але тут він і не потрібен.", True)


def main():
    apply()
    v = load()
    fig, axes = plt.subplots(3, 2, figsize=(15.5, 17.5))
    fig.subplots_adjust(hspace=0.62, wspace=0.24,
                        top=0.925, bottom=0.125, left=0.075, right=0.975)

    panel_bars(axes[0, 0], v)
    panel_box(axes[0, 1], v)
    panel_ecdf(axes[1, 0], v)
    panel_strip(axes[1, 1], v)
    panel_sweep(axes[2, 0])
    panel_matrix(axes[2, 1], v)

    fig.suptitle(
        "Ті самі дані в шести конвенційних формах — вибір ідіоми, не рисунок "
        "для дисертації",
        fontsize=13.5, fontweight="bold", y=0.975)
    fig.text(0.075, 0.947,
             "Панелі 1–4 і 6: відхилення від місії, 379 валідних атакуючих "
             "прогонів з campaign_master.csv. Панель 5: свип по втратах, "
             "255 прогонів з detection_vs_loss.csv.",
             fontsize=8.6, color=MUTED, ha="left")
    fig.text(0.075, 0.022,
             "Не показано, бо немає даних у маковському клоні: трек у площині "
             "north-east і часовий ряд відхилення (потрібні trajectory.jsonl з VM). "
             "Це дві найконвенційніші ідіоми жанру.",
             fontsize=8.6, color=ACCENT, ha="left")

    fig.savefig(OUT, dpi=170, facecolor="white")
    print("saved", OUT)


if __name__ == "__main__":
    main()
