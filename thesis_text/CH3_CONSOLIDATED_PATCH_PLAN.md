# Консолидированный план патчей главы 3

**Основание:** `thesis_text/CH23_ALIGNMENT_WITH_FROZEN_RESULTS.md` и замороженный `FINAL_RESULTS_AUDIT.md`, commit `7451258`  
**Назначение:** свести 26 позиций со статусом «блокирует главу 4» к минимальному набору непротиворечивых замен  
**Объект будущих правок:** глава 3 PDF `Thesis Draft Semerenska-4.pdf`, PDF pp. 15–104  
**Текущий статус:** это только patch plan; текст диссертации и её исходники не изменялись

## 1. Решение о консолидации

Двадцать шесть блокирующих позиций объединяются в **шесть патчей**. Меньшее число потребовало бы объединить разные объекты редактирования: описание реализованных конфигураций с формальным контрактом метрик либо исторический статус гипотез с технической областью loss-sweep. Это создало бы большие замены, которые нельзя независимо проверить и которые легко породили бы новые противоречия между 3.2–3.5.

Распределение блокеров:

| Патч | Блок | Закрываемые ID | Количество |
|---|---|---|---:|
| P1 | Граница целевой архитектуры и PoC | A04, A05, A06, A07 | 4 |
| P2 | Граница целевой архитектуры и PoC | A09, A10, A23 | 3 |
| P3 | Единый контракт метрик | A12, A13, A14, A15, A17, A18, A19, A20, A21, A27, A28, A29, A36 | 13 |
| P4 | Гипотезы и допустимая сила выводов | A16, A22, A24, A31 | 4 |
| P5 | Гипотезы и допустимая сила выводов | A30 | 1 |
| P6 | Ограничения и область применимости | A25 | 1 |
| **Итого** |  | **26 уникальных ID** | **26** |

Числовые результаты главы 4 в заменяющие фрагменты не переносятся. Числа используются только для описания фактического корпуса, eligibility denominators, порогов метрик и статистического протокола.

---

## 2. Блок I. Граница целевой архитектуры и PoC

### P1. Единая граница между target architecture, PoC и recovery outcomes

**Закрывает:** A04, A05, A06, A07.

**Точное место в главе 3:**

1. 3.1.7.1, PDF pp. 51–52: заменить абзацы, начинающиеся с описания «Можливості відновлення у випадку GPS spoofing…» и заканчивающиеся утверждением о возврате к штатному режиму.
2. 3.1.7.2, PDF pp. 52–54: заменить recovery-часть после описания локализации command hijacking.
3. 3.1.7.3, PDF pp. 54–56: заменить recovery-часть про восстановление connectivity, rerouting и повторную синхронизацию.
4. 3.2.6, PDF pp. 70–72: перед выводом подраздела вставить сводный абзац «Межа між цільовою моделлю та PoC».

**Существующий смысл текста:** три attack-tree ветви описывают максимально возможный recovery целевой self-healing architecture и затем без явной границы переходят к формулировкам, которые можно прочитать как описание фактически реализованного PoC. Из-за этого альтернативная навигация, перераспределение ролей, перестройка routing, реинтеграция и полное возвращение к миссии выглядят как проверенные механизмы.

**Полный заменяющий фрагмент на украинском:**

#### Для 3.1.7.1 GPS spoofing

> На рівні цільової архітектури recovery після GPS spoofing може передбачати перехід до альтернативного навігаційного джерела, перегляд ролей у рої, зміну режиму координації та подальше повернення до місійної логіки після перевірки стану вузла. Ці можливості визначають простір архітектурних рішень, але не є тотожними обсягу proof-of-concept реалізації.
>
> У PoC для повної конфігурації C реакція на локальний GPS detector або peer-position cross-check завершується командою LOITER для атакованого UAV. Альтернативна сенсорна навігація, автоматичне повернення на маршрут, перерозподіл ролей і повна реінтеграція вузла не реалізуються. Тому в експерименті оцінюються припинення зростання off-plan deviation, functional MTTR і рівень післяінцидентної стабілізації, а не повне відновлення передатакового маршруту чи штатної координації.

#### Для 3.1.7.2 command injection

> На рівні цільової архітектури recovery після command hijacking може включати перегляд повноважень, реконфігурацію ролі вузла та повторну синхронізацію рою. У реалізованому PoC конфігурація C виконує вужчу послідовність: після detection та isolation workflow активує фільтрацію команд із неавторизованим MAVLink sysid і повторно запускає mission mode для атакованого UAV. Ця послідовність розглядається як частина повної bundled-конфігурації C. Експериментальний дизайн не варіює command filter, mission resume, mesh та detection path незалежно, тому не ідентифікує окремий причинний ефект кожного механізму або self-healing як ізольованого компонента.

#### Для 3.1.7.3 communication disruption

> На рівні цільової архітектури recovery після порушення зв’язності може передбачати відновлення communication path, rerouting та повторну синхронізацію станів. У PoC communication disruption відтворюється як network-layer UDP DROP, що запускає heartbeat detection і локальне маркування isolation. У shipped recovery policy причина `heartbeat_loss` не зіставлена з автоматизованою recovery action. Отже, цей injection case перевіряє detection, event-level isolation, containment, mission resilience та coordination outcomes, але не автономне відновлення зв’язності або routing.

