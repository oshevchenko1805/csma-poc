# Финальное независимое regression review главы 3

**Объект:** `Thesis Draft Semerenska-7_ch3_frozen_candidate.docx`  
**Контрольный PDF:** `Thesis Draft Semerenska-7_ch3_frozen_candidate.pdf`  
**Базовые DOCX для regression comparison:** `Thesis Draft Semerenska-6_ch3_final_candidate.docx`, `Thesis Draft Semerenska-5_aligned.docx`  
**Дата проверки:** 2026-08-05  
**Режим:** независимая проверка без редактирования DOCX/PDF и без коммита

## 1. Итоговый вердикт

**Готова: blocker B01 закрыт, новых blockers не выявлено.**

Во всех пяти injection cases зафиксирован единый заранее заданный experimental timing: attack injection на `t = 90 s`, fixed post-attack observation window длительностью `60 s`, завершение run на `t = 150 s`. Recovery, containment и stabilisation во всех пяти случаях являются outcomes внутри этого окна и не определяют момент завершения запуска.

§3.5.2, табл. 3.11, §3.5.3, табл. 3.14 и табл. 3.15 согласованы. Metric-specific eligibility filters и denominators сохранены. Остаточные замечания предыдущего независимого ревью по formal-properties terminology, citation punctuation, иерархии нумерации и переносам табл. 3.14 исправлены. Регрессий по A01–A36 и R1–R9 не обнаружено.

## 2. Контрольные основания и идентификация файлов

Проверка выполнена по следующим материалам:

- `CH3_FINAL_INDEPENDENT_REVIEW.md`;
- `CH3_FINAL_FIX_LOG.md`;
- `CH3_5_3_FIXED_WINDOW_PARAGRAPHS.md`;
- `CH3_SEMANTIC_CONSERVATION_AUDIT.md`;
- `FINAL_RESULTS_AUDIT.md`;
- frozen protocol и repository state в commit `7451258c152409775896faa52e57b6b8d75c076b`;
- актуальный DOCX и соответствующий контрольный PDF;
- `-6_ch3_final_candidate` как непосредственная regression baseline и `-5_aligned` как внешний content-boundary control.

Контрольные SHA-256:

| Артефакт | SHA-256 |
|---|---|
| `Thesis Draft Semerenska-7_ch3_frozen_candidate.docx` | `044f1cf77e1d5ea9073bccb86012d6a18847e8bf4cd957feb6b192906ef02460` |
| `Thesis Draft Semerenska-7_ch3_frozen_candidate.pdf` | `f03c57626e1952abfb86c15e6077cf0507910bd68aedeb8b2389539206cd9241` |
| `Thesis Draft Semerenska-6_ch3_final_candidate.docx` | `6009baa63efd0311b520625251aa56c28c51f6f1c9ef5ee856ea0627160c0c1c` |
| `Thesis Draft Semerenska-5_aligned.docx` | `8f654a994c38000692825381af4fe06910a337f1a56ecada3803e48ddb60950e` |

Хэши актуальных DOCX/PDF совпадают с `CH3_FINAL_FIX_LOG.md`. ZIP integrity актуального DOCX: pass. Контрольный PDF содержит 102 physical pages; глава 3 занимает pp. 15–97, `REFERENCES` начинается на p. 98.

Frozen protocol проверен непосредственно в commit `7451258`:

- `scripts/run_batch.py`: campaign defaults `--attack-at-sec = 90.0` и `--observation-after-attack-sec = 60.0`;
- `configs/experiment.yaml`: `observation_after_attack_sec: 60.0` и прямое указание, что observation заканчивается на `t = 150 s`;
- `runners/experiment.py`: runner ждёт `_attack_at`, выполняет injection, затем без outcome-dependent branch ждёт полный `_obs_after` и только после этого ставит end-of-run marker.

Следовательно, fixed contract `90 + 60 = 150 s` подтверждён не только контрольными заметками, но и замороженной исполняемой конфигурацией.

## 3. Regression scope и узость изменений

Сравнение `-6 → -7` показало:

- набор файлов внутри DOCX package не изменился;
- единственная изменённая package part — `word/document.xml`;
- tracked insertions/deletions: `0/0`;
- число нативных Word-таблиц сохранилось: `16`;
- табл. 3.11 изменилась с `11 × 2` на `12 × 2` только за счёт добавления строки `Experimental timing`;
- текст всех прежних строк табл. 3.11 сохранён;
- табл. 3.14 осталась `18 × 4`, весь cell text посимвольно совпадает с `-6`; изменена только геометрия колонок;
- табл. 3.15 осталась `8 × 2`, весь cell text посимвольно совпадает с `-6`;
- hyperlinks: `48`; comment ranges/end/references: `3/3/3`; эти структуры сохранены;
- вне главы 3 текстовые body blocks до заголовка главы 3 и от `REFERENCES` до конца совпадают с `-5_aligned`.

