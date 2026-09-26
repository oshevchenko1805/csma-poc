# Таблиці до розділу 4 — review draft

Дата: 2026-08-05

Frozen results boundary: `7451258`

Frozen Chapter 3 boundary: `b6f75d4`

## Статус і нормативне правило

Цей файл є рецензійним макетом таблиць, а не новим статистичним output. Нормативним джерелом числових значень, статистичного статусу та допустимих інтерпретацій є `FINAL_RESULTS_AUDIT.md`. CSV і код використовуються лише як provenance-артефакти для перевірки вже аудованих результатів.

Пропуски не заповнюються самостійним перерахунком із CSV. Позначка «не наведено в frozen audit» означає, що для появи значення у фінальній таблиці потрібен окремий audit addendum і його заморожування. Це правило особливо стосується повних таблиць MTTD, Wilson CI для Recovery Success і Stabilisation Level.

Статус `confirmatory` мають лише чотири контрасти основного дослідницького припущення у табл. 4.3. Усі інші порівняння є exploratory або descriptive відповідно до позначок нижче.

## Таблиця 4.1. Потік корпусу та eligibility основних метрик

### Панель A. Потік основної кампанії

| Етап | Умова | Усього | A | B | C |
|---|---|---:|---:|---:|---:|
| Усі записи master | усі рядки `campaign_master.csv` | 435 | — | — | — |
| Виключені через помилку | `errored == True` | 20 | — | — | — |
| Виключені як gated run | `exclusion_reason == attack_did_not_land` | 1 | — | — | — |
| Валідний корпус | `valid == True` | 414 | 136 | 140 | 138 |
| Валідні attack-runs | `valid == True & attack != none` | 309 | 101 | 105 | 103 |
| Валідні clean flights | `valid == True & attack == none` | 105 | 35 | 35 | 35 |

### Панель B. Metric-specific eligibility

| Метрика / аналіз | Population / filter | Знаменник |
|---|---|---:|
| Detection Rate | валідні attack-runs, окрема `architecture × attack` cell | cell-specific, табл. 4.2 |
| Conditional MTTD | валідні attack-runs із `detected == True` і ненульовим `mttd_s` | cell-specific, табл. 4.4 |
| Containment Success | усі валідні attack-runs | 309 (A/B/C: 101/105/103) |
| Time to Isolation | валідні attack-runs із ненульовим `time_to_isolation_s`; дві baseline FP rows не входять | 220 (44/74/102) |
| Total Response Time | лише C-runs із наявними recovery events | 88 |
| Clean coordination reference | валідні clean flights, де наявні обидві coordination metrics | 103 (34/34/35) |
| Mesh Cost | усі валідні runs | 414 (136/140/138) |
| FP prevalence: clean flights | валідні `attack == none` | 105 (35/35/35) |
| FP prevalence: all clean windows | усі валідні runs; whole-flight або pre-attack clean window | 414 (136/140/138) |
| FP loop-depth census | лише позитивні FP cases | 17; детальний механізм C: 2 |

Примітка. Однакова тривалість експериментальних вікон не створює спільного знаменника для різних метрик.

## Таблиця 4.2. Detection Rate за типом атаки й архітектурою

| Attack | A, k/n (Wilson 95% CI) | B, k/n (Wilson 95% CI) | C, k/n (Wilson 95% CI) | Статус |
|---|---:|---:|---:|---|
| GPS spoofing | 14/15 (0.702–0.988) | 15/15 (0.796–1.000) | 14/15 (0.702–0.988) | descriptive; cross-architecture exploratory |
| Comm disruption | 15/15 (0.796–1.000) | 15/15 (0.796–1.000) | 13/13 (0.772–1.000) | descriptive |
| Command injection | 15/15 (0.796–1.000) | 15/15 (0.796–1.000) | 15/15 (0.796–1.000) | descriptive |
| Detector takeout + GPS spoofing | 0/28 (0–0.121) | 0/30 (0–0.114) | 30/30 (0.886–1.000) | контрасти основного дослідницького припущення у табл. 4.3 |
| Monitor takeout + GPS spoofing | 0/28 (0–0.121) | 29/30 (0.833–0.994) | 30/30 (0.886–1.000) | контрасти основного дослідницького припущення у табл. 4.3 |

Примітка. `0/n` не означає неможливість події, а `n/n` — гарантований результат у генеральній сукупності. Detection Rate не характеризує швидкість detection.