#### Вставка в конец 3.2.6

> **Межа між цільовою моделлю та PoC.** Запропонована CSMA-модель визначає повний архітектурний простір detection, isolation, coordinated recovery і reintegration. PoC реалізує лише операціоналізоване підмноження цього простору: local detectors; для конфігурації C — peer-position cross-check і ZeroMQ PUB/SUB; local-state isolation з mesh announce; детермінований вибір координатора; LOITER для GPS/cross-check events; command filtering і mission resume для command-injection events. Маркування isolation у PoC є зміною локального стану та, для C, його поширенням через mesh; воно не є повним network-level відсіканням UAV. Перерозподіл ролей, перебудова routing, зміна геометрії рою, альтернативна навігація та повна реінтеграція залишаються елементами цільової моделі, а не емпірично перевіреними механізмами цього PoC.

**Затрагиваемые таблицы и термины:** recovery branches attack trees; `recovery`, `coordinated recovery`, `LOITER`, `command filtering`, `mission resume`, `reintegration`, `role redistribution`, `routing`, `isolation`.

**Почему это не подгонка теории под результаты:** правка не меняет target architecture и не удаляет теоретически допустимые recovery mechanisms. Она разделяет уровень архитектурного проектирования и заранее существующий уровень реализации, проверяемый по конфигурациям и коду. В текст не добавляются observed effect sizes или направления результатов.

**Проверка соседних подразделов после патча:**

- 3.1.7 остаётся threat-driven описанием возможных защитных ветвей, но больше не выдаёт весь threat-tree response space за PoC.
- 3.2.1–3.2.5 сохраняют target architecture без сужения научного вклада.
- 3.2.6 получает явную implementation boundary и не противоречит будущему описанию testbed в 3.5.2.
- Термин `Recovery Success` нигде в этом патче не определяется; его значение остаётся за единым метрическим контрактом P3.

### P2. Фактические конфигурации A/B/C и запрет component-level causality

**Закрывает:** A09, A10, A23.

**Точное место в главе 3:**

1. 3.3.2–3.3.4, PDF pp. 73–77: заменить операциональное описание baseline recovery/mesh и полностью заменить табл. 3.9.
2. 3.4.6, PDF pp. 85–87: заменить табл. 3.10 и заключительный абзац, который ранжирует архитектуры по ожидаемой эффективности.
3. 3.5.2, PDF p. 90: заменить абзац, начинающийся «Порівняння виконується не між трьома різними фізичними системами…».
4. 3.5.5, PDF pp. 102–103: заменить первые два абзаца о «контрольованій зміні лише одного класу параметрів» и прямой атрибуции различий организации detection/isolation/recovery.

**Существующий смысл текста:** A описана как централизованная архитектура с внешним recovery, B — как distributed baseline, работающая в mesh-среде, а C — как архитектура, уже обладающая лучшей mission resilience и coordination integrity. В experimental design это превращается в утверждение, что различия позволяют идентифицировать эффект отдельных security functions.

**Полный заменяющий фрагмент на украинском:**

#### Замена операционального описания baseline architectures

> Для comparative evaluation архітектури A, B і C визначаються як три повні конфігурації одного testbed. Вони мають однакову місію, однаковий склад UAV, однакові attack injections і спільні measurement rules, але відрізняються сукупністю deployment-рішень security loop.
>
> В архітектурі A один ground-station monitoring domain спостерігає за трьома UAV і виконує локальне event-level рішення про isolation. Automated recovery вимкнено, а security-context mesh реалізовано як NoOpMesh. Тому A є centralized monitoring baseline, але не baseline із реалізованим зовнішнім recovery.
>
> В архітектурі B кожен UAV має власний monitor, який спостерігає лише за локальним вузлом і веде local-state isolation. Automated recovery вимкнено; обмін security context між peers відсутній, а mesh також реалізовано як NoOpMesh. B є distributed local-detection baseline без mesh-mediated cross-check і без замкненого recovery loop.
>
> В архітектурі C кожен UAV має local detectors, а також peer-position cross-check; security та coordination events поширюються через brokerless ZeroMQ PUB/SUB. Local-state isolation доповнюється mesh announce, після чого детерміновано вибраний coordinator може сформувати recovery request і передати його виконавцю цільового UAV. Наявність цих механізмів описує склад конфігурації, але не встановлює наперед її ефективність у кожному attack scenario.

#### Новая редакция табл. 3.9

**Таблиця 3.9. Операціональні відмінності конфігурацій comparative evaluation**

| Характеристика | Архітектура A | Архітектура B | Архітектура C |
|---|---|---|---|
| Розміщення monitoring | Один ground-station failure domain для трьох UAV | Окремий monitor на кожному UAV | Окремий monitor на кожному UAV |
| Local detectors | Heartbeat, command, GPS для кожного спостережуваного UAV | Heartbeat, command, GPS локального UAV | Heartbeat, command, GPS локального UAV та peer-position cross-check |
| Security-context mesh | Відсутній; NoOpMesh | Відсутній; NoOpMesh | ZeroMQ PUB/SUB між peers |
| Isolation у PoC | Local-state mark у ground-station domain | Local-state mark на відповідному UAV | Local-state mark і mesh announce |
| Automated recovery | Вимкнено | Вимкнено | Увімкнено для причин, що мають shipped action mapping |
| Coordinator | Відсутній | Відсутній | Детермінований `lowest-alive-sysid` серед доступних non-isolated peers |
| Предмет емпіричного порівняння | Повна конфігурація A | Повна конфігурація B | Повна конфігурація C |