Полный paragraph-level diff `-6 → -7` не выявил необъявленных содержательных изменений. Изменения ограничены:

1. fixed-window correction B01;
2. добавлением parent heading `3.1` и missing heading `3.1.5.2`;
3. унификацией точек после номеров headings/captions;
4. исправлением внутренней ссылки `3.1.1 → 3.1.2`;
5. закрытием citation parenthesis;
6. заменой двух stale formal-properties formulations;
7. добавлением timing row в табл. 3.11;
8. перераспределением ширины колонок табл. 3.14 без изменения metric contract.

## 4. Проверка blocker B01 по пяти injection cases

| Injection case | Attack time | Fixed window | Run end | Recovery/containment/stabilisation как stopping condition | Статус |
|---|---:|---:|---:|---|---|
| 1. SITL position manipulation / GPS spoofing approximation | `t = 90 s` | `60 s`, до `t = 150 s` | `t = 150 s` | прямо исключены как условие окончания | pass |
| 2. MAVLink command injection / waypoint override | `t = 90 s` | `60 s`, до `t = 150 s` | `t = 150 s` | прямо исключены как условие окончания | pass |
| 3. Network-layer communication disruption | `t = 90 s` | `60 s`, до `t = 150 s` | `t = 150 s` | прямо исключены как условие окончания | pass |
| 4. Detector takeout + position manipulation | `t = 90 s` | `60 s`, до `t = 150 s` | `t = 150 s` | прямо исключены как условие окончания | pass |
| 5. Monitor takeout + position manipulation | `t = 90 s` | `60 s`, до `t = 150 s` | `t = 150 s` | прямо исключены как условие окончания | pass |

По полному тексту главы дополнительно выполнен negative search. Не найдены прежние outcome-dependent clauses:

- `до моменту відновлення ... або до завершення запуску`;
- `до досягнення нового стабільного стану`;
- `до відновлення допустимого communication state`;
- эквивалентные конструкции, связывающие конец observation window с recovery или stabilisation.

Единственное условие окончания run в методологическом contract — заранее заданное `t = 150 s`.

**Вывод по B01:** закрыт полностью.

## 5. Согласованность §3.5.2, табл. 3.11, §3.5.3, табл. 3.14 и табл. 3.15

| Место | Проверенное содержание | Согласованность |
|---|---|---|
| §3.5.2, p. 83 | `t = 90 s`, `60 s` post-attack, run end `t = 150 s`; единое окно не создаёт единый denominator | pass |
| Табл. 3.11, pp. 84–85 | отдельная строка `Experimental timing` повторяет `90/60/150`, outcomes inside window и metric-specific denominators | pass |
| §3.5.3, pp. 85–89 | общий timing paragraph и все пять cases используют один fixed contract; stopping language отсутствует | pass |
| Табл. 3.14, pp. 92–94 | eligibility/denominator задаётся отдельно для каждой метрики; Recovery Success привязан к концу fixed observation window | pass |
| Табл. 3.15, p. 96 | закрепляет единое observation window и отдельные eligibility filters/denominators | pass |

Табл. 3.15 не повторяет числа `90/60/150`, но не вводит альтернативного окна: её строка `Observation window` является логическим summary точного contract, уже однозначно заданного в §3.5.2, табл. 3.11 и §3.5.3. Противоречия или двусмысленного второго правила нет.

## 6. Metric-specific eligibility filters и denominators

Текст табл. 3.14 не изменён относительно `-6` и согласуется с frozen `FINAL_RESULTS_AUDIT.md`:

| Метрика/группа | Сохранённый eligibility rule | Статус |
|---|---|---|
| Detection Rate | все valid attack-runs соответствующей cell | pass |
| MTTD | только detected attack-runs | pass |
| Time to Isolation | valid attack-runs с attributed detection и non-null `isolation_announce`; clean FP rows исключены | pass |
| Containment Success | valid attack-runs с наблюдением non-target UAV | pass |
| Recovery Success | все valid attack-runs | pass |
| MTTR functional | только runs с найденным финальным стабильным segment | pass |
| Stabilisation Level | только stabilized runs | pass |
| Mission Degradation | все valid attack-runs | pass |
| Residual Mission Functionality | runs с пригодными trajectory series | pass |
| Phase/Geometry Excess | valid attack-runs; valid clean-runs только как отдельный reference corpus | pass |
| Total Response Time | только C-runs с recovery event | pass |
| FP clean flights | все valid clean flights соответствующей architecture | pass |
| FP all valid clean windows | отдельная mixed-window exposure; не объединяется с clean-flight denominator | pass |
| FP loop depth | positive FP cases; exploratory case analysis | pass |
| Mesh Cost | valid runs соответствующей architecture | pass |
| Sustain sensitivity | valid GPS attack-runs и valid clean flights | pass |