## Таблиця 4.3. Чотири заздалегідь визначені контрасти основного дослідницького припущення

| Scenario | Контраст | Різниця часток C − baseline | Newcombe 95% CI | Fisher exact p | Holm-adjusted p | Висновок |
|---|---|---:|---:|---:|---:|---|
| Detector takeout + GPS spoofing | C − A | +1.000 | +0.834…+1.000 | 3.44e-17 | 1.03e-16 | підтримано |
| Detector takeout + GPS spoofing | C − B | +1.000 | +0.839…+1.000 | 1.69e-17 | 6.76e-17 | підтримано |
| Monitor takeout + GPS spoofing | C − A | +1.000 | +0.834…+1.000 | 3.44e-17 | 1.03e-16 | підтримано |
| Monitor takeout + GPS spoofing | C − B | +0.033 | −0.083…+0.167 | 1.000 | 1.000 | не підтверджено |

Примітка. Family була pre-specified, але не pre-registered. Основне дослідницьке припущення підтримано частково; null C–B у monitor-takeout cell не є доказом equivalence.

## Таблиця 4.4. Умовний MTTD для сценаріїв із наявним виявленням

| Attack | Architecture | n detected | Median, s | IQR, s | Exploratory comparison |
|---|---:|---:|---:|---:|---|
| GPS spoofing | A | 14 | 2.860 | 2.745–2.947 | C–A: Mann–Whitney p=0.370 |
| GPS spoofing | B | 15 | 2.945 | 2.842–3.003 | C–B: p=0.678 |
| GPS spoofing | C | 14 | 2.939 | 2.867–2.978 | reference |
| Detector takeout + GPS spoofing | C | 30 | 7.429 | 7.337–8.208 | інші architectures не мали detections |
| Monitor takeout + GPS spoofing | B | 29 | 2.865 | 2.815–2.977 | C–B: p=0.826 |
| Monitor takeout + GPS spoofing | C | 30 | 2.905 | 2.803–2.975 | reference |

Примітки. MTTD є умовною метрикою серед detected runs. Cells без detections не мають визначеного MTTD.

## Допоміжні табличні дані до рис. 4.1. Loss sensitivity для C/cross-check

| Mesh loss | Detected / n | Detection Rate | Wilson 95% CI | Conditional MTTD median, s |
|---:|---:|---:|---:|---:|
| 0.00 | 27/28 | 0.964 | 0.823–0.994 | 7.477 |
| 0.10 | 29/29 | 1.000 | 0.883–1.000 | 7.446 |
| 0.20 | 28/30 | 0.933 | 0.787–0.982 | 7.482 |
| 0.30 | 19/30 | 0.633 | 0.455–0.781 | 7.474 |
| 0.40 | 16/28 | 0.571 | 0.391–0.735 | 7.520 |
| 0.45 | 14/30 | 0.467 | 0.302–0.639 | 7.508 |
| 0.50 | 14/30 | 0.467 | 0.302–0.639 | 7.509 |
| 0.55 | 12/26 | 0.462 | 0.288–0.645 | 8.071 |
| 0.60 | 4/12 | 0.333 | 0.138–0.609 | 7.756 |
| 0.65 | 3/12 | 0.250 | 0.089–0.532 | 8.284 |

Примітка. Це exploratory sensitivity лише для C у detector-takeout + GPS scenario. Формальний trend test не виконувався; послідовність point estimates не є строго монотонною, а два найвищі рівні мають n=12.

## Допоміжні табличні дані до рис. 4.2. Sustain sensitivity

| Sustain k | GPS local-signal detections / 45 (Wilson 95% CI) | Clean FP-runs / 105 (Wilson 95% CI) |
|---:|---:|---:|
| 1 | 45/45 (0.921–1.000) | 6/105 (0.026–0.119) |
| 2 | 43/45 (0.852–0.988) | 2/105 (0.005–0.067) |
| 3, основна кампанія | 43/45 (0.852–0.988) | 2/105 (0.005–0.067) |
| 4 | 43/45 (0.852–0.988) | 2/105 (0.005–0.067) |
| 5 | 40/45 (0.765–0.952) | 2/105 (0.005–0.067) |
| 6 | 32/45 (0.566–0.823) | 2/105 (0.005–0.067) |

Примітка. Це offline sensitivity локального GPS detector, а не architecture-level Detection Rate. Дані не встановлюють, що k=3 є оптимальним.

