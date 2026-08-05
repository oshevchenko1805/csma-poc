# Применение P1–P6 к главе 3

## 1. Артефакты и границы

- Исходник: `/Users/vsemerenska/Downloads/Thesis Draft Semerenska-5_aligned.docx`.
- SHA-256 исходника до и после работы: `8f654a994c38000692825381af4fe06910a337f1a56ecada3803e48ddb60950e` — исходник не изменён.
- Итоговая Word-копия: `/Users/vsemerenska/Downloads/Thesis Draft Semerenska-5_aligned_patched.docx`.
- Контрольная PDF: `/Users/vsemerenska/Downloads/Thesis Draft Semerenska-5_aligned_patched.pdf`.
- SHA-256 итогового DOCX: `c3967c2bcb1502547ba425eee00c0525007b4cf837aafe37e20a33fd3c7cbd5b`.
- SHA-256 контрольной PDF: `46819f9f27522b06af4fb85efc093b27458af09d2a31bfef83c3ed58928b2e0f`.
- Изменена только глава 3. Каноническое XML-содержимое до заголовка главы 3 и после её заключительного абзаца совпадает с исходником.
- В пакете DOCX изменён только `word/document.xml`; остальные 20 частей архива, включая styles, numbering, comments, relationships, embedded fonts и bibliography-related content, совпадают побайтово.
- Коммиты не создавались.

Нумерационная особенность прикреплённой копии: три attack-tree места P1, названные в плане 3.1.7.1–3.1.7.3, в Word-документе имеют номера 3.1.6.2–3.1.6.4. Привязка выполнена по точным начальным фразам recovery-абзацев; нумерация документа не изменялась.

## 2. Соответствие P1–P6 изменённым местам

| Патч | Изменённые места в Word | Что применено | Страницы контрольной PDF |
|---|---|---|---|
| P1 | 3.1.6.2 GPS spoofing; 3.1.6.3 command injection; 3.1.6.4 communication disruption; конец 3.2.6 | Разделены target architecture и PoC; зафиксированы LOITER, MAVLink sysid filter + mission resume, отсутствие recovery mapping для `heartbeat_loss`; добавлена сводная граница PoC | 52–55, 72 |
| P2 | 3.3.2–3.3.4; табл. 3.9; 3.4.6 и табл. 3.10; 3.5.2; начало 3.5.5 | A/B/C определены как bundled-конфигурации; A/B — recovery off и NoOpMesh; C — cross-check/ZeroMQ/recovery workflow; устранена component-level causal attribution | 74–76, 80–81, 84, 95–96 |
| P3 | Полная замена операциональных частей 3.4.3–3.4.5; полная замена 3.5.4 и табл. 3.14 | Введён единый contract метрик, eligibility denominators, provenance и statistical status; сохранена граница внешнего trajectory ground truth; заблокированные analyses явно исключены | 78–81, 92–95 |
| P4 | 3.4.6; абзац после табл. 3.10; методологические абзацы injection cases 4–5; итоговая comparative logic 3.5.5 | Coverage отделён от speed; coordination association не приписана отдельной action; composite cases определены как architecture-cell comparisons; общий выигрыш C не предполагается | 80–81, 88–90, 96 |
| P5 | Начало 3.5.5 | Добавлен ненумерованный блок `Статус гіпотез і statistical protocol`; H1 названа pre-specified in version history, но не pre-registered; прочие comparisons — exploratory/post hoc по указанным правилам | 95–96 |
| P6 | 3.5.2; последняя строка табл. 3.11; полная замена 3.5.6 | Loss sweep ограничен C/cross-check; A/B обозначены только как external reference; добавлены consolidated simulation, bundled-causality и generalisation limitations | 85–86, 97 |

## 3. Контроль таблиц и визуального представления

- Табл. 3.9 заменена на Word-таблицу 8×4.
- Табл. 3.10 заменена на Word-таблицу 6×4.
- В табл. 3.11 сохранена структура 11×2; заменена только строка, указанная в P6.
- Табл. 3.14 заменена на Word-таблицу 18×4.
- Подписи таблиц, стили абзацев и строк, заголовки и нумерация подразделов сохранены по шаблону исходного документа.
- Контрольный рендер содержит 102 страницы против 109 в исходнике; уменьшение вызвано консолидацией заменяемого текста. Все 102 страницы просмотрены, включая детальную проверку страниц с P1–P6 и переносов табл. 3.9, 3.10, 3.11 и 3.14. Обрезки текста, выхода за поля и повреждённых таблиц не обнаружено.

## 4. Повторная проверка 36 позиций alignment audit