#### Новая редакция табл. 3.10 и заключения 3.4.6

**Таблиця 3.10. Зв’язок security properties з механізмами та outcome-метриками**

| Security property | Реалізований механізм порівняння | Емпіричний outcome | Межа інтерпретації |
|---|---|---|---|
| Detection capability | Centralized або local monitoring; для C також cross-check | Detection Rate і conditional MTTD | Coverage і speed оцінюються окремо |
| Isolation capability | Event-level local-state isolation; для C mesh announce | Time to Isolation та Containment Success | Event timing не є фізичним containment; Containment Success не доводить дію isolation mechanism |
| Recovery capability | A/B: automated recovery off; C: shipped action mapping | Recovery Success, MTTR functional, Stabilisation Level | Стабілізація не означає повернення до маршруту або повну реінтеграцію |
| Mission resilience | Спільний mission setup і зовнішній trajectory ground truth | Mission Degradation, Residual Mission Functionality | Порівнюються outcomes повних конфігурацій |
| Coordination integrity | Спільна coordinated waypoint mission; для C mesh-mediated actions | Phase Excess і Geometry Excess | Attack, detection path та action не варіюються незалежно |

> Таблиці 3.9–3.10 фіксують наявність механізмів, місце їх виконання та відповідні outcomes. Вони не задають наперед ранжування A, B і C за ефективністю. Одна конфігурація може мати додатковий detection path або recovery workflow і водночас не мати загальної переваги за speed, mission або coordination metrics у кожному сценарії.

#### Замена comparative-design абзацев в 3.5.2 и 3.5.5

> Comparative evaluation виконується для трьох повних bundled-конфігурацій на спільній simulation-based платформі. Кількість UAV, mission plan, attack injection, observation rules і спосіб обчислення outcome-метрик утримуються спільними. Водночас між A, B і C одночасно змінюються placement monitoring functions, failure domains, наявність mesh, cross-check path, propagation isolation events і recovery workflow. Отже, спостережувані відмінності можуть інтерпретуватися як відмінності між повними конфігураціями A/B/C, але не як окремий causal effect mesh, self-healing або конкретної recovery action без спеціального component-level ablation design.

**Затрагиваемые таблицы и термины:** табл. 3.9, табл. 3.10; `centralized recovery`, `distributed baseline`, `NoOpMesh`, `ZeroMQ mesh`, `cross-check`, `bundled configuration`, `causal effect`, `security property`.

**Почему это не подгонка теории под результаты:** состав A/B/C и предмет сравнения определяются конфигурационными файлами и экспериментальным дизайном, а не observed outcomes. Патч не меняет attacks, sample или hypotheses; он уточняет estimand — эффект полной конфигурации вместо неидентифицируемого эффекта отдельного компонента.

**Проверка соседних подразделов после патча:**

- 3.3.1 продолжает объяснять концептуальную роль baselines; 3.3.2–3.3.4 теперь точно задают их experimental instantiation.
- 3.4.1–3.4.2 сохраняют пять security properties как общую аналитическую рамку.
- Табл. 3.10 больше не конфликтует с metric definitions P3 и causal guardrails P4.
- 3.5.2 и 3.5.5 используют одинаковый estimand: whole-configuration comparison.

---

## 3. Блок II. Единый контракт метрик

### P3. Одна authoritative спецификация метрик, знаменателей и статистической подачи

**Закрывает:** A12, A13, A14, A15, A17, A18, A19, A20, A21, A27, A28, A29, A36.

**Точное место в главе 3:**

1. 3.4.3–3.4.5, PDF pp. 80–85: заменить операциональные определения и временные формулы, начиная с первого определения `Detection capability` в 3.4.3 и заканчивая абзацем о `τtotal` в конце 3.4.5. Теоретическое обоснование пяти properties в 3.4.1–3.4.2 сохранить.
2. 3.5.4, PDF pp. 98–102: заменить весь текст подраздела и табл. 3.14 единым metric contract ниже. Абзац на p. 100 о внешнем ground truth сохранить и поставить после нового контракта как provenance note.

**Существующий смысл текста:** свойства и метрики описаны дважды и по-разному. `Isolation Success` смешан с containment; Recovery Success и MTTR означают слишком широкий safe state; MTTD назван средним и speed-comparative; Total Response Time ошибочно связывается с общей стабилизацией A/B/C; FP и coordination metrics названы неавторитетными именами; eligibility denominators и статистический статус не зафиксированы.

**Полный заменяющий фрагмент на украинском:**

#### Полная замена 3.4.3–3.4.5

