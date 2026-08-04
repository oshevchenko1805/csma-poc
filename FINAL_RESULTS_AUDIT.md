# FINAL RESULTS AUDIT

Дата аудита: 2026-08-04  
Репозиторий: `/Users/vsemerenska/Documents/csma/csma-poc`  
Коммит: `f507ba422add4e7a16bfaad91981483e3116b487`  
Назначение: числовой и смысловой шлюз перед написанием глав 4 и 5. Этот файл не является текстом главы.

## 1. Статус и правила источников

Статус: **условно готово к написанию**. Основные результаты воспроизводятся из первичных CSV, но несколько чисел и формулировок во вторичных заметках устарели. Их нельзя переносить в диссертацию без исправления по этому аудиту.

Приоритет источников зафиксирован так:

1. `runs_campaign/campaign_master.csv`;
2. `runs_final/detection_vs_loss.csv`;
3. `runs_campaign/fp_census.csv`;
4. определения и accounting в `metrics/derived.py`, `campaign_report.py`, `metrics/coordination.py`, `metrics/sustain.py`, `campaign_master.py`, а также статистические процедуры в `metrics/stats.py`, `campaign_stats.py`;
5. только для контекста и выбора формы подачи: `HANDOFF_CH45.md`, `RESULTS_NOTES.md`, `FIGURE_SPECS.md`, `HYPOTHESES_DRAFT.md`.

Числа из handoff- и notes-файлов не считаются подтверждёнными, пока не совпали с источниками 1–4. Архивные handoff-файлы не использовались.

Provenance определений зафиксирован точнее: MTTD реализован в `campaign_report.mttd` и переносится в master через `campaign_master.py`; Phase/Geometry Excess определены в `metrics/coordination.py`; sustain sensitivity — в `metrics/sustain.py`; FP- и fleet-level mesh-accounting — в `campaign_master.py`. Остальные производные outcome-метрики определены в `metrics/derived.py`. Численные значения во всех случаях берутся из авторизованных CSV, прежде всего из master.

Хэши первичных файлов:

| файл | SHA-256 |
|---|---|
| `runs_campaign/campaign_master.csv` | `158e57743bceb9c1899805a90fa7065b8e8470213c4c1f30bf15591e4ac282d9` |
| `runs_final/detection_vs_loss.csv` | `5ada30d0b01d304257574da7ad958084f43623c40634a11ac6a3dc01cf53e54a` |
| `runs_campaign/fp_census.csv` | `7f6aceb08e8337e42d3fe0af1758ebb656d7a8e2b6bee8be8ca18caddc3d8b3f` |
| `metrics/derived.py` | `da328262bb2f6441a3493f66adbd5869fc1599a4214509bc6203180c89ba9049` |
| `metrics/stats.py` | `d9f07c97d1e7218ec5bcf3c8db2d9f4966d9eca0f4c631c1e90b0f3fa1ac4638` |
| `campaign_stats.py` | `3f8cb382eb3bedcee430fb65ddff0dd0593643bed5e2e501e6c05fcf8eb3e3f` |

Правила округления и формулировок:

- доли всегда подавать как `k/n`, затем долю и Wilson 95% CI;
- `0/n` не означает «никогда», `n/n` не означает гарантированные 100%;
- отсутствие значимости означает «нет статистических оснований утверждать различие», а не «архитектуры равны»;
- семейство из четырёх сравнений Detection Rate для H1 было **pre-specified in version history before the authoritative master was versioned**; это не pre-registration. Остальные тесты exploratory и без поправки на множественность;
- средние, медианы и интервалы нельзя агрегировать по разным атакам без явного обоснования: состав сценариев различается по архитектурам из-за разных чисел валидных прогонов;
- нулевые, условные и неудобные результаты публикуются вместе с положительными.

## 2. Аудит корпуса и знаменателей

### 2.1 Основная кампания

`campaign_master.csv` содержит 435 уникальных прогонов и 47 колонок.

| поток | число |
|---|---:|
| все строки master | 435 |
| валидные | 414 |
| errored | 20 |
| исключены validity gate | 1 (`attack_did_not_land`) |
| валидные чистые полёты (`attack == none`) | 105, по 35 на A/B/C |
| валидные атакующие прогоны | 309 |
| валидные всего по A/B/C | 136 / 140 / 138 |
| валидные атакующие по A/B/C | 101 / 105 / 103 |

Проверки целостности:

- дубликатов `run_id`: 0;
- все 435 строк имеют `post_fix == True`;
- `detected == True` без конечного `mttd_s`: 0;
- `detected == False` при заполненном `mttd_s`: 0;
- отрицательных `time_to_isolation_s`: 0;
- отрицательных `total_response_time_s`: 0;
- все 309 валидных атакующих прогонов имеют Detection, Containment, Recovery Success, Mission Degradation, Residual Mission Functionality, phase и geometry metrics;
- во всём валидном master `mttd_s` заполнен в 223 строках, а `time_to_isolation_s` — в 222; для анализа реакции на атаку фильтр `attack != none` оставляет n=220 строк с обеими метриками. Три baseline FP-строки имеют MTTD, две из них также имеют Time to Isolation и исключаются из attack-response анализа;
- MTTR заполнен в 267 прогонах, где стабилизация наступила;
- Total Response Time заполнен в 88 прогонах, все они относятся к C.

