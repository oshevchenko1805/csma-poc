# Chapter 4 Source Inventory

Дата инвентаризации: 2026-08-05

Репозиторий: `/Users/vsemerenska/Documents/csma/csma-poc`

Назначение: зафиксировать допустимые источники и воспроизводимую цепочку происхождения результатов до написания главы 4. Это не текст главы.

## 1. Repository state и frozen boundary

- Текущая ветка: `main`, upstream `origin/main`, расхождение `+0/-0`.
- Рабочее дерево до создания файлов этой инвентаризации было чистым.
- `HEAD`: `b6f75d45e690a1747adcd583899d0d8228822db4` (`docs: freeze audited chapter 3`).
- Frozen results commit: `7451258c152409775896faa52e57b6b8d75c076b` (`docs: freeze audited dissertation results`).
- `7451258` является предком `b6f75d4`; оба являются предками текущего `HEAD`.
- Аудит в `FINAL_RESULTS_AUDIT.md` выполнен на состоянии `f507ba422add4e7a16bfaad91981483e3116b487`.
- Между `f507ba4` и `7451258` добавлен только `FINAL_RESULTS_AUDIT.md`; data, analysis code и figures не менялись.
- Между `7451258` и `b6f75d4` добавлены только frozen Chapter 3 DOCX/PDF и audit/patch records в `thesis_text/`; data, analysis code и figures не менялись.

Следовательно, числовые данные, статистические процедуры и frozen figures в `b6f75d4` побайтово соответствуют состоянию, на котором выполнен results audit; `b6f75d4` добавляет замороженный metric contract главы 3.

## 2. Normative writing gate и иерархия доказательных и provenance-источников

### 2.1 Normative writing authority

> **Нормативним джерелом числових значень, статистичного статусу та допустимих інтерпретацій для тексту розділу 4 є `FINAL_RESULTS_AUDIT.md`. CSV та код є первинними артефактами provenance і можуть використовуватися для перевірки аудованих результатів, але не для введення нових чисел, тестів або claims без окремого аудиту та заморожування.**

Практическое следствие: отсутствие значения, test result или claim в frozen audit нельзя автоматически восполнять расчётом из master, loss CSV, FP census или кода. Для такого дополнения сначала требуется отдельный audit addendum с явными filters, denominators, statistical status и frozen output. Это правило распространяется в том числе на попытки построить «полные» таблицы MTTD и Stabilisation Level.

### 2.2 Иерархия доказательных и provenance-источников

После применения normative writing gate provenance проверяется в следующем порядке:

1. `runs_campaign/campaign_master.csv`;
2. `runs_final/detection_vs_loss.csv`;
3. `runs_campaign/fp_census.csv`;
4. определения и accounting в `metrics/derived.py`, `campaign_report.py`, `metrics/coordination.py`, `metrics/sustain.py`, `campaign_master.py`; статистические процедуры в `metrics/stats.py` и `campaign_stats.py` с оговоркой в разделе 4;
5. `thesis_text/Thesis Draft Semerenska-7_ch3_frozen.docx` и `thesis_text/CH3_FINAL_REGRESSION_REVIEW.md` как источник metric contract, eligibility rules и границ интерпретации;
6. committed figure source data и scripts только в роли, указанной ниже.

Handoff-, notes- и candidate-файлы не являются writing authority или primary provenance. Их можно использовать только для навигации или истории решений после обязательной сверки с `FINAL_RESULTS_AUDIT.md` и соответствующими provenance-артефактами.

## 3. Primary provenance data