В главу 3 не вернулись realized corpus sizes и conditional factual `n`, кроме разрешённых limitation values `n=12` и `n=2`. Не найдены старые/заблокированные числа и claims: `657`, `36.65/1.34`, `39,198/486`, `902 ± 52`, MTTD decomposition, policy ablation и mesh message-type composition.

## 7. Проверка исправления minor issues

| Предыдущее замечание | Результат проверки | Статус |
|---|---|---|
| Stale `формальними security properties` / `formal properties` | точных остаточных употреблений: `0`; заменены на operationalized terminology | closed |
| Citation punctuation на прежней p. 24 | фрагмент теперь заканчивается `Kumar et al., 2024).`; в главе 3 нет paragraphs/table cells с несбалансированными круглыми скобками | closed |
| Отсутствующий parent `3.1` | heading присутствует на p. 15 | closed |
| Пропуск `3.1.5.2` | присутствует `3.1.5.2. Ідентифіковані сценарії загроз` | closed |
| Непоследовательные точки после номеров | у всех 59 распознанных numbered headings главы 3 точка после номера присутствует | closed |
| Иерархия нумерации | duplicates: `0`; missing parents: `0`; gaps: `0`; ветка `3.1.5.1–3.1.5.5` непрерывна | closed |
| Неверная prose reference на классы противников | ссылка исправлена на §3.1.2 и указывает на существующий раздел | closed |
| Внутрисловные переносы названий в табл. 3.14 | grid изменён с `[1150, 3000, 2450, 2420]` на `[1750, 2750, 2300, 2220]` DXA; названия метрик не разрываются внутри слов | closed |

## 8. Regression matrix A01–A36

| ID | Краткий invariant | Результат в `-7` |
|---|---|---|
| A01 | gap/target architecture не выдаётся за полную PoC validation | pass, без регрессии |
| A02 | broad RF/GNSS threat model отделена от single-UAV 50 m software injection | pass, без регрессии |
| A03 | три базовых класса связаны с пятью injection cases | pass, без регрессии |
| A04 | GPS outcome не назван полным recovery | pass, без регрессии |
| A05 | command recovery описан узко, без component causal claim | pass, без регрессии |
| A06 | comm disruption не получает несуществующий recovery/rerouting | pass, без регрессии |
| A07 | target self-healing cycle отделён от PoC subset | pass, без регрессии |
| A08 | coordinator = deterministic `lowest-alive-sysid`, не consensus | pass, без регрессии |
| A09 | A/B/C, NoOpMesh и recovery states описаны фактически | pass, без регрессии |
| A10 | mechanism tables не предрешают победу C | pass, без регрессии |
| A11 | security properties = operational framework, не absolute security | pass, без регрессии |
| A12 | isolation event/Time to Isolation/Containment разведены | pass, без регрессии |
| A13 | Recovery Success/MTTR/Stabilisation не означают full recovery | pass; B01 дополнительно закрыт |
| A14 | Total Response Time не стал универсальной A/B/C metric | pass, без регрессии |
| A15 | MTTD conditional-on-detection, median [IQR] + n | pass, без регрессии |
| A16 | detection coverage не подменяется speed | pass, без регрессии |
| A17 | FP prevalence разделена по exposure | pass, без регрессии |
| A18 | FP blast radius не используется как рабочая метрика; сохранён loop depth | pass, без регрессии |
| A19 | Residual Mission Functionality не означает mission completion | pass, без регрессии |
| A20 | Mission Degradation использует 30 s pre-attack median baseline | pass, без регрессии |
| A21 | Phase/Geometry Excess и clean references разведены | pass, без регрессии |
| A22 | coordination trade-off не приписан одной recovery action | pass, без регрессии |
| A23 | A/B/C остаются bundled configurations | pass, без регрессии |
| A24 | composite cases не превращены в component ablation | pass, без регрессии |
| A25 | loss sweep остаётся C/cross-check only | pass, без регрессии |
| A26 | taxonomy `3 basic + 2 composite` сохранена | pass, без регрессии |
| A27 | metric-specific eligibility/denominators сохранены | pass; fixed window не создаёт общий denominator |
| A28 | blocked decomposition/R15/mesh composition отсутствуют | pass, без регрессии |
| A29 | Mesh Cost = fleet published/delivered/dropped + payload bytes | pass, без регрессии |
| A30 | H1 pre-specified, не pre-registered; остальное exploratory | pass, без регрессии |
| A31 | общей победы C не заявлено | pass, без регрессии |
| A32 | spatial outcomes основаны на external ground truth | pass, без регрессии |
| A33 | старые `657`/realized denominators в методологию не возвращены | pass, без регрессии |
| A34 | blocked result-figure set не возвращён | pass, без регрессии |
| A35 | полный limitation statement сохранён | pass, без регрессии |
| A36 | sustain sensitivity остаётся prospective/offline replay rule | pass, без регрессии |