Число «657 прогонов на диске» не выводится из master и не может быть проверено в текущем локальном корпусе сырых прогонов. Его можно оставить только после отдельного воспроизводимого census каталога на VM. Аудированный поток внутри master: **435 -> 414 = 20 errored + 1 gated out**.

### 2.2 Свип потерь меша

`detection_vs_loss.csv` содержит 10 уровней потерь:

- 255 валидных belief-gated прогонов;
- 166 обнаружений;
- 5 прогонов `no_attack`, исключённых из знаменателей;
- 4 errors, исключённых из знаменателей;
- 264 попытки по сумме `n + no_attack + errors`;
- 2 pre-attack false positives, учтённых отдельно.

Знаменатель каждой точки равен `n` этого уровня, то есть числу прогонов, которые завершились без ошибки и в которых spoof фактически был подтверждён belief gate.

### 2.3 Перепись false positives

`fp_census.csv` содержит только положительные случаи: 17 уникальных прогонов с хотя бы одним false positive. Поэтому знаменатели для частот берутся из master, а не из census.

- A: 6 FP-прогонов из 136 валидных clean windows;
- B: 9 из 140;
- C: 2 из 138;
- всего: 17.

Два класса экспозиции не смешиваются под одним названием:

1. `clean_flight`: весь полёт без атаки, знаменатель 35 на архитектуру;
2. `pre_attack`: только интервал до `inject_start` в атакующем прогоне, знаменатели A/B/C = 101/105/103.

## 3. Контракт метрик

| метрика | точное определение | правильный знаменатель | неопределённость/тест | запрещённое чтение |
|---|---|---|---|---|
| Detection Rate | существует `security` event не раньше `inject_start` и с `target_uav`, равным атакованному борту | все валидные атакующие прогоны данной клетки | Wilson 95%; Fisher exact + Newcombe для сравнений долей | любое событие в прогоне; pre-attack FP как detection |
| MTTD | первая атрибутируемая `security` event минус `inject_start`; реализация `campaign_report.mttd` | только detected attack-прогоны | медиана [IQR]; Mann-Whitney exploratory | сравнение времени в клетке, где baseline ничего не обнаружил |
| Time to Isolation | атрибутируемая `isolation_announce` минус атрибутируемая detection | attack-response: `valid == True & attack != none & time_to_isolation_s.notna()`, n=220; во всём valid master non-null n=222 | медиана и диапазон; confirmatory теста нет | характеристика распределённой архитектуры; использование `n=222` как attack-response знаменателя |
| Containment Success | ни один нецелевой UAV не превысил 15 м off-plan после атаки | валидные атакующие прогоны с наблюдением других UAV, здесь 309 | Wilson 95% | «изоляция сработала» или Isolation Success |
| Recovery Success | off-plan deviation перестала расти до конца окна | все валидные атакующие прогоны | Wilson 95%; отдельного межархитектурного теста нет | доказательство self-healing: baseline-данные лишь согласуются с механизмом saturation |
| MTTR functional | время от isolation, а при её отсутствии от attack onset, до начала окончательно стабильного участка; slope <= 0.5 м/с в окне 5 с | только прогоны, где стабильный участок найден, здесь n=267 | медиана [IQR]; отдельного теста нет | время возврата на маршрут; unconditional metric |
| Stabilisation Level | медианный off-plan level после найденной стабилизации минус pre-attack baseline | только стабилизировавшиеся прогоны | медиана [IQR] | Recovery Success без указания уровня стабилизации |
| Mission Degradation | максимум post-attack distance-to-plan цели минус медиана за 30 с до атаки | все 309 валидных атакующих прогонов | медиана [IQR]; bootstrap CI разности медиан exploratory | чистая максимальная дистанция; отрицательные малые значения считать ошибкой |
| Residual Mission Functionality | доля наблюдаемых UAV на расстоянии <= 15 м от плана в конце ряда | все прогоны с траекториями | дискретные значения 0.33/0.67/1.00 | завершение миссии или синхронность роя |
| Phase Excess | peak разброса накопленного пути относительно медианы роя после атаки минус pre-attack peak; `metrics/coordination.py` | все прогоны с >=2 UAV; attack n=309, clean n=103 | медиана [IQR]; bootstrap diff exploratory | off-plan distance или причинный эффект recovery action |
| Geometry Excess | peak изменения попарных расстояний относительно собственной pre-attack медианы минус pre-attack peak; `metrics/coordination.py` | тот же | медиана [IQR]; bootstrap diff exploratory | строй как единая нормальная шкала без оговорки о тяжёлом хвосте |
| Total Response Time | последняя атрибутируемая recovery request/ack минус attack onset | только прогоны с recovery event, здесь C, n=88 | медиана и диапазон | сравнение A/B/C или полный response time всех атак |
| Mesh Cost | fleet counters на прогон; accounting в `campaign_master.py` | все валидные прогоны архитектуры | mean ± sample SD, диапазон; теста нет | измеренное масштабирование за пределы трёх UAV |
| FP-run prevalence | прогон содержит >=1 security event в своём clean window; accounting в `campaign_master.py` | master, отдельно по типу экспозиции | Wilson 95%; Fisher exploratory | event count как rate; смешивание whole-flight и pre-attack exposure |
| FP loop depth | достигает ли ложная тревога isolation и фактически исполненного recovery action | положительные FP-cases в census | exploratory case analysis, n C=2 | blast radius; распространение обвинения на несколько UAV |
| Loss-sweep Detection | post-attack `cross_check` на цели при подтверждённом landed spoof | `n` на каждом loss level | Wilson 95%; trend test не реализован | A/B тестировались на всех loss levels; строгая монотонность |
| Sustain sensitivity | offline replay порога `ratio > 1` для k подряд; `metrics/sustain.py` | 45 GPS-атак и 105 чистых полётов | Wilson можно показывать; hypothesis test не реализован | общая Detection Rate архитектуры или оптимизация k по независимой выборке |