## Таблиця 4.5. Containment, residual functionality і event-chain timing

### Панель A. Containment Success

| Architecture | Success / n | Rate | Wilson 95% CI |
|---|---:|---:|---:|
| A | 94/101 | 0.931 | 0.864–0.966 |
| B | 101/105 | 0.962 | 0.906–0.985 |
| C | 100/103 | 0.971 | 0.918–0.990 |
| Разом | 295/309 | 0.955 | 0.925–0.973 |

### Панель B. Time to Isolation

| Population | n | Median, μs |
|---|---:|---:|
| Усі eligible attack-responses | 220 | 51.856 |
| A | 44 | 52.810 |
| B | 74 | 51.379 |
| C | 102 | 51.618 |

### Панель C. Total Response Time, лише C та лише runs із recovery events

| Population | n | Median, s |
|---|---:|---:|
| Усі eligible C-runs | 88 | 7.431 |
| Command injection | 14 | 0.029 |
| Detector takeout + GPS spoofing | 30 | 7.441 |
| GPS spoofing | 14 | 7.427 |
| Monitor takeout + GPS spoofing | 30 | 7.457 |

### Панель D. Обов'язкове cross-read Residual Mission Functionality

| Cell | n | Residual Mission Functionality, median [IQR] | Phase Excess, median, m | Інтерпретація |
|---|---:|---:|---:|---|
| C, detector takeout + GPS spoofing | 30 | 1.00 [1.00, 1.00] | 172.875 | близькість до маршруту наприкінці серії не означає збереження coordination |

Примітки. Containment Success не перейменовується на Isolation Success. Time to Isolation вимірює локальний in-process dispatch, а не фізичну локалізацію загрози. Для attack-response denominator використовується n=220, не 222. Total Response Time не допускає A/B/C comparison.

## Таблиця 4.6. Recovery Success, MTTR functional і Stabilisation Level

### Панель A. Command injection

| Attack | Arch. | Recovery Success | Wilson 95% CI | MTTR median [IQR], s; n |
|---|---:|---:|---:|---:|
| Command injection | A | 0/15 | 0–0.204 | не визначено |
| Command injection | B | 0/15 | 0–0.204 | не визначено |
| Command injection | C | 14/15 | 0.702–0.988 | 0.119 [0.075, 0.169]; n=14 |

### Панель B. GPS-пов'язані сценарії

| Attack | Arch. | Recovery Success | MTTR median [IQR], s; n | Stabilisation Level median, m |
|---|---:|---:|---:|---:|
| GPS spoofing | A | 12/15 | 51.000 [50.833, 51.211]; n=12 | 49.153 |
| GPS spoofing | B | 15/15 | 50.868 [50.767, 50.999]; n=15 | 49.137 |
| GPS spoofing | C | 15/15 | 16.356 [16.241, 16.914]; n=15 | 19.601 |
| Detector takeout + GPS spoofing | A | 26/28 | 54.210 [53.573, 54.635]; n=26 | 49.124 |
| Detector takeout + GPS spoofing | B | 28/30 | 54.123 [53.633, 54.514]; n=28 | 49.127 |
| Detector takeout + GPS spoofing | C | 30/30 | 0.131 [0.089, 0.168]; n=30 | −0.174 |
| Monitor takeout + GPS spoofing | A | 27/28 | 53.913 [53.578, 54.453]; n=27 | 49.142 |
| Monitor takeout + GPS spoofing | B | 29/30 | 51.353 [50.869, 51.652]; n=29 | 49.147 |
| Monitor takeout + GPS spoofing | C | 30/30 | 16.373 [16.147, 16.540]; n=30 | 19.655 |

Примітки. MTTR і Stabilisation Level визначаються лише для stabilized runs. Значення −0.174 m є різницею відносно baseline, а не «від'ємною відстанню». При spoofing стабілізація A/B поблизу 49.8 m сумісна з досягненням injected-offset ceiling, тому Recovery Success не є самостійним доказом self-healing або повернення до маршруту.

## Таблиця 4.7. Mission Degradation за типом атаки й архітектурою