**Итог по A01–A36:** `36/36 pass`; новых или вновь открытых alignment defects нет.

## 9. Regression matrix R1–R9

| ID | Acceptance result | Статус |
|---|---|---|
| R1 | theoretical basis centralized baseline сохранён; external recovery не приписан A | pass |
| R2 | theoretical basis distributed baseline сохранён; shared security context/closed recovery не приписаны B | pass |
| R3 | operationalization terminology теперь последовательна; stale formal-properties phrases отсутствуют | pass, прежний minor закрыт |
| R4 | §3.4.7 сохраняет definitions, outcomes, valid intervals и presentation rules | pass |
| R5 | пять properties связаны с literature и study-specific outcomes | pass |
| R6 | fixed `90/60/150`; outcomes внутри окна; denominators metric-specific | pass, B01 закрыт |
| R7 | H1/comparison language и табл. 3.15 сохранены; запрещённые working definitions не возвращены | pass |
| R8 | adversary bridges cases 4–5 сохранены без нового estimand | pass |
| R9 | prospective metric contract сохранён; realized n/module/internal audit language не возвращены | pass |

**Итог по R1–R9:** `9/9 pass`.

## 10. Визуальная и структурная проверка

Актуальный DOCX независимо отрендерен в 102 page images. Просмотрены все 102 страницы; ключевые изменённые участки дополнительно проверены в полном разрешении: начало главы 3, citation на p. 24, headings ветки 3.1, §3.5.2–§3.5.3 и табл. 3.11 на pp. 83–89, табл. 3.14 на pp. 92–94, табл. 3.15 и limitations на pp. 96–97.

Не выявлены:

- clipping или overlap;
- missing glyphs;
- оборванные строки или table cells;
- повреждённые table rows;
- выход таблиц за поля;
- новые аномальные page breaks;
- внутрисловные переносы названий метрик в первом столбце табл. 3.14.

Табл. 3.11 корректно продолжается на следующей странице с повторённой header row. Табл. 3.14 занимает три страницы вместо четырёх и сохраняет весь metric contract. Табл. 3.15 читается целиком на одной странице.

Существующий красный diagram placeholder на pp. 36–38 не изменён и, в соответствии с контрольным review scope, не считается новым defect или minor issue этого regression review.

## 11. Неблокирующие audit notes

1. Доступный `CH3_SEMANTIC_CONSERVATION_AUDIT.md` прямо маркирован как восстановленная контрольная копия, а не byte-identical original. Для текущей проверки этого достаточно: требования R1–R9 подтверждены также по фактическому DOCX, patch/fix logs, independent review и frozen audit. Это audit-trail note, а не defect главы 3.
2. Три analytical claims из `FINAL_RESULTS_AUDIT.md` остаются заблокированными до отдельного primary-artifact audit: MTTD decomposition, policy ablation `36.65/1.34 m` и mesh message-type composition `39,198/486`. Они отсутствуют в главе 3, не блокируют её фиксацию и не должны появляться в главе 4 без отдельной проверки.

## 12. Формальный итог

- **B01: закрыт.**
- **Количество новых blockers: 0.**
- **Оставшиеся minor issues: 0 в проверяемом содержательном и layout scope главы 3.**
- **Можно ли коммитить DOCX/PDF: да.** Актуальные DOCX и matching PDF прошли content, structural и render regression checks; сам commit в рамках этой проверки не выполнялся.
- **Можно ли переходить к главе 4: да.** Главу 4 следует писать строго по `FINAL_RESULTS_AUDIT.md`, сохраняя metric-specific denominators, statistical status и запрет на три неаудированных analytical claims.

**Финальный вердикт: глава 3 regression-clean и готова к фиксации DOCX/PDF и переходу к главе 4.**