## 4. Реестр аудированных результатов

### R1. Detection при detector takeout

- **Метрика:** Detection Rate.
- **Знаменатель:** валидные прогоны `detector_takeout+gps_spoofing`: A n=28, B n=30, C n=30.
- **Значение:** A 0/28 = 0.000 [0.000, 0.121]; B 0/30 = 0.000 [0.000, 0.114]; C 30/30 = 1.000 [0.886, 1.000].
- **CI/тест:** Wilson 95% для клеток. C-A: diff +1.000, Newcombe 95% CI [+0.834, +1.000], Fisher p=3.44e-17, Holm p_adj=1.03e-16. C-B: diff +1.000 [+0.839, +1.000], p=1.69e-17, p_adj=6.76e-17.
- **Допустимый вывод:** в этом сценарии C показала дополнительный канал обнаружения, отсутствующий у A и B; три клетки полностью разделились на наблюдаемой выборке.
- **Запрещено:** «A и B никогда не обнаруживают», «C гарантирует 100%», «меш всегда лучше».
- **Форма подачи:** основная таблица Detection Rate с `k/n` и Wilson CI; confirmatory comparison table с diff, Newcombe CI и Holm p_adj.

### R2. Detection при monitor takeout

- **Метрика:** Detection Rate.
- **Знаменатель:** A n=28, B n=30, C n=30.
- **Значение:** A 0/28 = 0.000 [0.000, 0.121]; B 29/30 = 0.967 [0.833, 0.994]; C 30/30 = 1.000 [0.886, 1.000].
- **CI/тест:** C-A diff +1.000 [+0.834, +1.000], p_adj=1.03e-16. C-B diff +0.033 [-0.083, +0.167], Fisher p=1.00, Holm p_adj=1.00. Exploratory B-A: diff +0.967 [+0.787, +0.994], p=2.00e-15, без поправки.
- **Допустимый вывод:** общий monitoring domain A является наблюдаемой single point of failure; B и C сохраняют detection. Заявленное C-B различие не подтверждено.
- **Запрещено:** «C значимо лучше B», скрывать нулевое C-B сравнение, называть exploratory B-A заранее заявленным тестом.
- **Форма подачи:** та же таблица Detection; нулевой C-B результат выделить в тексте, а не убирать.

### R3. Данные не показывают общего преимущества C по Detection и MTTD в проверенных сценариях

- **Метрики:** Detection Rate и MTTD.
- **Знаменатели:** GPS A/B/C = 15/15/15; comm A/B/C = 15/15/13; command injection = 15/15/15. MTTD условен на detection.
- **Значения Detection:** GPS A 14/15 [0.702, 0.988], B 15/15 [0.796, 1.000], C 14/15 [0.702, 0.988]; comm A 15/15, B 15/15, C 13/13; command injection 15/15 во всех трёх.
- **Значения MTTD, median [IQR], n:** GPS A 2.860 [2.745, 2.947], n=14; B 2.945 [2.842, 3.003], n=15; C 2.939 [2.867, 2.978], n=14. При detector takeout MTTD есть только у C: 7.429 [7.337, 8.208], n=30. При monitor takeout B 2.865 [2.815, 2.977], n=29; C 2.905 [2.803, 2.975], n=30.
- **CI/тест:** GPS Fisher C-A p=1.00; MTTD Mann-Whitney C-A p=0.370, C-B p=0.678. Monitor takeout MTTD C-B p=0.826. Все эти тесты exploratory и без коррекции.
- **Допустимый вывод:** данные не показывают общего преимущества C по скорости или частоте обнаружения в проверенных обычных сценариях; наблюдаемое преимущество C локализовано в coverage при компрометации security plane.
- **Запрещено:** «C обнаруживает раньше», сравнивать 7.4 с cross-check и 2.9 с local GPS как чистый эффект архитектуры, говорить о MTTD baseline в клетках 0 detections.
- **Форма подачи:** компактная MTTD-таблица; объяснение detector/cadence как limitation, если оно подкреплено отдельно. Не делать speed figure.

### R4. Граница применимости mesh-mediated detection

- **Метрика:** Detection Rate C при `detector_takeout+gps_spoofing` по loss probability.
- **Знаменатель:** только валидные belief-gated прогоны; n различается по уровню.

| loss | detected/n | rate | Wilson 95% CI | MTTD median, s |
|---:|---:|---:|---:|---:|
| 0.00 | 27/28 | 0.964 | [0.823, 0.994] | 7.477 |
| 0.10 | 29/29 | 1.000 | [0.883, 1.000] | 7.446 |
| 0.20 | 28/30 | 0.933 | [0.787, 0.982] | 7.482 |
| 0.30 | 19/30 | 0.633 | [0.455, 0.781] | 7.474 |
| 0.40 | 16/28 | 0.571 | [0.391, 0.735] | 7.520 |
| 0.45 | 14/30 | 0.467 | [0.302, 0.639] | 7.508 |
| 0.50 | 14/30 | 0.467 | [0.302, 0.639] | 7.509 |
| 0.55 | 12/26 | 0.462 | [0.288, 0.645] | 8.071 |
| 0.60 | 4/12 | 0.333 | [0.138, 0.609] | 7.756 |
| 0.65 | 3/12 | 0.250 | [0.089, 0.532] | 8.284 |