> ### 3.4.3. Операціональний зв’язок security properties та outcomes
>
> П’ять security properties у цій роботі є теоретичною рамкою, а не назвами взаємозамінних емпіричних метрик. Кожна property операціоналізується кількома outcomes, які вимірюють різні аспекти поведінки. Зокрема, detection coverage не є detection speed; event-level isolation не є фактичним containment; припинення зростання відхилення не є повним recovery; mission state і coordination state оцінюються окремо.
>
> Detection capability операціоналізується через Detection Rate та MTTD. Detection Rate характеризує coverage у визначеній attack cell. MTTD характеризує час до першої атрибутованої detection event лише серед detected runs. Ці outcomes не замінюють один одного.
>
> Isolation capability операціоналізується через Time to Isolation та Containment Success. Time to Isolation є event-level інтервалом між detection і `isolation_announce`. Containment Success є trajectory-derived outcome для non-target UAV. Тому успішне event-level рішення не можна ототожнювати з доведеним фізичним стримуванням, а Containment Success не можна перейменовувати на Isolation Success.
>
> Recovery capability операціоналізується через Recovery Success, MTTR functional та Stabilisation Level. Recovery Success фіксує припинення зростання off-plan deviation в observation window. MTTR functional визначає час до початку фінального стабільного сегмента лише для runs, у яких такий сегмент знайдено. Stabilisation Level показує, на якому відносному off-plan рівні настала стабілізація. Жодна з цих метрик окремо не означає повернення на маршрут, завершення місії або повну реінтеграцію.
>
> Mission resilience операціоналізується через Mission Degradation і Residual Mission Functionality. Перша метрика вимірює приріст peak off-plan deviation атакованого UAV відносно pre-attack baseline; друга — частку спостережуваних UAV, що наприкінці ряду перебувають у межах установленого порога від mission plan.
>
> Coordination integrity операціоналізується через Phase Excess і Geometry Excess. Обидві метрики визначають post-attack excess над власним pre-attack рівнем. Вони не є взаємозамінними з off-plan distance і не утворюють єдиної універсальної шкали coordination quality.
>
> ### 3.4.4. Часові характеристики
>
> Для detection використовується інтервал `t_detect - t_attack`, реалізований як MTTD для detected attack-runs. Для event-level isolation використовується `t_isolation_announce - t_detect`, реалізований як Time to Isolation. Ця величина характеризує локальну dispatch chain і не визначає момент фізичного containment.
>
> Для functional recovery не використовується універсальний event `t_recover`, спільний для всіх архітектур. MTTR functional відраховується від isolation event, а за її відсутності — від attack onset, до початку фінального стабільного trajectory segment. Total Response Time має окреме event-based визначення: attack onset до останньої атрибутованої recovery request або recovery ack. Оскільки така подія наявна лише в runs із recovery workflow, Total Response Time не є сумою універсальних фаз і не використовується як загальна A/B/C метрика часу до стабілізації.
>
> ### 3.4.5. Правило подання похідних метрик
>
> Для кожної метрики обов’язково наводяться operational definition, eligibility filter, знаменник, summary statistic, uncertainty interval і statistical status. Однаковий testbed не створює однакового знаменника: Detection Rate використовує всі valid attack-runs відповідної cell; MTTD є conditional on detection; MTTR functional є conditional on знайдений стабільний segment; clean FP і clean coordination мають окремі exposures. Повний контракт наведено в 3.5.4 і використовується без перейменувань у главі 4.

#### Полная замена 3.5.4 и табл. 3.14

> ### 3.5.4. Metrics, eligibility denominators and statistical presentation
>
> Authoritative master містить 435 рядків. Після застосування validity rules аналітичний корпус становить 414 valid runs: 309 attack-runs і 105 clean flights. Розподіл valid attack-runs за архітектурами A/B/C становить 101/105/103. Ці числа описують corpus accounting, а не результативність архітектур.
>
> Значення метрик і їхні eligibility denominators не виводяться з однакової тривалості observation window автоматично. Для кожного outcome застосовується власний фільтр, наведений у табл. 3.14. MTTD реалізовано в `campaign_report.mttd`; Phase Excess і Geometry Excess — у `metrics/coordination.py`; sustain sensitivity — у `metrics/sustain.py`; FP і fleet-level mesh accounting — у `campaign_master.py`; інші trajectory-derived outcomes — у `metrics/derived.py`. Статистичні процедури визначені в `metrics/stats.py` і `campaign_stats.py`.

**Таблиця 3.14. Authoritative contract метрик comparative evaluation**

