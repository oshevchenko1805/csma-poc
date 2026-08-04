"""
metrics/figures_ch4.py — єдина точка входу для набору рисунків розділу 4.

Одна команда збирає рівно пʼять рисунків і нічого більше:

    python -m metrics.figures_ch4

| рисунок | що відповідає | джерело даних |
|---|---|---|
| `fig4_1_losssweep` | межа застосовності детекції через меш | `runs_final/detection_vs_loss.csv` |
| `fig4_2_sustain`   | плато правила підтвердження k          | `campaign_master.csv` + збережені ряди |
| `fig4_3_tracks`    | що фізично робить відновлення          | `figdata/` — три медіанні прогони |
| `fig4_4_tradeoff`  | розмен стримування × координація       | `campaign_master.csv` |
| `fig4_5_regimes`   | карта режимів 5 × 3, синтез            | `campaign_master.csv` |

Нумерація — за `FIGURE_SPECS.md`, тобто за порядком появи в тексті
розділу, який побудований за пʼятьма security properties:
Q1 detection дає 4.1 і 4.2, Q3 recovery дає 4.3, Q4 і Q5 разом дають
4.4, синтез дає 4.5. Розбіжна нумерація в
`CH45_QUESTIONS_ANSWERS_FIGURES.md` (де карта режимів була 4.1)
вважається застарілою.

Чому саме пʼять, а не чотирнадцять: матеріал для рисунка це залежність
від параметра, розподіл або фізика. Матриця 5 × 3, у якій одинадцять
комірок із пʼятнадцяти збігаються, — це таблиця, і розділ 3 це прямо
дозволяє («відсутність відмінності є самостійним висновком»). Перелік
того, що лишається таблицями, — у кінці `FIGURE_SPECS.md`.

**Рисунки це шар відображення, а не шар зберігання.** Видалення всієї
теки `figures/` не втрачає нічого: усе перебудовується цією командою.
"""

from __future__ import annotations

import argparse

from metrics.plots import load, valid_rows, fig_sustain
from metrics.plots_extra import fig_loss_sweep
from metrics.plots_regime import fig_regime_map
from metrics.plots_tradeoff import fig_tradeoff
from metrics.plots_tracks import build as build_tracks

MASTER = "runs_campaign/campaign_master.csv"
LOSS_CSV = "runs_final/detection_vs_loss.csv"


def main() -> None:
    ap = argparse.ArgumentParser(description="Набір рисунків розділу 4.")
    ap.add_argument("--master", default=MASTER)
    ap.add_argument("--loss-csv", default=LOSS_CSV)
    ap.add_argument("--outdir", default="figures")
    args = ap.parse_args()

    rows = valid_rows(load(args.master))
    print("валідних прогонів: %d" % len(rows))
    print("пишемо в %s/" % args.outdir)

    fig_loss_sweep(args.loss_csv, args.outdir)          # 4.1
    fig_sustain(rows, args.outdir)                      # 4.2
    build_tracks(True, args.outdir, "fig4_3_tracks")    # 4.3
    fig_tradeoff(rows, args.outdir)                     # 4.4
    fig_regime_map(rows, args.outdir)                   # 4.5

    print("готово: пʼять рисунків, PNG 300 dpi і PDF-вектор")


if __name__ == "__main__":
    main()