- **CI/тест:** Wilson 95% на каждой точке; формального trend test и теста MTTD-vs-loss нет.
- **Допустимый вывод:** наблюдается общий нисходящий тренд и плато point estimates около 0.46 при loss 0.45–0.55; даже на 0.65 наблюдались 3/12 detections, но CI широк.
- **Запрещено:** «строго монотонная деградация» (0.964 -> 1.000 между 0 и 0.1), «MTTD не зависит от потерь» без теста, «критический порог 0.3», «A и B равны нулю на каждом уровне».
- **Форма подачи:** `fig4_1_losssweep`, одна C-кривая с Wilson CI и n. Если A/B показаны как reference, подпись обязана сказать, что их 0/28 и 0/30 взяты из основной кампании при другом экспериментальном дизайне, а не из loss sweep.

### R5. Чувствительность sustain rule

- **Метрика:** offline detection локального GPS residual и FP-run prevalence в зависимости от k.
- **Знаменатели:** 45 валидных `gps_spoofing` прогонов, post-attack window; 105 чистых полётов, full-series fleet window.

| k | detection k/n [Wilson 95%] | clean FP k/n [Wilson 95%] |
|---:|---:|---:|
| 1 | 45/45 [0.921, 1.000] | 6/105 [0.026, 0.119] |
| 2 | 43/45 [0.852, 0.988] | 2/105 [0.005, 0.067] |
| 3, shipped | 43/45 [0.852, 0.988] | 2/105 [0.005, 0.067] |
| 4 | 43/45 [0.852, 0.988] | 2/105 [0.005, 0.067] |
| 5 | 40/45 [0.765, 0.952] | 2/105 [0.005, 0.067] |
| 6 | 32/45 [0.566, 0.823] | 2/105 [0.005, 0.067] |

- **CI/тест:** Wilson показан; формального сравнения k нет. Full-series detection для k=2–4 равна 44/45, поэтому окно нужно называть.
- **Допустимый вывод:** shipped k=3 лежит на наблюдаемом плато k=2–4. Переход к k=1 увеличивает point estimate FP-run prevalence с 2/105 до 6/105, то есть втрое, одновременно давая 45/45 вместо 43/45 detections.
- **Запрещено:** «k=3 оптимален», «k=1 статистически втрое хуже», знаменатель 90, смешивание post и full windows.
- **Форма подачи:** `fig4_2_sustain`, две панели с общей осью k; знаменатели и окна в подписи.

### R6. Mission Degradation

- **Метрика:** peak post-attack off-plan distance цели минус pre-attack median baseline.
- **Знаменатель:** все валидные атакующие прогоны клетки.
- **Значения:** median [IQR], n.

| атака | A | B | C |
|---|---:|---:|---:|
| GPS spoofing | 49.837 [49.708, 49.881], 15 | 49.834 [49.663, 49.895], 15 | 19.665 [19.570, 19.732], 15 |
| comm disruption | 1.123 [0.461, 2.853], 15 | 1.195 [0.413, 2.885], 15 | 1.650 [0.543, 5.258], 13 |
| command injection | 37.531 [37.283, 37.667], 15 | 37.547 [37.355, 37.613], 15 | 0.414 [0.398, 0.431], 15 |
| detector takeout + GPS | 49.843 [49.685, 49.917], 28 | 49.842 [49.736, 49.897], 30 | 0.240 [0.175, 0.601], 30 |
| monitor takeout + GPS | 49.888 [49.852, 49.927], 28 | 49.883 [49.763, 49.952], 30 | 19.747 [19.662, 19.846], 30 |

- **CI/тест:** seeded bootstrap CI разности медиан, exploratory и без коррекции. C-A/C-B: command injection примерно -37.12 м, CI не включает 0; detector takeout примерно -49.60 м, CI не включает 0; GPS и monitor takeout примерно -30.1 м, CI не включает 0. Для comm disruption C-A +0.53 м [-1.51, +3.42], C-B +0.45 м [-1.24, +3.52], интервалы включают 0.
- **Допустимый вывод:** C имеет заметно меньшие наблюдаемые median mission degradation во всех сценариях, кроме comm disruption; exploratory bootstrap intervals для четырёх сценариев не включают 0, а comm disruption является нулевым exploratory результатом. Значения A/B около 49.8 м согласуются с потолком инжектированного смещения; saturation не изолирована как независимо доказанная причина.
- **Запрещено:** «C лучше при всех атаках», трактовать разность около 49.6 м как полный нецензурированный размер эффекта, приписывать весь эффект абстрактному self-healing без описания detector/action.
- **Форма подачи:** числовая таблица; `fig4_3_tracks` только для иллюстрации механизма, `fig4_4_tradeoff` для совместного чтения с coordination.

### R7. Recovery после command injection