| Метрика | Операціональне визначення | Eligibility / знаменник | Подання і statistical status |
|---|---|---|---|
| Detection Rate | Наявність атрибутованої `security` event не раніше `inject_start` для атакованого UAV | Усі valid attack-runs відповідної cell | `k/n`, Wilson 95%; для запланованих H1 contrasts — Fisher exact, Newcombe CI і Holm correction |
| MTTD | Перша атрибутована `security` event мінус `inject_start` | Лише detected attack-runs | median [IQR] і n; Mann–Whitney лише exploratory; detector/cadence decomposition не входить до frozen analysis |
| Time to Isolation | Атрибутована `isolation_announce` мінус атрибутована detection event | У valid master 222 non-null; attack-response filter `valid & attack != none & non-null` дає n=220; дві baseline FP rows виключаються | median і range; без confirmatory test; не трактувати як фізичний containment time |
| Containment Success | Після attack onset жоден non-target UAV не перевищив 15 м off-plan | Усі 309 valid attack-runs із доступним спостереженням non-target UAV | `k/n`, Wilson 95%; не називати Isolation Success і не приписувати outcome лише isolation mechanism |
| Recovery Success | Off-plan deviation припинила зростати до кінця observation window | Усі 309 valid attack-runs | `k/n`, Wilson 95%; без окремого confirmatory inter-architecture test; не означає повне recovery |
| MTTR functional | Від isolation, а за її відсутності від attack onset, до початку фінального стабільного segment зі slope ≤ 0,5 м/с у 5-секундному вікні | Лише runs із знайденим стабільним segment; у frozen corpus n=267 | median [IQR] і n; conditional metric; не час повернення на маршрут |
| Stabilisation Level | Медіанний off-plan level після початку фінального стабільного segment мінус pre-attack baseline | Лише stabilized runs | median [IQR] і n; подавати разом із Recovery Success та MTTR functional |
| Mission Degradation | Максимальна post-attack distance-to-plan атакованого UAV мінус її медіана за 30 с до атаки | Усі 309 valid attack-runs | median [IQR] і n; bootstrap CI різниці медіан лише exploratory |
| Residual Mission Functionality | Частка спостережуваних UAV у межах 15 м від mission plan наприкінці trajectory series | Runs із придатними trajectory series | Значення для трьох UAV дискретні: 0,33/0,67/1,00; не трактувати як завершення місії або частку абстрактних функцій |
| Phase Excess | Post-attack peak розкиду накопиченого шляху відносно медіани рою мінус pre-attack peak | Attack n=309; full valid clean n=103 | median [IQR]; bootstrap contrasts exploratory; heavy clean tail описується явно |
| Geometry Excess | Post-attack peak зміни попарних відстаней відносно власної pre-attack медіани мінус pre-attack peak | Attack n=309; full valid clean n=103 | median [IQR]; bootstrap contrasts exploratory; не подавати як єдину normal scale |
| Total Response Time | Остання атрибутована recovery request/ack мінус attack onset | Лише C-runs із recovery event; frozen corpus n=88 | median і range; не порівнювати A/B/C і не переносити на attacks без recovery event |
| FP-run prevalence: clean flights | Наявність принаймні однієї FP event у штатному польоті | 35 clean flights на кожну архітектуру | `k/n`, Wilson 95%; Fisher contrasts exploratory |
| FP-run prevalence: all valid clean windows | Наявність принаймні однієї FP event у відповідному clean window | A/B/C = 136/140/138 valid windows | `k/n`, Wilson 95%; не об’єднувати з clean-flight exposure і не порівнювати event totals як rate |
| FP loop depth | Чи дійшла FP event chain до isolation і фактично виконаної recovery action | Positive FP cases; механістичний C-analysis має n=2 | Exploratory case analysis; не називати blast radius і не робити population-rate claim |
| Mesh Cost | Fleet-level published, delivered і dropped messages та application-payload bytes на run | Valid runs відповідної архітектури | mean ± sample SD і n; message-type composition не входить до frozen analysis |
| Sustain sensitivity | Offline replay правила `ratio > 1` для k послідовних samples | 45 GPS attack-runs і 105 clean flights | `k/n` з Wilson 95%; k=3 позначається як shipped, не optimal; formal hypothesis test не реалізовано |

> Для clean coordination основним reference corpus є `valid & attack == none`, n=103. Підкорпус `base_pass`, n=88, може наводитися лише окремо з явним фільтром і не підмінює загальний clean noise floor.
>
> MTTD decomposition, окремий R15 policy ablation і mesh message-type composition не входять до цього контракту та залишаються заблокованими до самостійного аудиту primary artefacts. Їх не можна вводити в главу 4 як похідні від authoritative CSV.
>
> Просторові outcome-метрики обчислюються за зовнішнім ground truth simulation environment. Monitor-generated diagnostic series використовуються для пояснення можливих механізмів, але не підміняють comparative trajectory outcomes, оскільки їх доступність залежить від того, чи зберігся відповідний monitoring process.

**Затрагиваемые таблицы и термины:** табл. 3.14; `Detection Rate`, `MTTD`, `Time to Isolation`, `Containment Success`, `Recovery Success`, `MTTR functional`, `Stabilisation Level`, `Mission Degradation`, `Residual Mission Functionality`, `Phase Excess`, `Geometry Excess`, `Total Response Time`, `FP-run prevalence`, `FP loop depth`, `Mesh Cost`, `Sustain sensitivity`; удаляются `Isolation Success Rate`, `False Positive Blast Radius`, `Phase Divergence`, `Geometry Deviation`, общий `False Negative Rate`.

**Почему это не подгонка теории под результаты:** definitions, eligibility rules и provenance воспроизводят фактический measurement contract. Патч не меняет thresholds после просмотра outcome direction и не добавляет unsupported decomposition. Числа относятся к corpus accounting и denominators; ни один observed effect size, p-value или архитектурное ранжирование в теоретический текст не переносится.

**Проверка соседних подразделов после патча:**

