"""
metrics/figures_h3_map.py — рисунок офлайн-карти H3 «швидкість × σ_ГНСС»
(етап 5, крок 4; дані: h3_map.json з metrics.h3_offline_map, b = 0.2 м).

а) 1 м/с — сліпа зона детекторів v1: поріг θ(σ) з калібрування і шкода
   на момент тривоги далекомірної перевірки (медіана, p5–p95).
б) час до тривоги для чотирьох швидкостей підміни.

Шкала швидкостей — послідовна (один тон, світлота монотонна: повільніше =
темніше), перевірена validate_palette: сусідні ступені ΔE ≥ 15 (норма і
протан). Найсвітліша ступінь має низький контраст до фону, тому кожна
лінія має власний маркер і пряму підпись. ACCENT — лише поріг θ
(анотація, як «стелі» на інших рисунках).

    python3 -m metrics.figures_h3_map <h3_map.json> [outdir=figures]
"""

from __future__ import annotations

import json
import os
import sys

import matplotlib.pyplot as plt

from metrics import style
from metrics.figures_ch4_v2 import WIDTH_IN, _save

BIAS_M = 0.2
LEVELS = ("L1", "L3", "L10", "L30")
SPEED_COLOR = {"L1": "#12263C", "L3": "#2F5580", "L10": "#5C87B5", "L30": "#9DB6D2"}
SPEED_MARKER = {"L1": "o", "L3": "s", "L10": "^", "L30": "D"}
LABEL_GAP_S = 2.4          # мінімальний проміжок між прямими підписами, с


def series_from_map(res: dict, bias: float = BIAS_M) -> dict:
    """Ряди для рисунка з h3_map.json (ключі комірок 'sigma|b')."""
    cells = {}
    for key, c in res["cells"].items():
        s, b = (float(x) for x in key.split("|"))
        if abs(b - bias) < 1e-9:
            cells[s] = c
    sig = sorted(cells)
    out = {"sigma": sig,
           "theta": [cells[s]["calibration"]["theta_m"] for s in sig],
           "harm_L1": [(cells[s]["levels"]["L1"]["harm_at_alarm_m"]["median"],
                        cells[s]["levels"]["L1"]["harm_at_alarm_m"]["p5"],
                        cells[s]["levels"]["L1"]["harm_at_alarm_m"]["p95"]) for s in sig],
           "t_rng": {lv: [cells[s]["levels"][lv]["t_rng_s"]["median"] for s in sig]
                     for lv in LEVELS},
           "detect": min(cells[s]["levels"][lv]["peer_detect_share"]
                         for s in sig for lv in LEVELS),
           "false_alarms": sum(cells[s]["false_alarms"]["alarms"] for s in sig)}
    return out


def spread_labels(ys: list, gap: float) -> list:
    """Розсунути підписи по y, щоб між сусідніми було не менше gap."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    placed = [0.0] * len(ys)
    last = None
    for i in order:
        y = ys[i] if last is None else max(ys[i], last + gap)
        placed[i] = y
        last = y
    return placed


def fig_h3_map(res: dict, outdir: str, name: str = "fig_h3_map") -> dict:
    style.apply()
    d = series_from_map(res)
    sig = d["sigma"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(WIDTH_IN, 3.0))

    # а) поріг і шкода при 1 м/с
    med = [h[0] for h in d["harm_L1"]]
    lo = [h[0] - h[1] for h in d["harm_L1"]]
    hi = [h[2] - h[0] for h in d["harm_L1"]]
    ax1.plot(sig, d["theta"], color=style.ACCENT, lw=1.4, ls="--", marker="o",
             ms=4, zorder=3)
    ax1.errorbar(sig, med, yerr=[lo, hi], color=SPEED_COLOR["L1"], lw=2.0,
                 marker="o", ms=6, mec="white", mew=1.0, capsize=3, elinewidth=1.0,
                 zorder=4)
    ax1.text(sig[-1] + 0.12, med[-1], "шкода\n(p5–p95)", fontsize=8, va="center",
             color=SPEED_COLOR["L1"])
    ax1.text(sig[-1] + 0.12, d["theta"][-1], "поріг θ", fontsize=8, va="center",
             color=style.ACCENT)
    ax1.text(0.02, 0.97, "детектори v1: тривоги немає за 120 с",
             transform=ax1.transAxes, fontsize=8, color=style.MUTED, va="top")
    ax1.set_title("а) підміна 1 м/с (сліпа зона v1)", loc="left")
    ax1.set_xlabel("Похибка ГНСС σ (на вісь), м")
    ax1.set_ylabel("Відстань, м")
    ax1.set_ylim(0, 34)

    # б) час до тривоги
    ends = []
    for lv in LEVELS:
        ax2.plot(sig, d["t_rng"][lv], color=SPEED_COLOR[lv], lw=2.0,
                 marker=SPEED_MARKER[lv], ms=5.5, mec=style.EDGE["C"] if lv == "L30" else "white",
                 mew=0.8, zorder=3)
        ends.append(d["t_rng"][lv][-1])
    for lv, y in zip(LEVELS, spread_labels(ends, LABEL_GAP_S)):
        v0 = res["cells"][next(iter(res["cells"]))]["levels"][lv]["v0_mps"]
        ax2.text(sig[-1] + 0.12, y, f"{v0:g} м/с", fontsize=8, va="center",
                 color="#1F2937")
    ax2.set_title("б) час до тривоги (медіана)", loc="left")
    ax2.set_xlabel("Похибка ГНСС σ (на вісь), м")
    ax2.set_ylabel("Час від початку атаки, с")
    ax2.set_ylim(0, 48)
    ax2.set_xlim(-0.15, sig[-1] + 0.75)
    ax2.text(0.02, 0.97,
             f"виявлено {d['detect'] * 100:.0f} % за 120 с; хибних тривог {d['false_alarms']}",
             transform=ax2.transAxes, fontsize=8, color=style.MUTED, va="top")
    for ax in (ax1, ax2):
        ax.set_xticks(sig)
        ax.set_xticklabels([f"{s:g}" for s in sig])
        style.despine(ax)
    ax1.set_xlim(-0.15, sig[-1] + 0.75)
    fig.tight_layout(w_pad=2.0)
    _save(fig, outdir, name)
    return d


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    with open(argv[0]) as fh:
        res = json.load(fh)
    fig_h3_map(res, argv[1] if len(argv) > 1 else "figures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
