# CH3 final fix log

Дата: 2026-08-05

## Обсяг проходу

- Вхідний документ: `Thesis Draft Semerenska-6_ch3_final_candidate.docx`.
- Вихідний документ: `Thesis Draft Semerenska-7_ch3_frozen_candidate.docx`.
- Контрольна PDF: `Thesis Draft Semerenska-7_ch3_frozen_candidate.pdf`.
- Змінено лише главу 3; code, CSV, frozen results і глави поза главою 3 не змінювалися.
- Commit не створювався.

## Закриття blocker B01

1. У §3.5.2 додано єдиний experimental timing: attack injection на `t = 90 s`, fixed post-attack observation window `60 s`, завершення run на `t = 150 s`.
2. У табл. 3.11 після рядка `Спільні умови порівняння` додано рядок `Experimental timing` з тим самим fixed contract і metric-specific denominator guardrail.
3. У загальному абзаці §3.5.3 recovery, containment і stabilisation визначено як outcomes, що спостерігаються та обчислюються всередині fixed window і не завершують його.
4. В усіх п’яти injection cases вилучено outcome-dependent або неявне stopping language та вставлено однаковий fixed-window contract.
5. Збережено правило: єдине time window не означає єдиного знаменника; eligibility filters і denominators визначаються окремо за §3.5.4.

Точні фінальні абзаци і вилучені stopping clauses наведено в `CH3_5_3_FIXED_WINDOW_PARAGRAPHS.md`.

## Minor corrections

| Місце | Зміна |
|---|---|
| §3.2.1 | `формальними security properties` → `операціоналізованими security properties` |
| §3.5.1 | `formal properties` → `операціоналізовані security properties` |
| p. 24 source layout | Закрито citation: `Kumar et al., 2024).` |
| Початок глави 3 | Додано перевірений parent heading `3.1. Моделювання простору загроз для multi-UAV систем` |
| §3.1.5 | Додано `3.1.5.2. Ідентифіковані сценарії загроз` без перенумерації 3.1.5.3–3.1.5.5 |
| §3.1.3.5 | Виправлено внутрішнє посилання на класи противників: `3.1.1` → `3.1.2` |
| Заголовки глави 3 | Уніфіковано крапку після номера; зміст і номери не зсувалися |
| Табл. 3.4 і 3.5 | Додано пропущену крапку після номера caption |
| Табл. 3.14 | Ширини колонок змінено з `[1150, 3000, 2450, 2420]` на `[1750, 2750, 2300, 2220]` DXA; загальна ширина `9020` DXA, структура 18 × 4 і текст метрик збережені |

## Hierarchy and internal-reference check

- У DOCX немає Word bookmarks, internal hyperlink anchors або `REF` fields, які потребували б оновлення.
- Після вставлення 3.1 і 3.1.5.2 downstream numbering не змінювався.
- Перевірено всі явні prose references на 3.1.x; виправлено лише фактично помилкове посилання в §3.1.3.5.
- Фінальна послідовність: 3.1 → 3.1.1–3.1.6; усередині 3.1.5 наявні 3.1.5.1–3.1.5.5 без пропусків.

## Structural verification

- Input SHA-256: `6009baa63efd0311b520625251aa56c28c51f6f1c9ef5ee856ea0627160c0c1c`.
- Output DOCX SHA-256: `044f1cf77e1d5ea9073bccb86012d6a18847e8bf4cd957feb6b192906ef02460`.
- Control PDF SHA-256: `f03c57626e1952abfb86c15e6077cf0507910bd68aedeb8b2389539206cd9241`.
- DOCX ZIP integrity: pass.
- Єдина змінена package part: `word/document.xml`.
- XML blocks до початку глави 3 та від `REFERENCES` до кінця документа: canonical-equivalent.
- Word-таблиці: 16. Табл. 3.11 стала 12 × 2 через обов’язковий timing row. Табл. 3.14 залишилася 18 × 4. Усі інші table shapes і весь інший table text не змінені.
- Загальний table count: 16; rows: 123; cells: 475.
- Hyperlinks: 48; pictures: 5; comment ranges/references: 3/3/3; counts preserved.
- Tracked insertions/deletions: 0/0.

## Render verification

- Контрольна PDF: 102 physical pages.
- Глава 3: pp. 15–97; `REFERENCES` починається на p. 98.
- Візуально перевірено всі 102 rendered pages.
- Окремо перевірено: нові headings, citation p. 24, табл. 3.11 і §3.5.2–3.5.3 на pp. 83–89, табл. 3.14 на pp. 92–94.
- Clipping, overlap, missing glyphs, broken rows або пошкоджені page breaks не виявлено.
- Перерозподіл ширини табл. 3.14 усунув внутрислівні переноси назв метрик у першій колонці та скоротив таблицю на одну PDF-сторінку без зміни metric contract.
- Наявний червоний diagram placeholder на pp. 36–38 не змінювався і не враховувався як новий дефект.

## Final status

Blocker B01 технічно закрито. Після render verification роботу з документом зупинено; commit не створено.