- 3.4.1–3.4.2 сохраняют теоретическую мотивацию пяти properties; новый 3.4.3 не сужает их, а разводит property и outcome.
- Табл. 3.10 из P2 использует те же authoritative metric names.
- Переход 3.5.3 → 3.5.4 остаётся логичным: injection cases сначала задают воздействие, затем contract задаёт измерение.
- Сохранённый ground-truth абзац p. 100 прямо поддерживает trajectory-derived definitions.
- P5 использует уже определённые здесь tests и не вводит новый metric post hoc.
- Глава 4 сможет ссылаться на одну таблицу definitions без повторного переопределения denominators.

---

## 4. Блок III. Гипотезы и допустимая сила выводов

### P4. Neutral claims: coverage ≠ speed, association ≠ component causality

**Закрывает:** A16, A22, A24, A31.

**Точное место в главе 3:**

1. 3.4.6, PDF p. 86: заменить абзац о том, что context sharing создаёт условия для «більш раннього виявлення».
2. 3.4.6, PDF p. 87: заменить абзац после табл. 3.10, начинающийся «Слід окремо зазначити, що координаційна цілісність…».
3. 3.5.3, PDF pp. 94–98: заменить methodological-purpose абзацы injection cases 4–5, где detector takeout назван ablation, изолирующей вклад context sharing, а monitor takeout — прямой component-level causal test.
4. 3.5.5, PDF p. 103: заменить абзац, начинающийся «У межах даної роботи логіка порівняння виходить з того…».

**Существующий смысл текста:** C ожидается раньше обнаруживающей, recovery action представляется причиной coordination trade-off, composite cases — как чистые ablations отдельных компонентов, а архитектурное преимущество — как ожидаемая комбинация лучших outcomes.

**Полный заменяющий фрагмент на украинском:**

#### Замена speed-утверждения в 3.4.6

> У proposed CSMA-конфігурації local-first detection доповнюється обміном security context і peer-position cross-check. Архітектурне очікування полягає в наявності додаткового detection path за компрометації локального detector або monitoring failure domain. Це очікування стосується detection coverage у визначених security-plane scenarios і не передбачає загальної переваги C за MTTD. Coverage та speed оцінюються окремими outcomes і не можуть підміняти одне одного.

#### Замена coordination-абзаца после табл. 3.10

> Coordination outcomes не розглядаються як монотонна функція архітектурної складності. У comparative design профіль поведінки формується повним поєднанням attack, detection path і action mapping. Ці компоненти не варіюються незалежно, тому observed association між малим mission damage та великим coordination excess не ідентифікує окрему recovery action як єдину причину. Висновки формулюються для повних конфігурацій і конкретних attack cells.

#### Замена methodological-purpose абзацев injection cases 4–5

> Detector takeout + position manipulation перевіряє, чи зберігає повна конфігурація додатковий detection path після деактивації local detectors атакованого UAV. Порівняння виконується на рівні architecture cells; воно не є component-level ablation, що окремо ідентифікує causal effect mesh, cross-check або recovery.
>
> Monitor takeout + position manipulation перевіряє залежність detection coverage від розміщення monitoring functions у спільному або розділених failure domains. Заплановані contrasts стосуються Detection Rate повних конфігурацій. Сценарій не призначений для доведення загальної переваги C над B або для оцінювання recovery actions.

#### Замена conclusion comparative logic в 3.5.5

> Proposed architecture оцінюється багатовимірно, але multidimensional evaluation не передбачає, що C повинна мати перевагу за кожною метрикою або в кожному scenario. Основний estimand — відмінність між повними A/B/C configurations у наперед визначених attack cells. Detection coverage, MTTD, containment, functional stabilisation, mission outcomes, coordination outcomes, FP behaviour і mesh cost подаються окремо. Допустимий архітектурний висновок має бути обмежений тими scenarios та outcomes, для яких його підтримують дані, і повинен включати null results та trade-offs.

**Затрагиваемые таблицы и термины:** заключение табл. 3.10; описания injection cases 4–5 и табл. 3.13; `earlier detection`, `coverage`, `speed`, `ablation`, `single point of failure`, `coordination trade-off`, `causal effect`, `general advantage`.

**Почему это не подгонка теории под результаты:** патч заранее ограничивает силу estimand тем, что позволяет comparative design. Он не заменяет неуспешную гипотезу на успешную после просмотра чисел, а разводит разные constructs и запрещает component-level causality, которую дизайн никогда не идентифицировал.

**Проверка соседних подразделов после патча:**

- Формулировка coverage согласуется с configuration table P2 и метриками P3.
- Пять injection cases из 3.5.3 сохраняются; изменяется только causal interpretation composite cases.
- P5 может задать H1 как coverage family без противоречия со speed wording.
- Заключение 3.5.5 не предвосхищает результаты главы 4 и допускает null/trade-off findings.

### P5. Явный статус H1 и единый statistical protocol

**Закрывает:** A30.

**Точное место в главе 3:** в начале 3.5.5, PDF p. 102, перед обновлённой comparative logic из P2/P4 вставить новый блок «Статус гіпотез і statistical protocol». Нумерацию последующих подразделов менять не требуется.

**Существующий смысл текста:** утверждается, что metric set сформирован до эксперимента, но отсутствует явное различие confirmatory и exploratory анализа. Это позволяет ошибочно назвать все hypotheses pre-registered или распространить multiplicity-controlled status H1 на остальные tests.

