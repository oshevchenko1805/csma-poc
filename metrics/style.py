"""
metrics/style.py — єдина палітра і типографіка для рисунків розділу 4.

Принцип, який замінює стару схему «сірий плюс штриховка»
--------------------------------------------------------
Штриховка була милицею для випадку, коли заливки не різняться за
світлотою. Якщо світлота різна, штриховка стає шумом і робить рисунок
каламутним. Тому тут кольори підібрані так, щоб різнитися **за
світлотою**, а не лише за тоном:

    A  #BFC9D2   L* ~ 79   світлий холодний сірий
    B  #79899A   L* ~ 55   середній сланцевий
    C  #1B3B5F   L* ~ 24   глибокий темно-синій

У чорно-білому друку це 0.79 / 0.55 / 0.24 — розділення більше, ніж дає
будь-яка штриховка. На екрані виглядає сучасно.

Акцентний теплий колір (`ACCENT`) зарезервований **виключно для
анотацій**: лінії стелі, підписи кутів, робочі точки. Він ніколи не
кодує архітектуру, тому не конкурує з основною шкалою.

Безпечно для дальтонізму: немає пари червоний-зелений, і навіть при
повній втраті кольору три рівні світлоти лишаються різними.
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ARCHS = ["A", "B", "C"]

COLOR = {"A": "#BFC9D2", "B": "#79899A", "C": "#1B3B5F"}
EDGE = {"A": "#8895A3", "B": "#4E5C69", "C": "#12263C"}
MARKER = {"A": "o", "B": "s", "C": "^"}

ARCH_LABEL = {
    "A": "A — централізована",
    "B": "B — сегментована",
    "C": "C — CSMA + self-healing",
}

ACCENT = "#C1651B"
"""Теплий акцент. Тільки анотації: стелі, робочі точки, підписи кутів."""

MUTED = "#6B7280"
"""Нейтральний для пояснювального тексту на полі рисунка."""

GRID = "#D8DDE2"

ATTACK_LABEL = {
    "none": "без атаки",
    "gps_spoofing": "GPS spoofing",
    "comm_disruption": "comm disruption",
    "command_injection": "command injection",
    "detector_takeout+gps_spoofing": "detector takeout + GPS",
    "monitor_takeout+gps_spoofing": "monitor takeout + GPS",
}


def apply() -> None:
    """Викликати один раз на початку модуля побудови."""
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9.5,
        "axes.edgecolor": "#9AA3AC",
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.7,
        "grid.linestyle": "-",
        "grid.alpha": 1.0,
        "xtick.color": "#4B5563",
        "ytick.color": "#4B5563",
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "legend.frameon": False,
        "legend.fontsize": 8.5,
        "figure.dpi": 110,
        "savefig.facecolor": "white",
    })


def despine(ax, keep=("left", "bottom")) -> None:
    for name, sp in ax.spines.items():
        sp.set_visible(name in keep)