| Файл | Гранулярность и роль | Проверенный объём | SHA-256 | Допустимое использование |
|---|---|---:|---|---|
| `runs_campaign/campaign_master.csv` | Одна строка на попытку основной кампании; provenance, validity, detection/response, mission, coordination, sustain, mesh и FP fields | 435 строк данных, 47 колонок; 435 уникальных `run_id`; 414 valid, 20 errored, 1 `attack_did_not_land` | `158e57743bceb9c1899805a90fa7065b8e8470213c4c1f30bf15591e4ac282d9` | Primary provenance artifact для проверки frozen cell- и architecture-level результатов; не разрешает вводить новые числовые клетки, tests или claims без audit addendum |
| `runs_final/detection_vs_loss.csv` | Одна строка на configured mesh-loss level в отдельном C-only sensitivity experiment | 10 уровней; 255 valid belief-gated runs, 166 detections, 5 `no_attack`, 4 errors | `5ada30d0b01d304257574da7ad958084f43623c40634a11ac6a3dc01cf53e54a` | Primary provenance для frozen R4/Fig. 4.1; `n` каждой строки является отдельным знаменателем, но новые summaries/tests требуют отдельного audit addendum |
| `runs_campaign/fp_census.csv` | Одна строка на положительный FP-run; детальная глубина event chain | 17 строк, 17 уникальных FP-runs; файл содержит только положительные случаи | `7f6aceb08e8337e42d3fe0af1758ebb656d7a8e2b6bee8be8ca18caddc3d8b3f` | Primary provenance для frozen FP loop-depth claims; prevalence denominators берутся из master, а новые claims требуют отдельного audit addendum |

### 3.1 Проверенный corpus flow основной кампании

- Все попытки: 435.
- Valid: 414.
- Errored: 20.
- Gated out: 1 (`attack_did_not_land`).
- Valid clean flights: 105, по 35 на A/B/C.
- Valid attack-runs: 309; A/B/C = 101/105/103.
- Valid total A/B/C = 136/140/138.
- Все 435 строк имеют `post_fix == True`.
- Non-null в valid master: MTTD 223, Time to Isolation 222, MTTR 267, Total Response Time 88.
- Attack-response Time to Isolation после исключения baseline FP rows: n=220.

Число `657 runs on disk` не выводится из локального authoritative corpus и не используется. Допустимый поток: `435 -> 414 = 20 errored + 1 gated out`.

## 4. Frozen statistical outputs и statistical procedures

### 4.1 Frozen output

`FINAL_RESULTS_AUDIT.md` — единственный committed frozen statistical/numerical output, который одновременно содержит:

- metric contract;
- проверенные знаменатели;
- R1–R13 с точными summary statistics;
- Wilson CI, Fisher exact, Newcombe CI, Holm-adjusted p-values;
- exploratory Mann–Whitney и seeded bootstrap results;
- статус H1–H7;
- реестр запрещённых интерпретаций и устаревших вторичных чисел;
- окончательный набор figures/tables и обязательных limitations.

Файл добавлен commit `7451258`; SHA-256: `072e715d7d7894fe7d72794b47b471a1f3866c910077798a770ca10fa9956ca8`.

### 4.2 Statistical code

| Файл | Роль | SHA-256 | Статус для главы 4 |
|---|---|---|---|
| `metrics/stats.py` | `wilson_bounds`, two-sided Fisher exact, Newcombe hybrid-score CI, Mann–Whitney U, seeded bootstrap difference of medians, Holm adjustment | `d9f07c97d1e7218ec5bcf3c8db2d9f4966d9eca0f4c631c1e90b0f3fa1ac4638` | Authoritative procedure library |
| `campaign_stats.py` | Объявляет H1 family и печатает confirmatory/exploratory comparisons | `3f8cb382eb3bedcee430fb65ddff0dd0593643bed5e2e501e6c05fcf8eb3e3f` | Procedural provenance, но CLI читает raw run directories через `campaign_report.collect`, а не master |
| `tests/test_stats.py` | Unit tests statistical primitives | tracked | Проверка реализации; не источник numerical results |
| `tests/test_sustain.py` | Unit tests sustain replay logic | tracked | Проверка реализации; не источник numerical results |

В репозитории нет отдельного machine-readable frozen файла с итогами inferential tests. Точные statistical results заморожены в `FINAL_RESULTS_AUDIT.md`. Согласно его §6.15, финальные inferential values должны пересчитываться из `campaign_master.csv` функциями `metrics.stats`, а не приниматься из stdout `campaign_stats.py` без сверки. Read-only пересчёт H1 family из master воспроизвёл все четыре frozen comparisons, включая null C–B при monitor takeout.

## 5. Metric derivation и accounting provenance