**Полный заменяющий фрагмент на украинском:**

> #### Статус гіпотез і statistical protocol
>
> Єдиною confirmatory family у цьому дослідженні є H1 щодо detection coverage за компрометації security plane. H1 була **pre-specified in version history before the authoritative master was versioned**, але не була pre-registered у зовнішньому registry. Це розмежування наводиться прямо і не замінюється терміном «pre-registration».
>
> H1 перевіряється чотирма запланованими pairwise contrasts: C–A та C–B у detector-takeout + GPS scenario, а також C–A та C–B у monitor-takeout + GPS scenario. Для кожної architecture cell Detection Rate подається як `k/n` із Wilson 95% CI. Для різниці proportions використовується Newcombe 95% CI, для hypothesis test — Fisher exact, а для family з чотирьох comparisons — Holm-adjusted p-values. Null comparison залишається частиною family і не вилучається з подання.
>
> Усі інші inferential comparisons мають exploratory status, якщо прямо не зазначено інше. Для них наводяться effect estimate, uncertainty interval, exact n і unadjusted p-value, а відсутність statistical significance не інтерпретується як доведена еквівалентність. MTTD comparisons, bootstrap contrasts mission/coordination outcomes, FP comparisons і sensitivity analyses не належать до H1 family.
>
> Позначення H2–H7 із робочої version history не мають статусу pre-registered hypotheses. Твердження про загальну перевагу C за detection speed, про Isolation Success як механізм, про перевагу mission outcomes у всіх attacks, про causal effect recovery action і про FP blast radius не використовуються як confirmatory hypotheses. Післядані descriptive або mechanistic questions можуть бути наведені лише з явною позначкою exploratory або post hoc.

**Затрагиваемые таблицы и термины:** начало 3.5.5; `H1`, `confirmatory family`, `pre-specified`, `pre-registered`, `exploratory`, `post hoc`, Wilson CI, Newcombe CI, Fisher exact, Holm correction; будущая confirmatory table главы 4.

**Почему это не подгонка теории под результаты:** патч раскрывает зафиксированную до versioning authoritative master историю H1 и не повышает статус остальных анализов. Null contrast сохраняется в family. Направление H1 и multiplicity correction не выбираются по observed values.

**Проверка соседних подразделов после патча:**

- H1 использует ровно те composite cases, которые описаны в 3.5.3.
- Термины Detection Rate и eligibility берутся из P3 без нового определения.
- P4 устраняет speed/causal claims, которые иначе конфликтовали бы со статусом H1.
- Обновлённая 3.5.5 сначала задаёт protocol, затем whole-configuration comparison logic; порядок методологически последовательный.

---

## 5. Блок IV. Ограничения и область применимости

### P6. Loss sweep как отдельный C-only sensitivity experiment

**Закрывает:** A25. Дополнительно обеспечивает совместимость с неблокирующей позицией A35, но A35 не входит в счёт 26 блокеров.

**Точное место в главе 3:**

1. 3.5.2, PDF p. 91: заменить абзац «Окремим параметром experimental setup є якість внутрішнього mesh-середовища…».
2. Табл. 3.11, PDF pp. 91–92: заменить строку «Керовані параметри середовища».
3. 3.5.6, PDF p. 104: заменить limitation-абзацы о simulation, PoC и attack set единым фрагментом ниже.

**Существующий смысл текста:** message loss выглядит как общая ось сравнения A/B/C и как приближение свойств реального FANET. Не сказано, что loss sweep относится только к C/cross-check, а A/B reference не являются точками того же sweep.

**Полный заменяющий фрагмент на украинском:**

#### Замена loss-sweep абзаца и строки табл. 3.11

> Окремий sensitivity experiment оцінює стійкість mesh-mediated detection до synthetic message loss. Він виконується лише для конфігурації C у detector-takeout + GPS scenario, де detection залежить від peer-position cross-check. Loss реалізовано як незалежне Bernoulli erasure для доставлених mesh frames; це наближення packet loss, а не фізична модель RF/FANET channel. Архітектури A і B не проходять той самий loss sweep. Якщо їхні main-campaign values використовуються як reference, вони маркуються як дані іншого experimental design, а не як точки loss-кривої.

**Новая строка табл. 3.11:**

| Параметр setup | Характеристика |
|---|---|
| Окремий mesh-loss sensitivity experiment | Лише C/cross-check у detector-takeout + GPS; synthetic Bernoulli erasure; per-level valid n подається окремо; A/B не є учасниками sweep |

#### Полная замена limitations в 3.5.6

> Evaluation обмежена simulation-only testbed із трьома UAV, coordinated waypoint mission, ZeroMQ/TCP як software approximation peer-to-peer mesh і одним фіксованим magnitude GPS offset. Network-layer communication disruption не відтворює фізичний RF jamming, а synthetic mesh loss не моделює reordering, corruption, interference або повну FANET dynamics.
>
> Main campaign порівнює bundled-конфігурації A/B/C і не ідентифікує causal effect окремого detector, mesh mechanism або recovery action. Loss sweep є окремим C-only sensitivity experiment для cross-check path; valid n може відрізнятися між loss levels і завжди наводиться біля відповідної оцінки та CI. A/B reference з main campaign не інтерпретуються як loss-sweep observations.
>
> PoC реалізує обмежене підмноження target architecture. Він не перевіряє alternative navigation, role redistribution, routing reconfiguration, full reintegration або загальну поведінку великого рою. Механістичні висновки, що спираються на малу кількість FP cases, подаються як exploratory case evidence, а не як population estimates.
>
> Область допустимого узагальнення обмежена п’ятьма реалізованими injection cases, їхніми validity rules, observation windows і measurement contract. Висновки не поширюються автоматично на інші spoof magnitudes, swarm sizes, physical channels, attack implementations або recovery policies.