- **Метрики:** Recovery Success, MTTR functional, Stabilisation Level.
- **Знаменатель:** 15 валидных прогонов на архитектуру; MTTR только у стабилизировавшихся.
- **Значение:** A 0/15 [0.000, 0.204], MTTR отсутствует; B 0/15 [0.000, 0.204], MTTR отсутствует; C 14/15 [0.702, 0.988], MTTR median 0.119 с [0.075, 0.169], n=14.
- **CI/тест:** Wilson для rate; отдельный межархитектурный тест Recovery Success в статистическом коде не заявлен.
- **Допустимый вывод:** в 14/15 прогонах **полной конфигурации C** off-plan growth прекратился в окне наблюдения, в экспериментальном профиле с блокировкой команды и возобновлением миссии; у A/B стабилизация не была обнаружена ни в одном из 15 прогонов в пределах окна. Дизайн сравнивает полные конфигурации и не изолирует causal effect self-healing или отдельного recovery action.
- **Запрещено:** приписывать результат изолированному causal effect self-healing; «A/B никогда не стабилизируются», «уход неограничен», «C всегда полностью восстанавливает миссию»; у C containment при этой атаке 13/15, а не 15/15.
- **Форма подачи:** recovery table с rate, Wilson CI, MTTR и n; tracks figure с формулировкой «не настала протягом вікна спостереження».

### R8. Recovery при GPS spoofing: стабилизация не равна восстановлению

- **Метрики:** Recovery Success, MTTR functional и Stabilisation Level.
- **Знаменатели:** rate по всем валидным прогонам клетки; MTTR/level по стабилизировавшимся.

| атака | A rate; MTTR median [IQR] | B rate; MTTR median [IQR] | C rate; MTTR median [IQR] |
|---|---|---|---|
| GPS spoofing | 12/15; 51.000 [50.833, 51.211], n=12 | 15/15; 50.868 [50.767, 50.999], n=15 | 15/15; 16.356 [16.241, 16.914], n=15 |
| detector takeout + GPS | 26/28; 54.210 [53.573, 54.635], n=26 | 28/30; 54.123 [53.633, 54.514], n=28 | 30/30; 0.131 [0.089, 0.168], n=30 |
| monitor takeout + GPS | 27/28; 53.913 [53.578, 54.453], n=27 | 29/30; 51.353 [50.869, 51.652], n=29 | 30/30; 16.373 [16.147, 16.540], n=30 |

- **CI/тест:** rates требуют Wilson, например 26/28 [0.774, 0.980], 28/30 [0.787, 0.982], 30/30 [0.886, 1.000]. MTTR подан описательно; отдельного теста нет.
- **Механизм/уровень:** median Stabilisation Level при detector takeout A/B/C = 49.124/49.127/-0.174 м; при GPS = 49.153/49.137/19.601 м; при monitor takeout = 49.142/49.147/19.655 м. Эти значения согласуются с механизмом насыщения injected offset около 50 м у A/B и более раннего сдерживания у C, но эксперимент не доказывает saturation как независимо изолированную причину. Отрицательное значение -0.174 м является разностью относительно pre-attack baseline, а не отрицательной дистанцией.
- **Допустимый вывод:** высокий Recovery Success у A/B при spoofing совместим с прекращением роста после достижения потолка injected offset, а не сам по себе с self-healing. У C наблюдается стабилизация на другом уровне в другой полной конфигурации.
- **Запрещено:** «A/B тоже восстанавливаются», «MTTR A/B около 54 с», если не пояснено, что именно стабилизировалось; causal claim на основе post-hoc порога `<40 м`.
- **Форма подачи:** Recovery Success всегда рядом со Stabilisation Level и Mission Degradation. Отдельный recovery rate без уровня стабилизации вводит в заблуждение.

### R9. Coordination trade-off

- **Метрики:** Phase Excess и Geometry Excess.
- **Знаменатель:** все валидные атакующие прогоны клетки.
- **Ключевые значения:**

| C, сценарий | phase median [IQR], m | geometry median [IQR], m | degradation median, m |
|---|---:|---:|---:|
| command injection | 0.223 [0.000, 0.446] | 0.068 [0.000, 0.167] | 0.414 |
| detector takeout + GPS | 172.875 [168.999, 176.837] | 33.067 [30.375, 34.480] | 0.240 |
| monitor takeout + GPS | 144.043 [136.474, 145.348] | 52.709 [51.619, 53.499] | 19.747 |
| GPS spoofing | 145.532 [139.549, 146.762] | 52.877 [51.057, 53.525] | 19.665 |

Baseline comparison medians: detector takeout phase A/B = 14.103/12.401 м и geometry = 74.714/74.214 м; command injection phase A/B = 154.071/151.851 м и geometry = 56.970/59.175 м.

- **CI/тест:** exploratory bootstrap C-baseline diff. Detector takeout phase: C-A +158.8 м [156.0, 163.2], C-B +160.5 [157.7, 164.5]; geometry: C-A -41.6 [-44.1, -40.8], C-B -41.1 [-43.8, -39.6]. Command injection phase: C-A -153.8 [-158.5, -127.6], C-B -151.6 [-154.7, -124.3]; geometry: C-A -56.9 [-59.4, -39.7], C-B -59.1 [-59.4, -43.5]. Все exploratory, uncorrected.
- **Допустимый вывод:** полные сочетания `attack + detection path + action` дают разные наблюдаемые профили containment и coordination. Профиль с loiter согласуется с малым off-plan damage при большой phase divergence, а профиль command injection в полной конфигурации C — с сохранением маршрута и фазы; вклад отдельного recovery action этим дизайном не идентифицирован.
- **Запрещено:** приписывать trade-off только recovery action; «self-healing разрушает координацию», «loiter/command guard доказан как единственная причина». Между строками одновременно меняются attack, detection path и action; ни один компонент не варьировался независимо.
- **Форма подачи:** `fig4_4_tradeoff`, одна точка на прогон, линейные оси; подписать reference level инжектированного смещения 49.8 м и смысл углов. Текст обязан назвать confounding.