| Attack | A median [IQR], m; n | B median [IQR], m; n | C median [IQR], m; n | Exploratory C − baseline evidence |
|---|---:|---:|---:|---|
| GPS spoofing | 49.837 [49.708, 49.881]; 15 | 49.834 [49.663, 49.895]; 15 | 19.665 [19.570, 19.732]; 15 | bootstrap CI виключає 0 |
| Comm disruption | 1.123 [0.461, 2.853]; 15 | 1.195 [0.413, 2.885]; 15 | 1.650 [0.543, 5.258]; 13 | C−A +0.53 [−1.51, +3.42]; C−B +0.45 [−1.24, +3.52] |
| Command injection | 37.531 [37.283, 37.667]; 15 | 37.547 [37.355, 37.613]; 15 | 0.414 [0.398, 0.431]; 15 | bootstrap CI виключає 0 |
| Detector takeout + GPS spoofing | 49.843 [49.685, 49.917]; 28 | 49.842 [49.736, 49.897]; 30 | 0.240 [0.175, 0.601]; 30 | bootstrap CI виключає 0 |
| Monitor takeout + GPS spoofing | 49.888 [49.852, 49.927]; 28 | 49.883 [49.763, 49.952]; 30 | 19.747 [19.662, 19.846]; 30 | bootstrap CI виключає 0 |

Примітка. Bootstrap comparisons є exploratory, uncorrected. Comm disruption є обов'язковим null result. Значення A/B поблизу 49.8 m цензуровані injected-offset ceiling; це не uncensored effect size.

## Таблиця 4.8. Coordination profiles і clean reference

### Панель A. Спостережувані профілі C

| Attack | Phase Excess median [IQR], m | Geometry Excess median [IQR], m | Mission Degradation median, m |
|---|---:|---:|---:|
| Command injection | 0.223 [0, 0.446] | 0.068 [0, 0.167] | 0.414 |
| Detector takeout + GPS spoofing | 172.875 [168.999, 176.837] | 33.067 [30.375, 34.480] | 0.240 |
| Monitor takeout + GPS spoofing | 144.043 [136.474, 145.348] | 52.709 [51.619, 53.499] | 19.747 |
| GPS spoofing | 145.532 [139.549, 146.762] | 52.877 [51.057, 53.525] | 19.665 |

### Панель B. Exploratory bootstrap contrasts для двох показових bundled profiles

| Attack / metric | Baseline A median | Baseline B median | C−A difference [95% CI], m | C−B difference [95% CI], m |
|---|---:|---:|---:|---:|
| Detector takeout: Phase Excess | 14.103 | 12.401 | +158.8 [+156.0, +163.2] | +160.5 [+157.7, +164.5] |
| Detector takeout: Geometry Excess | 74.714 | 74.214 | −41.6 [−44.1, −40.8] | −41.1 [−43.8, −39.6] |
| Command injection: Phase Excess | 154.071 | 151.851 | −153.8 [−158.5, −127.6] | −151.6 [−154.7, −124.3] |
| Command injection: Geometry Excess | 56.970 | 59.175 | −56.9 [−59.4, −39.7] | −59.1 [−59.4, −43.5] |

### Панель C. Full clean coordination reference

| Metric | n | Median [IQR], m | Range, m | Tail count |
|---|---:|---:|---:|---:|
| Phase Excess | 103 (A/B/C: 34/34/35) | 0.131 [0, 0.427] | 0–190.001 | >10 m: 6/103 |
| Geometry Excess | 103 (A/B/C: 34/34/35) | 0.048 [0, 0.200] | 0–232.151 | >30 m: 3/103 |

Примітки. Base-pass sensitivity subset (n=88) має tail counts 4/88 і 2/88, але не замінює full clean reference. Профілі є bundled combinations `attack + detection path + action`; внесок окремої action дизайном не ідентифікований.

## Таблиця 4.9. Mesh Cost у валідному корпусі

| Architecture | n | Published msgs/run, mean ± sample SD | Bytes/run, mean ± sample SD | Delivered msgs/run, mean ± sample SD | Dropped msgs/run |
|---|---:|---:|---:|---:|---:|
| A | 136 | 0 (structural zero) | 0 (structural zero) | 0 (structural zero) | 0 |
| B | 140 | 0 (structural zero) | 0 (structural zero) | 0 (structural zero) | 0 |
| C | 138 | 457.17 ± 22.51 | 121,734.88 ± 5,930.87 | 914.35 ± 45.02 | 0 |

Примітки. A/B використовують `NoOpMesh`; нулі не є оцінкою невідомої величини. Результат стосується лише реалізації з трьома UAV і не вимірює scaling law.

## Таблиця 4.10. FP-run prevalence за двома exposure populations

### Панель A. Валідні clean flights