| Outcome / слой | Authoritative fields | Definition / generation code | Обязательный filter contract |
|---|---|---|---|
| Detection Rate | `detected` | `metrics/derived.py`, `campaign_report.py`, перенос через `campaign_master.py` | `valid == True & attack != none`, затем конкретные `architecture × attack` cells |
| MTTD | `mttd_s` | `campaign_report.mttd`, перенос через `campaign_master.py` | Только detected attack-runs; pre-attack events и события о другом UAV не атрибутируются атаке |
| Time to Isolation | `time_to_isolation_s` | `metrics/derived.py` | `valid == True & attack != none & time_to_isolation_s.notna()`; n=220 |
| Containment Success | `containment_success` | `metrics/derived.py` | Valid attack-runs с наблюдаемыми non-target UAV; здесь n=309 |
| Recovery Success | `degradation_stopped` | `metrics/derived.py` | Все valid attack-runs соответствующей cell |
| MTTR functional | `mttr_functional_s` | `metrics/derived.py` | Только runs с найденным финальным стабильным segment |
| Stabilisation Level | `stabilisation_level_m` | `metrics/derived.py` | Только stabilized runs |
| Mission Degradation | `mission_degradation_m` | `metrics/derived.py` | Все valid attack-runs; external Gazebo trajectory ground truth |
| Residual Mission Functionality | `residual_mission_func` | `metrics/derived.py` | Runs с пригодными trajectory series |
| Phase/Geometry Excess | `phase_excess_m`, `geometry_excess_m` | `metrics/coordination.py`, перенос через `campaign_master.py` | Attack: valid attack-runs; clean reference: `valid == True & attack == none` и non-null fields |
| Total Response Time | `total_response_time_s` | `metrics/derived.py` | Только C-runs с recovery request/ack; n=88 |
| Sustain sensitivity | `ratio_maxcons_post`, `ratio_maxcons_full_fleet` | `metrics/sustain.py`, materialization в `campaign_master.py` | GPS attack post-window n=45; clean full-series fleet window n=105 |
| Mesh Cost | `mesh_pub_msgs`, `mesh_pub_bytes`, `mesh_del_msgs`, `mesh_drop_msgs` | fleet accounting в `campaign_master.py` | Все valid runs соответствующей architecture: A/B/C = 136/140/138 |
| FP prevalence | `fp_events_clean`, per-detector columns | clean-window accounting в `campaign_master.py` | Раздельно `clean_flight` и `pre_attack`; prevalence denominator только из master |
| FP loop depth | detailed event-chain columns | `metrics/fp_census.py` | Только positive FP-cases; C mechanism n=2 |

Ключевые code hashes, уже зафиксированные аудитом:

- `metrics/derived.py`: `da328262bb2f6441a3493f66adbd5869fc1599a4214509bc6203180c89ba9049`;
- `metrics/stats.py`: `d9f07c97d1e7218ec5bcf3c8db2d9f4966d9eca0f4c631c1e90b0f3fa1ac4638`;
- `campaign_stats.py`: `3f8cb382eb3bedcee430fb65ddff0dd0593643bed5e2e501e6c05fcf8eb3e3f`.

## 6. Frozen Chapter 4 figures

Все четыре figures tracked и идентичны в commits `7451258` и `b6f75d4`. Единая точка сборки — `metrics/figures_ch4.py` (`python -m metrics.figures_ch4`). На этом этапе генератор не запускался и frozen files не перезаписывались.