**Затрагиваемые таблицы и термины:** табл. 3.11; 3.5.6 limitations; `loss sweep`, `C/cross-check`, `Bernoulli erasure`, `FANET`, `A/B reference`, `simulation-only`, `bundled configuration`, `generalisation`.

**Почему это не подгонка теории под результаты:** область sweep и channel model определяются фактическим experimental design. Патч не выбирает порог потерь и не объявляет trend; он заранее запрещает переносить C-only sensitivity curve на A/B или физический RF channel.

**Проверка соседних подразделов после патча:**

- 3.5.2 продолжает описывать общий main setup, а loss experiment явно вынесен как отдельная sensitivity axis.
- Injection case 3 остаётся adversarial communication disruption и не смешивается с ambient synthetic loss.
- Табл. 3.11 согласуется с future `fig4_1_losssweep`: одна C curve, A/B только внешний reference.
- Limitations повторяют boundary P1, bundled estimand P2 и metric eligibility P3, не вводя новых outcomes.

---

## 6. Порядок применения и контроль непротиворечивости

Рекомендуемый порядок будущего внесения правок в исходник главы 3:

1. **P1** — установить границу target architecture / PoC.
2. **P2** — зафиксировать фактические A/B/C и whole-configuration estimand.
3. **P3** — заменить все разрозненные definitions одним metric contract.
4. **P4** — убрать speed и component-causal ожидания.
5. **P5** — зафиксировать confirmatory/exploratory protocol.
6. **P6** — закрыть loss-sweep scope и общие limitations.

После применения каждого патча требуется текстовая проверка по следующим инвариантам:

- `coverage` нигде не используется как синоним `speed`;
- `Containment Success` нигде не называется `Isolation Success`;
- Time to Isolation нигде не трактуется как физический containment time;
- Recovery Success и MTTR нигде не означают route return или full recovery;
- Total Response Time нигде не используется для общего A/B/C comparison;
- A и B нигде не имеют automated recovery или security-context mesh;
- результат command-injection recovery относится полной C configuration;
- coordination trade-off нигде не приписан одной recovery action;
- `FP blast radius`, `Phase Divergence` и `Geometry Deviation` удалены из authoritative metric vocabulary;
- H1 названа pre-specified in version history, но не pre-registered;
- остальные inferential comparisons имеют exploratory status;
- loss sweep везде обозначен как C-only cross-check experiment;
- MTTD decomposition, R15 ablation и mesh message composition остаются заблокированными.

## 7. Проверка покрытия 26 блокеров

| ID | Патч | Контрольное место после правки |
|---|---|---|
| A04 | P1 | 3.1.7.1 и boundary 3.2.6 |
| A05 | P1 | 3.1.7.2 и boundary 3.2.6 |
| A06 | P1 | 3.1.7.3 и boundary 3.2.6 |
| A07 | P1 | 3.2.6 |
| A09 | P2 | 3.3.2–3.3.4, табл. 3.9 |
| A10 | P2 | табл. 3.9–3.10, conclusion 3.4.6 |
| A12 | P3 | 3.4.3–3.4.5, табл. 3.14 |
| A13 | P3 | 3.4.3–3.4.5, табл. 3.14 |
| A14 | P3 | 3.4.4, табл. 3.14 |
| A15 | P3 | 3.4.3–3.4.5, табл. 3.14 |
| A16 | P4 | 3.4.6 |
| A17 | P3 | табл. 3.14 |
| A18 | P3 | табл. 3.14 |
| A19 | P3 | 3.4.3, табл. 3.14 |
| A20 | P3 | 3.4.3, табл. 3.14 |
| A21 | P3 | 3.4.3, табл. 3.14 |
| A22 | P4 | conclusion табл. 3.10 |
| A23 | P2 | 3.5.2 и 3.5.5 |
| A24 | P4 | 3.5.3, cases 4–5 |
| A25 | P6 | 3.5.2, табл. 3.11, 3.5.6 |
| A27 | P3 | 3.5.4, corpus and eligibility |
| A28 | P3 | 3.5.4, blocked analyses note |
| A29 | P3 | табл. 3.14, Mesh Cost |
| A30 | P5 | начало 3.5.5 |
| A31 | P4 | conclusion 3.5.5 |
| A36 | P3 | табл. 3.14, Sustain sensitivity |

Все 26 блокирующих ID покрыты ровно один раз. Позиции со статусом «исправить до финальной сборки» и «не требует правки» не включены в обязательный счёт; P1 и P6 лишь обеспечивают с ними соседнюю согласованность там, где это необходимо.

На этом patch plan завершён. Диссертация и её исходники не редактировались.