| ID | Статус после P1–P6 | Краткое основание |
|---|---|---|
| A01 | соответствует | Литературная постановка главы 2 не менялась и остаётся теоретической границей. |
| A02 | осталось до финальной сборки | В 3.1.2.4 всё ещё нет явного сужения общего RF/GNSS threat model до single-UAV software injection фиксированного offset. |
| A03 | осталось до финальной сборки | Ранний переход 3.1.6 всё ещё говорит о трёх representative scenarios, хотя ниже корректно описаны пять injection cases. |
| A04 | закрыто P1 | GPS recovery ограничено LOITER и functional stabilisation; полного возврата на маршрут не заявлено. |
| A05 | закрыто P1 | Command recovery описано как bundled-конфигурация C без изолированного causal effect. |
| A06 | закрыто P1 | UDP DROP/heartbeat/isolation отделены от не реализованного connectivity recovery. |
| A07 | закрыто P1 | В 3.2.6 добавлена явная граница target architecture / PoC. |
| A08 | осталось до финальной сборки | В 3.2.3–3.2.4 и особенно в 3.5.2/табл. 3.11 сохраняется старое утверждение, что dynamic coordinator/election не реализован; оно конфликтует с deterministic `lowest-alive-sysid`. |
| A09 | закрыто P2 | A/B/C и NoOpMesh/recovery state приведены к исполняемым конфигурациям. |
| A10 | закрыто P2/P4 | Таблицы описывают mechanisms/outcomes, а не предрешённое превосходство C. |
| A11 | соответствует | Теоретические security properties сохранены как рамка, не как доказательство результата. |
| A12 | закрыто P3 | Time to Isolation, n=222/n=220 и Containment Success разведены. |
| A13 | закрыто P3 | Recovery Success, MTTR functional и Stabilisation Level определены раздельно и условно. |
| A14 | закрыто P3 | MTTD определена как conditional-on-detection median [IQR], а не mean/headline advantage. |
| A15 | закрыто P3 | Total Response Time ограничено C-runs с recovery event, n=88. |
| A16 | закрыто P4 | Additional detection coverage не превращается в claim о более раннем detection. |
| A17 | закрыто P3 | Detection Rate и conditional MTTD имеют раздельные eligibility rules. |
| A18 | закрыто P3 | FP-run prevalence разделено по clean-flight и all-valid-clean-window exposures. |
| A19 | закрыто P3 | FP blast radius заменён на exploratory FP loop depth с n=2. |
| A20 | закрыто P3 | Mission Degradation и Residual Mission Functionality получили authoritative definitions и ограничения. |
| A21 | закрыто P3 | Используются Phase Excess/Geometry Excess; full valid clean n=103 отделён от base_pass n=88. |
| A22 | закрыто P4 | Coordination trade-off не приписан отдельной recovery action. |
| A23 | закрыто P2 | Estimand сформулирован на уровне полных bundled-конфигураций. |
| A24 | закрыто P4 | Injection cases 4–5 больше не названы component-level ablations или доказательством общего causal effect. |
| A25 | закрыто P6 | Loss sweep обозначен как C-only cross-check sensitivity experiment. |
| A26 | соответствует | Различие трёх базовых и двух composite cases сохранено. |
| A27 | закрыто P3 | Зафиксированы 435 master rows, 414 valid, 309 attack, 105 clean и metric-specific denominators. |
| A28 | закрыто P3 | MTTD decomposition, R15 ablation и mesh composition явно заблокированы. |
| A29 | закрыто P3 | Mesh Cost использует fleet-level published/delivered/dropped и payload bytes; composition исключена. |
| A30 | закрыто P5 | H1/statistical family и confirmatory/exploratory status зафиксированы. |
| A31 | закрыто P4 | Comparative logic допускает null results/trade-offs и не ожидает выигрыша C по всем метрикам. |
| A32 | соответствует после P3 | External ground truth и diagnostic monitor series разведены. |
| A33 | соответствует после P3 | Введён только разрешённый corpus accounting; старое 657 отсутствует. |
| A34 | соответствует | Ссылки на старый result-figure set не добавлялись. |
| A35 | частично закрыто P6; осталось до финальной сборки | Добавлены simulation-only, 3 UAV, ZeroMQ/TCP, one fixed offset, C-only loss, bundled-causality и small-FP-case limitations. Пока не указаны точные 50 м, два high-loss уровня с n=12/wide CI и явное FP n=2 в самом limitation-блоке. |
| A36 | закрыто P3 | Sustain sensitivity добавлена с exposure 45 GPS attack-runs/105 clean и shipped k=3. |

### Итог re-audit

- Оставшихся позиций со статусом **«блокирует главу 4»**: **0**.
- Оставшихся позиций **«исправить до финальной сборки»**: **A02, A03, A08, A35**.
- Из них A35 частично закрыта P6; A02, A03 и A08 лежат вне точных заменяющих мест P1–P6 и поэтому сознательно не редактировались в этом проходе.