| Figure | Frozen files и SHA-256 | Numerical/source data | Generation path | Допустимая функция в главе |
|---|---|---|---|---|
| Fig. 4.1, loss sweep | PNG `a0696f07b5bf1d736bc3086d3894da8f591ed0a38118a047f60524916c8d1cce`; PDF `40d4b2851cdc73d224b962d406d4082d266c636442eee0d4add394e626bd622f` | `runs_final/detection_vs_loss.csv`; A/B 0/28 и 0/30 только как explicitly labelled reference из main campaign | `metrics/figures_ch4.py` -> `metrics.plots_extra.fig_loss_sweep`; raw loss CSV generator: `scripts/analyze_loss_sweep.py` | C-only loss-sensitivity, Wilson CI и per-level n; не строгая монотонность и не A/B loss experiment |
| Fig. 4.2, sustain | PNG `d303c8790d0da71dbaa33d65e84d863168e43e0e5de4d2a95a0d6e44500f9b3e`; PDF `00d6c8ee62b2e8576d74f1e69411d3531b4c7da502a7523d024c0ca41c191791` | `campaign_master.csv`: GPS `ratio_maxcons_post`, clean `ratio_maxcons_full_fleet` | `metrics/figures_ch4.py` -> `metrics.plots.fig_sustain`; replay definition in `metrics/sustain.py` | Offline local-detector sensitivity; k=3 = shipped, не optimal; не architecture Detection Rate |
| Fig. 4.3, tracks | PNG `c758009ae7ad0b9c0c830f23ff0b86547d0f3d2b4892458886c5086dd835f6ff`; PDF `0eca090aa4bc20da85ce0e343e2a0931227cb7cc27db29d5a7093484839f10bf` | `campaign_master.csv` для deterministic median-nearest selection + шесть raw bundles в `figdata/` | `metrics/figures_ch4.py` -> `metrics.plots_tracks.build` | Иллюстрация физического механизма для GPS spoofing и command injection; runs непарные, causal proof запрещён |
| Fig. 4.4, trade-off | PNG `0ec083a0669fa900573c5e539fbc4cf3ec2450898a50220a56a5ce3aaa4c4ded`; PDF `6fae2027b063a431161d7422622b62cdfa4718c8329ac9a59380ff2d4347143b` | `campaign_master.csv`: `mission_degradation_m`, `phase_excess_m`, valid attack-runs | `metrics/figures_ch4.py` -> `metrics.plots_tradeoff.fig_tradeoff` | Raw runs + cell medians/IQR; 49.8 m = injection ceiling; attack, detection path и action confounded |

Visual inspection текущих PNG подтвердила заявленную компоновку: Fig. 4.1 содержит одну C curve и A/B caveat; Fig. 4.2 — две панели с n=45 и n=105; Fig. 4.3 — 2x3 tracks grid; Fig. 4.4 — linear-axis run-level trade-off scatter.

## 7. Figure source data (`figdata/`)

`figdata/runs_campaign/` содержит 24 committed run bundles:

- 17 bundles соответствуют всем 17 строкам `fp_census.csv` и дают event-level source для `metrics/fp_census.py`;
- 6 bundles являются текущими median-nearest sources Fig. 4.3;
- 1 bundle (`C_gps_spoofing_r3_1785309732`) не используется текущими FP census или Fig. 4.3 и не должен становиться источником нового claim без отдельного назначения.

Точные Fig. 4.3 runs:

| Attack | A | B | C |
|---|---|---|---|
| GPS spoofing | `figdata/runs_campaign/gps_pass1/run_A_gps_spoofing_r4_1785562555` | `figdata/runs_campaign/gps_pass1/run_B_gps_spoofing_r2_1785563219` | `figdata/runs_campaign/std_pass1/run_C_gps_spoofing_r1_1785309289` |
| Command injection | `figdata/runs_campaign/ci_pass2/run_A_command_injection_r2_1785408959` | `figdata/runs_campaign/ci_pass1/run_B_command_injection_r4_1785407548` | `figdata/runs_campaign/ci_pass1/run_C_command_injection_r1_1785395502` |

Для каждого из шести bundles присутствуют `run_summary.json`, `merged.jsonl` и `trajectory.jsonl`. Selection rule воспроизведён из master: ближайший к median `mission_degradation_m` run в каждой `architecture × attack` cell с tie-break по `run_id`.

## 8. Generation scripts inventory