### R10. Clean coordination noise floor

- **Метрики:** Phase Excess и Geometry Excess на `attack == none`.
- **Полный valid clean-корпус:** фильтр `valid == True & attack == none`; 103 из 105 полётов имеют обе метрики: A n=34, B n=34, C n=35. Phase median 0.131 м [0.000, 0.427], range 0–190.001; geometry median 0.048 м [0.000, 0.200], range 0–232.151. Phase >10 м: **6/103**; geometry >30 м: **3/103**.
- **Подкорпус base_pass:** дополнительный фильтр `group.str.startswith("base_pass")`; 88 из 90 полётов имеют обе метрики. Phase >10 м: **4/88**; geometry >30 м: **2/88**. Разность относительно полного корпуса создают 15 строк `std_pass1`, из которых две добавляют phase-tail и одна из этих двух также geometry-tail.
- **CI/тест:** описательная характеристика хвоста; тест не заявлен.
- **Допустимый вывод:** для общего noise-floor вывода используется полный valid clean-корпус: типичный clean background мал, но distribution имеет тяжёлый хвост; geometry требует особой осторожности. Подкорпус base_pass допустим только как явно помеченный sensitivity/subset result.
- **Запрещено:** смешивать `4/88, 2/88` и `6/103, 3/103` без фильтра; выдавать base_pass за общий clean noise floor; «noise floor измерен на 30/arch»; сравнивать median атаки только с чистой median, скрывая хвост.
- **Форма подачи:** основной текст — полный корпус `6/103` и `3/103`; при необходимости рядом отдельной строкой — base_pass `4/88` и `2/88`. Не отдельный headline figure.

### R11. Containment, Residual Mission Functionality и event times

#### Containment

- **Метрика:** отсутствие распространения последствий за пределы атакованного борта.
- **Знаменатель и значение:** A 94/101 = 0.931 [0.864, 0.966]; B 101/105 = 0.962 [0.906, 0.985]; C 100/103 = 0.971 [0.918, 0.990]; всего 295/309 = 0.955 [0.925, 0.973].
- **CI/тест:** Wilson 95%; confirmatory test не заявлен.
- **Допустимый вывод:** в большинстве прогонов последствия не распространялись на нецелевые UAV; агрегаты по архитектурам описательные и слабо разделяют их. Они не являются confirmatory сравнением и объединяют разные сценарии атак.
- **Запрещено:** Isolation Success, «изоляция успешна в 295/309», причинная атрибуция механизму isolation.

#### Residual Mission Functionality

- **Метрика:** доля UAV в пределах 15 м от плана в последнем срезе.
- **Знаменатель:** все 309 валидных атакующих прогонов; гранулярность 0.33/0.67/1.00.
- **Ключевой результат:** C при detector takeout имеет median 1.00 [1.00, 1.00], одновременно с phase median 172.875 м.
- **Допустимый вывод:** бинарное пребывание у линии маршрута не означает сохранение миссионной фазы.
- **Запрещено:** «100% mission functionality» без phase metric.

#### Time to Isolation

- **Знаменатель:** во всём валидном master фильтр `valid == True & time_to_isolation_s.notna()` даёт **n=222**. Для анализа реакции на атаку применяется `valid == True & attack != none & time_to_isolation_s.notna()`, что даёт **n=220**. Исключаются две baseline FP-строки: `A_none_r2_1785303964` и `B_none_r3_1785483357`; их nominal attack/detection/isolation event chain относится к ложным тревогам, а не к реакции на инжектированную атаку.
- **Значение:** overall median 51.856 мкс, range 36.240–548.363 мкс. A n=44, median 52.810 мкс; B n=74, 51.379 мкс; C n=102, 51.618 мкс.
- **CI/тест:** описательно; confirmatory test отсутствует.
- **Допустимый вывод:** локальная in-process isolation dispatch занимает десятки микросекунд и практически не является архитектурным различителем.
- **Запрещено:** диапазон «40–59 мкс»; использовать `n=222` как знаменатель attack-response результата; трактовать это как время физической локализации угрозы.

#### Total Response Time

- **Знаменатель:** C-only, n=88.
- **Значение:** median 7.431 с, range 0.016–8.354. По клеткам: command injection n=14, median 0.029; detector takeout n=30, 7.441; GPS n=14, 7.427; monitor takeout n=30, 7.457.
- **CI/тест:** описательно; межархитектурное сравнение невозможно.
- **Допустимый вывод:** описывает event-chain timing тех C-прогонов, где recovery events существовали.
- **Запрещено:** общий response time архитектур A/B/C; перенос на comm disruption; unconditional n=309.

### R12. Mesh cost

- **Метрики:** published messages, published bytes, delivered messages, dropped messages на валидный прогон.
- **Знаменатели:** A n=136, B n=140, C n=138.
- **Значение:** A и B имеют точные нули по всем четырём полям. C: published 457.17 ± 22.51 msgs/run; 121,734.88 ± 5,930.87 bytes/run; delivered 914.35 ± 45.02 msgs/run; dropped 0. Здесь `±` = sample SD.
- **CI/тест:** описательные mean ± SD; тест не нужен для structural zeros A/B.
- **Допустимый вывод:** данная трёх-UAV реализация C несёт ненулевой измеренный mesh overhead, тогда как A/B используют `NoOpMesh` и имеют нулевые counters.
- **Запрещено:** `902 ± 52 delivered`; выдавать O(N²) как измеренный scaling result; сообщать состав `39,198 peer_position против 486 security messages`, поскольку он не воспроизводится из авторизованных CSV.
- **Форма подачи:** одна строка таблицы, не рисунок.