| Architecture | Positive runs / n | Prevalence | Wilson 95% CI | FP events | Exploratory Fisher tests |
|---|---:|---:|---:|---:|---|
| A | 2/35 | 0.057 | 0.016–0.186 | 6 | C–A p=0.493 |
| B | 4/35 | 0.114 | 0.045–0.260 | 9 | C–B p=0.114; A–B p=0.673 |
| C | 0/35 | 0 | 0–0.099 | 0 | reference |

### Панель B. Усі валідні clean windows

| Architecture | Positive runs / n | Prevalence | Wilson 95% CI | FP events | Exploratory Fisher tests |
|---|---:|---:|---:|---:|---|
| A | 6/136 | 0.044 | 0.020–0.093 | 13 | C–A p=0.171 |
| B | 9/140 | 0.064 | 0.034–0.118 | 15 | C–B p=0.060; A–B p=0.598 |
| C | 2/138 | 0.014 | 0.004–0.051 | 13 | reference |

Примітки. Whole-flight clean exposure і pre-attack windows не утворюють однорідну rate-per-time population. Кількість events не є prevalence і не порівнюється як частота без експозиційного знаменника. Дані не встановлюють statistically lower FP prevalence для C.

## Таблиця 4.11. FP loop depth у позитивних cases

| Population | n | Accused width | Isolation events | Executed recovery actions | Інтерпретаційна межа |
|---|---:|---:|---:|---:|---|
| Найбільші observed A/B cascades | входять до census n=17 | до 3 accused | до 3 | 0 | event chain не дійшов до executed recovery |
| C pre-attack case 1 | 1 | 1 | 7 | 4 | case analysis, не population rate |
| C pre-attack case 2 | 1 | 1 | 5 | 3 | case analysis, не population rate |

Примітка. Детальний C mechanism має n=2. У C зафіксовано 13 FP events: 10 `cross_check` і 3 `gps`. Таблиця характеризує loop depth, а не blast radius; за accused width два C cases були вужчими за найбільші A/B cascades.

## Таблиця 4.12 — Узагальнення результатів експериментального дослідження

| Аналітичне положення | Емпіричний результат | Характер аналізу | Практичне значення |
|---|---|---|---|
| Збереження повноти виявлення пов'язане з доступністю незалежного каналу отримання інформації | У стандартних сценаріях усі конфігурації мали високу повноту виявлення; C зберегла виявлення при detector takeout, а B і C при monitor takeout; контраст C–B для monitor takeout залишився нульовим | Перевірка основного дослідницького припущення за чотирма заздалегідь визначеними контрастами | Розділення каналів виявлення зменшує залежність від єдиної точки відмови, коли після компрометації зберігається потрібна інформація |
| Зменшення Mission Degradation має сценарно-залежний характер | C мала меншу спостережувану медіану Mission Degradation у чотирьох із п'яти сценаріїв; comm disruption залишився нульовим результатом; стабілізація на нижчому рівні відхилення спостерігалася за доступної безпечної дії реагування | Сценарно-залежне порівняння фізичних результатів і профілів стабілізації | Результати відновлення слід оцінювати за Mission Degradation, MTTR і Stabilisation Level разом, а не лише за Recovery Success |
| Результат реагування відображає поєднання отримання інформації, виявлення та дії реагування | Профіль C для command injection поєднував захист маршруту і фази; профіль detector takeout поєднував малу деградацію маршруту з великим фазовим розходженням | Системне зіставлення Mission Degradation, Phase Excess і Geometry Excess для комплексних профілів реагування | Вибір дії реагування має враховувати компроміс між захистом маршруту та цілісністю координації |
| Додаткова стійкість супроводжується операційною вартістю та наслідками FP у ланцюзі реагування | C мала вимірювані витрати mesh-обміну; різницю між архітектурами за часткою FP-прогонів не встановлено; у двох спостережуваних випадках C ланцюг хибного реагування досяг виконаної дії відновлення | Опис загальносистемної вартості, аналіз частки FP-прогонів і механістичний аналіз окремих випадків | Розподілене реагування потребує захисних умов, що обмежують небажану дію після хибного виявлення |

## Заборонені доповнення до таблиць

- MTTD decomposition;
- policy ablation `36.65/1.34 m`;
- mesh message-type composition `39,198/486`;
- будь-які додаткові MTTD, Wilson CI, Stabilisation Level або test results, яких немає у frozen audit;
- composite score або pooled architecture ranking.