| Artifact | Script(s) | Local reproducibility status |
|---|---|---|
| `campaign_master.csv` | `campaign_master.py`; upstream definitions `campaign_report.py`, `metrics/derived.py`, `metrics/coordination.py`, `metrics/sustain.py` | Полный rebuild из checkout невозможен: 435 raw campaign run directories не закоммичены. Frozen CSV и его hash являются authoritative snapshot |
| `detection_vs_loss.csv` | `scripts/analyze_loss_sweep.py` | Полный rebuild из checkout невозможен: raw `runs_sweep` corpus не закоммичен. Frozen CSV и его hash являются authoritative snapshot |
| `fp_census.csv` | `metrics/fp_census.py` | Rebuild возможен из master + всех 17 committed FP bundles |
| Statistical tests | `metrics/stats.py`; reporting/provenance `campaign_stats.py` | Functions и master доступны; frozen exact results находятся в `FINAL_RESULTS_AUDIT.md`. Raw-root CLI `campaign_stats.py` не является локально self-contained |
| Four Chapter 4 figures | `metrics/figures_ch4.py`; `metrics/plots.py`, `metrics/plots_extra.py`, `metrics/plots_tracks.py`, `metrics/plots_tradeoff.py`, `metrics/style.py` | Rebuild возможен из committed master/loss CSV/figdata; на этом этапе не запускался, чтобы не перезаписывать frozen artifacts |

`metrics/plots_regime.py` и rejected 5x3 regime map не входят в frozen figure set. Другие plot functions в `metrics/plots.py`/`metrics/plots_extra.py` не становятся источниками Chapter 4 автоматически.

## 9. Frozen Chapter 3 metric contract

Authoritative methodology sources:

- `thesis_text/Thesis Draft Semerenska-7_ch3_frozen.docx`, SHA-256 `044f1cf77e1d5ea9073bccb86012d6a18847e8bf4cd957feb6b192906ef02460`;
- `thesis_text/CH3_FINAL_REGRESSION_REVIEW.md`, SHA-256 `d4261b4d3f56b3898454362b6cb7a2ac4b8b5702b542f589193bdfa7bc3c6f46`.

Контракт находится в §3.5.4, Table 3.14; comparison/statistical logic — в §3.5.5 и Table 3.15; ограничения — в §3.5.6. Обязательные invariants для главы 4:

1. Для каждой метрики указать operational definition, eligibility filter, denominator, summary statistic, uncertainty/test и statistical status.
2. Fixed timing `90/60/150 s` задаёт общее observation window, но не общий denominator.
3. Detection coverage и MTTD/speed не взаимозаменяемы.
4. Time to Isolation не является временем физического containment; `Containment Success` нельзя переименовывать в `Isolation Success`.
5. Recovery Success, MTTR functional и Stabilisation Level подаются совместно; стабилизация не означает возврат на маршрут или завершение миссии.
6. Residual Mission Functionality не означает mission completion.
7. Phase Excess и Geometry Excess не являются off-plan distance и не образуют единую normal scale; clean heavy tail раскрывается явно.
8. Total Response Time — C-only conditional metric, а не общая A/B/C latency.
9. H1 family pre-specified in version history before versioning authoritative master, но не pre-registered; все остальные inferential comparisons exploratory, post hoc или descriptive.
10. A/B/C — bundled configurations; component-level causal claims о mesh, self-healing или recovery action без ablation запрещены.
11. Loss sweep — только C/cross-check; два верхних уровня имеют n=12 и широкие CI.
12. Обязательные external-validity limits: simulation-only, три UAV, ZeroMQ/TCP mesh approximation, один GPS offset 50 m, пять injection cases.

`CH3_FINAL_REGRESSION_REVIEW.md` подтверждает `36/36` alignment invariants и `9/9` regression requirements; blocked MTTD decomposition, policy ablation и message-type composition отсутствуют в frozen Chapter 3.

## 10. Excluded and contextual-only material

Не использовать как источник чисел или claims:

- `HANDOFF*.md`, включая `HANDOFF_CH45.md`, `HANDOFF_FIGURES.md` и архивные handoffs;
- `RESULTS_NOTES.md`, `FINDINGS_AND_FIGURES.md`, `CH45_QUESTIONS_ANSWERS_FIGURES.md`;
- `HYPOTHESES_DRAFT.md`;
- `FIGURE_SPECS.md` для чисел: допустим только как исторический контекст формы подачи после сверки с audit;
- промежуточные/candidate документы в `thesis_text/`; authoritative text — только `Thesis Draft Semerenska-7_ch3_frozen.docx` плюс final regression review;
- `runs_v2/report/*`, `runs_v3/report/*` и старые `runs_v2/run_*`, `runs_v3/run_*` как финальные Chapter 4 results;
- rejected regime map и любые прежние figures вне frozen four-figure set;
- unreferenced `figdata` bundle как самостоятельное основание нового результата.