### R13. False positives: частота и глубина цикла

#### Чистые полёты

- **Метрика:** доля clean flights с >=1 FP.
- **Знаменатель:** 35 на архитектуру.
- **Значение:** A 2/35 = 0.057 [0.016, 0.186], 6 events; B 4/35 = 0.114 [0.045, 0.260], 9 events; C 0/35 = 0.000 [0.000, 0.099], 0 events.
- **CI/тест:** Fisher exploratory: C-A p=0.493, C-B p=0.114, A-B p=0.673.
- **Допустимый вывод:** в 35 наблюдавшихся clean flights C не дала ни одного FP, но статистических оснований утверждать различие частот нет.
- **Запрещено:** «C не имеет false positives», «частоты равны», «C статистически тише».

#### Все валидные clean windows

- **Метрика:** доля валидных прогонов с FP в соответствующем clean window.
- **Знаменатель и значение:** A 6/136 = 0.044 [0.020, 0.093], 13 events; B 9/140 = 0.064 [0.034, 0.118], 15 events; C 2/138 = 0.014 [0.004, 0.051], 13 events.
- **CI/тест:** Fisher exploratory: C-A p=0.171, C-B p=0.060, A-B p=0.598.
- **Допустимый вывод:** нет статистических оснований утверждать различие в FP-run prevalence. Это incidence по смешанным типам clean window, не единая rate per time.
- **Запрещено:** объединять эти числа с clean-flight rate, «same rate» как доказанная эквивалентность, сравнивать event totals как частоту.

#### Глубина цикла

- **Метрика:** числа accused UAV, isolation events и фактически выполненных recovery actions в FP-cases.
- **Знаменатель:** полный census содержит 17 FP-runs; детальный механизм C основан на n=2 pre-attack cases.
- **Значение:** крупнейшие A/B cascades: по 3 accused UAV, 3 isolations, 0 recovery actions. Два C-cases: по 1 accused UAV; 7 и 5 isolations; 4 и 3 recovery actions. Всего у C 13 FP-events, из них cross_check 10 и gps 3.
- **CI/тест:** exploratory case analysis, формального теста нет; механизм C основан на n=2.
- **Допустимый вывод:** ни один наблюдавшийся A/B FP не дошёл до recovery; в двух наблюдавшихся C-cases цикл дошёл до фактически исполненного recovery action над исправным аппаратом. Это exploratory наблюдение с явным **n=2**, а не оценка популяционной частоты.
- **Запрещено:** blast radius, «тревога распространяется на большее число жертв», «fleet-wide victims». По ширине обвинения C уже A/B: 1 против 3.
- **Форма подачи:** таблица frequency + отдельная механистическая таблица loop depth с явным `n=2, pre-attack exposure`.

## 5. Статус гипотез

| гипотеза из draft | аудированный статус | допустимая версия |
|---|---|---|
| H1, A <= B <= C при атаке на security plane | частично подтверждена; family была pre-specified in version history before the authoritative master was versioned, но не pre-registered; одно сравнение C-B null | C отделяется от A в обоих takeout-сценариях и от B при detector takeout; C и B не различаются при monitor takeout |
| H2, C обнаруживает раньше | не подтверждена | coverage, а не speed, является преимуществом C; GPS MTTD не различается exploratory |
| H3, Time to Isolation и Isolation Success различают архитектуры | draft семантически неверен | Time to Isolation является локальным in-process timing; `containment_success` не измеряет isolation mechanism |
| H4, стабилизация после command injection | поддержана описательно, post-hoc | в полных конфигурациях A/B/C наблюдалось 0/15, 0/15, 14/15 в пределах окна; causal effect self-healing отдельно не изолирован |
| H5, C снижает mission degradation во всех атаках | поддержана с исключением | ниже в четырёх сценариях; comm disruption является null exploratory result |
| H6, coordination зависит от recovery action | наблюдаемая ассоциация, causal isolation отсутствует | attack, detection path и action меняются совместно; вклад action не варьировался и не идентифицировался независимо |
| H7, mesh не увеличивает FP и имеет blast radius | частота: различие не доказано; blast-radius часть отвергнута | публиковать clean-flight prevalence и loop depth, не blast radius |

Только H1 имеет семейство тестов, **pre-specified in version history before the authoritative master was versioned**. H1 не было pre-registered; H4–H7, сформулированные после данных, также нельзя называть pre-registered.

## 6. Реестр расхождений во вторичных файлах

Следующие формулировки заблокированы:

1. `HANDOFF_CH45.md`: Time to Isolation `n=222` корректно описывает все non-null значения в valid master, но не attack-response корпус. После фильтра `attack != none` анализ использует **n=220**; две baseline FP-строки исключены.
2. `HANDOFF_CH45.md` и `RESULTS_NOTES.md`: clean coordination tail `4/88` и `2/88` воспроизводится для `base_pass`. Полный valid clean-корпус даёт **phase >10 м: 6/103; geometry >30 м: 3/103** и используется для общего noise-floor вывода.
3. `RESULTS_NOTES.md` R12: delivered mesh cost `902 ± 52`. Master даёт **914.35 ± 45.02**, n=138.
4. `RESULTS_NOTES.md` R10: `3/210` pre-attack FP относится к старой/pilot версии. Финальный CSV содержит **2 pre-attack FP при 255 valid**.
5. `HANDOFF_CH45.md`, `RESULTS_NOTES.md`, `FIGURE_SPECS.md`: «монотонная» loss degradation. Point estimates не строго монотонны, поскольку 0.10 выше 0.00. Допустим «общий нисходящий тренд».
6. `FIGURE_SPECS.md` 4.2 в строке данных всё ещё говорит о 90 чистых прогонах; правильный знаменатель **105**.
7. `HYPOTHESES_DRAFT.md` H2 содержит устаревшие MTTD 2.85/2.88/2.98. Правильные GPS medians: **2.860/2.945/2.939 с** с n=14/15/14.
8. `HYPOTHESES_DRAFT.md` H3 использует Isolation Success. Поле переименовано и по смыслу является **Containment Success**.
9. `HYPOTHESES_DRAFT.md` H7 и ранний R13 используют blast radius. `fp_census.csv` и R19.4 опровергают эту интерпретацию; публикуется **loop depth**.
10. `HANDOFF_CH45.md` даёт Fisher C-A для FP как 0.172. Реализация `metrics.stats.fisher_exact` на текущем master даёт **0.170911**, то есть 0.171 при округлении до трёх знаков. Вывод не меняется.
11. R9 decomposition и утверждение, что «большая часть MTTD является полом стенда», опираются на отдельные raw series и не воспроизводятся из трёх авторизованных CSV. Весь decomposition-result заблокирован до отдельного аудита первичных raw artefacts.
12. R15 ablation `36.65 м против 1.34 м` не представлена в master, loss CSV или FP census. Ablation-result заблокирован до отдельного аудита первичного artefact и знаменателей.
13. Mesh message composition `39,198 peer_position против 486 security messages` не представлена в master. Composition-result заблокирован до отдельного аудита первичных mesh artefacts.
14. Поток `657 на диске -> 435 в анализе` не воспроизводится из локального master. До отдельного directory census разрешена только часть `435 -> 414`.
15. `campaign_stats.py` читает каталоги прогонов, а не master. Финальные inferential numbers должны считаться из master с функциями `metrics.stats`; именно так они проверены в этом аудите.

## 7. Финальная форма подачи

### Рисунки

1. `fig4_1_losssweep`: только C loss-sweep, Wilson CI и n. A/B reference явно пометить как данные основной кампании, не loss-sweep.
2. `fig4_2_sustain`: две панели; attack post-window 45 и clean full-window 105; k=3 отмечен как shipped, не «оптимальный».
3. `fig4_3_tracks`: сетка 2 x 3, median-nearest непарные прогоны; иллюстрирует механизм, не доказывает причинность; общие оси только внутри ряда.
4. `fig4_4_tradeoff`: scatter на линейных осях, одна точка на прогон; reference level инжектированного смещения 49.8 м и confounding attack/detection/action указаны явно.

Карта режимов 5 x 3 в набор не входит.

### Таблицы

Обязательные таблицы:

- Detection Rate по пяти атакам, `k/n`, Wilson CI;
- четыре confirmatory comparisons, Newcombe CI и Holm p_adj, включая null C-B;
- Mission Degradation median [IQR] и n;
- Recovery Success + MTTR + Stabilisation Level, в одной таблице;
- Containment, Residual Functionality и Time to Isolation с корректными названиями;
- Mesh Cost, n и mean ± sample SD;
- FP: отдельно clean flights, all clean windows и loop depth;
- MTTD как conditional descriptive metric, без speed headline.

### Обязательные ограничения рядом с результатами

- simulation-only, три UAV, ZeroMQ mesh, один spoof magnitude;
- Detection при loss оценивалась только для C/cross_check;
- данные Recovery Success при spoofing согласуются с saturation injected offset, но не доказывают этот механизм как независимо изолированную причину;
- coordination trade-off конфаундлен: attack, detection path и action не варьировались независимо;
- два последних loss levels имеют n=12 и широкие CI;
- C loop-depth mechanism основан на двух pre-attack FP-cases;
- нули и единицы являются выборочными наблюдениями с ненулевой неопределённостью.

## 8. Решение перед написанием глав

Числовое ядро готово. Совокупность результатов поддерживает узкий архитектурный вклад: полная конфигурация C сохраняет дополнительное detection coverage и наблюдаемую устойчивость в проверенных сценариях компрометации security plane и command path. Она не доказывает общего преимущества C, более раннего обнаружения или изолированного causal effect self-healing; положительные результаты условны на сценарий и сопровождаются coordination/mesh/FP trade-offs. Главы 4–5 можно писать только по значениям и формулировкам этого аудита. До начала текста не требуется менять код, данные или рисунки.

Три содержательных пункта остаются **заблокированными как результаты** до отдельного аудита первичных artefacts, но не блокируют основную главу:

1. R9 MTTD decomposition по raw series;
2. R15 policy ablation 36.65/1.34 м;
3. mesh message-type composition 39,198/486.

Если эти пункты нужны в диссертации, для каждого требуется отдельный первичный artefact с явным знаменателем и воспроизводимым расчётом. До этого их нельзя использовать как количественное или качественное доказательство.