## 11. Explicitly blocked claims

До отдельного primary-artifact audit запрещены как количественные и качественные доказательства:

1. MTTD decomposition;
2. policy ablation `36.65/1.34 m`;
3. mesh message-type composition `39,198/486`.

В `campaign_master.csv` отсутствуют поля, позволяющие воспроизвести эти claims. Для разблокировки каждого требуются конкретный primary artifact, явный population/eligibility filter, denominator и воспроизводимый calculation script.

## 12. Reproducibility boundary

Локально полностью воспроизводимы:

- все denominators и summaries из `campaign_master.csv`;
- loss-sweep figure и таблица из `detection_vs_loss.csv`;
- FP census из master + committed positive-case bundles;
- четыре frozen figures из committed source artifacts;
- inferential procedures из master + `metrics/stats.py`.

Локально не воспроизводимы с самого сырого уровня:

- rebuild `campaign_master.csv` из всех 435 raw runs;
- rebuild `detection_vs_loss.csv` из raw loss-sweep runs;
- directory census `657 -> 435`;
- три explicitly blocked claims.

Эта граница не блокирует планирование главы 4, поскольку audited CSV snapshots заморожены и совпадают с hashes, но должна быть сохранена в provenance note и не замещаться старыми secondary files.

## 13. Предлагаемая структура главы 4

Структура следует пяти security properties главы 3 и отделяет confirmatory result от exploratory/descriptive material.

### 4.1. Корпус данных, validity flow и правила анализа

- frozen boundary и authoritative artifacts;
- поток `435 -> 414`;
- различие main campaign, C-only loss sweep и FP positive-case census;
- metric-specific denominators и fixed observation window;
- таблица corpus/eligibility; при необходимости data-flow diagram без новых чисел.

### 4.2. Detection capability

- 4.2.1. Detection Rate по пяти attack cells;
- 4.2.2. Confirmatory H1 family для detector/monitor takeout, включая null C–B;
- 4.2.3. Conditional MTTD как отдельная descriptive/exploratory metric;
- 4.2.4. Граница mesh-mediated detection при loss — Fig. 4.1;
- 4.2.5. Sustain-rule sensitivity — Fig. 4.2.

### 4.3. Isolation и containment

- event-level Time to Isolation;
- trajectory-level Containment Success;
- C-only Total Response Time как отдельная conditional event-chain metric;
- отсутствие подмены containment термином Isolation Success.

### 4.4. Recovery и mission resilience

- Recovery Success, MTTR functional и Stabilisation Level в одной таблице;
- command-injection result для полных configurations;
- spoofing saturation caveat;
- Mission Degradation и Residual Mission Functionality;
- median-nearest trajectories — Fig. 4.3 только как mechanistic illustration.

### 4.5. Coordination integrity и наблюдаемый trade-off

- Phase Excess и Geometry Excess;
- clean coordination reference и heavy-tail caveat;
- scenario-specific trade-off между mission degradation и phase divergence — Fig. 4.4;
- explicit confounding attack/detection/action.

### 4.6. Architectural cost и false-positive behaviour

- fleet-level Mesh Cost как descriptive overhead;
- FP prevalence отдельно для clean flights и всех valid clean windows;
- FP loop depth как n=2 exploratory mechanism для C;
- message-type composition не включается.

### 4.7. Синтез результатов и ограничения применимости

- частичная поддержка H1 и null result;
- H2–H7 только в audited status;
- отсутствие общего superiority claim для C;
- bundled-configuration и external-validity limitations;
- итог формулируется как scenario-conditional coverage/resilience trade-off, без component-level causal claims.

Детальная claim-to-evidence привязка и проверка согласованности с Table 3.14 находятся в `thesis_text/CH4_CLAIM_EVIDENCE_MATRIX.md`.
