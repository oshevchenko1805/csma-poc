# Chapter 4 Reporting Frame

Дата: 2026-08-05

Frozen results boundary: `7451258`

Frozen Chapter 3 boundary: `b6f75d4`

Статус: внутрішній reporting-control file. Не є частиною дисертаційного тексту.

## 1. Narrative principle

Головна лінія розділу 4:

> **Стійкість архітектури залежить від того, яка інформація про атаку збереглася, який detection path залишається працездатним і яку response action можна безпечно виконати.**

Основне дослідницьке припущення стосується збереження detection coverage за наявності незалежного detection path. Інші результати подаються як виявлені закономірності, аналітичні висновки та узагальнення, а не як ретроспективно сформульована система гіпотез.

Стандартний narrative unit:

1. результат;
2. його науковий зміст;
3. одна межа інтерпретації лише там, де без неї змінюється значення результату.

## 2. Normative writing gate

Нормативним джерелом числових значень, statistical status і допустимих інтерпретацій є `FINAL_RESULTS_AUDIT.md`. `CH4_CLAIM_EVIDENCE_MATRIX.md` визначає 25 дозволених claims та їхні metric-specific populations. CSV і generation code є provenance-артефактами й не дозволяють додавати нові числа, tests або claims без окремого frozen audit addendum.

Незмінні contract rules:

- Detection Rate і conditional MTTD подаються окремо;
- attack-response Time to Isolation використовує n=220;
- Total Response Time є C-only conditional metric з n=88;
- Recovery Success читається разом із MTTR functional, Stabilisation Level і Mission Degradation;
- full clean coordination reference має n=103, а base-pass n=88 є sensitivity subset;
- дві FP exposure populations не об'єднуються;
- A/B/C є bundled configurations;
- comm disruption і C–B при monitor takeout залишаються обов'язковими null results.

## 3. Statistical reporting status

| Result block | Population / analysis | Internal status | Main-text treatment |
|---|---|---|---|
| Standard attack Detection Rate | GPS spoofing, comm disruption, command injection cells | descriptive cell estimates; cross-architecture tests exploratory | усі configurations мали високу coverage; architecture differences emerged under security-plane compromise |
| Takeout Detection Rate | C–A і C–B у detector- та monitor-takeout cells | confirmatory family of four pre-specified contrasts; not preregistered | основне дослідницьке припущення підтримано частково; null C–B monitor contrast залишається в тексті |
| B–A monitor-takeout comparison | окремий Fisher comparison | exploratory | допоміжний результат, не частина confirmatory family |
| Conditional MTTD | detected runs only | descriptive medians; Mann–Whitney comparisons exploratory and uncorrected | coverage є основним architecture-separating result; conditionality зазначається один раз |
| Mesh-loss sensitivity | C/cross-check only | exploratory sensitivity; per-level estimates descriptive | boundary of mesh-mediated detection; no formal trend test |
| Sustain sensitivity | local GPS detector, offline/prospective | descriptive sensitivity | shipped k=3 лежить на observed plateau k=2–4 |
| Containment Success | all valid attack-runs | descriptive | більшість runs contained; architecture aggregates are close |
| Time to Isolation | eligible attack-response rows, n=220 | descriptive | local dispatch timing у десятках microseconds |
| Total Response Time | eligible C-runs, n=88 | descriptive conditional | event-chain timing лише для C-runs із recovery events |
| Command-injection recovery | all cell runs for rate; stabilized for MTTR | descriptive, post hoc | C припинила off-plan growth у 14/15 runs у межах observation window |
| Spoofing recovery | rate for all valid; MTTR/level for stabilized | descriptive | рівень стабілізації розрізняє saturation near offset ceiling і lower-deviation C profiles |
| Mission Degradation | architecture × attack cells | descriptive medians; seeded bootstrap contrasts exploratory and uncorrected | lower observed C medians in four scenarios; comm disruption null |
| Residual Mission Functionality | all valid attack-runs; key C detector cell | descriptive | end-state route proximity must be read with phase integrity |
| Representative trajectories | six median-nearest runs | illustrative/descriptive | mechanism illustration, not an inferential result |
| Coordination profiles | attack cells | descriptive medians; seeded bootstrap contrasts exploratory and uncorrected | information–detection–response profiles produce different route/coordination trade-offs |
| Clean coordination reference | full clean corpus n=103; base-pass sensitivity n=88 | descriptive | typical background is small with heavy tails |
| Joint trade-off figure | valid attack-runs | exploratory synthesis | one point per run; reference level 49.8 m; action contribution not independently identified |
| Mesh Cost | all valid runs per architecture | descriptive mean ± sample SD | measured three-UAV implementation cost; A/B structural zeros |
| FP prevalence: clean flights | 35 per architecture | descriptive prevalence; Fisher tests exploratory | observed C 0/35 with no statistical evidence of prevalence difference |
| FP prevalence: all clean windows | A/B/C n=136/140/138 | descriptive incidence; Fisher tests exploratory | separate mixed-exposure population; no rate-per-time claim |
| FP loop depth | positive FP census n=17; C mechanism n=2 | exploratory case analysis | C response chain reached executed recovery in two observed cases; no population or blast-radius claim |

## 4. Main-text caveat budget

Окрему межу інтерпретації потрібно залишати поруч лише з такими результатами:

1. conditional MTTD — defined only among detected runs;
2. recovery — stabilization is not equivalent to full mission restoration;
3. configuration comparisons — action contribution is not independently identified;
4. comm disruption — exploratory null result;
5. monitor takeout C–B — confirmatory null result;
6. FP loop depth — C mechanism is based on n=2.

Інші methodological details залишаються у таблицях, примітках і цьому internal reporting frame, щоб основний текст зберігав послідовну наукову аргументацію.

## 5. Synthesis frame for §4.7

1. **Збереження detection coverage.** Висока coverage у стандартних scenarios; differences emerge when security plane is compromised; independent path determines which configurations remain effective.
2. **Зменшення Mission Degradation і рівень стабілізації.** Four-of-five scenario pattern; command-path and takeout profiles show lower-deviation stabilization when a safe response can be executed.
3. **System relationship information–detection–response.** Preserved information determines detection path; detection path constrains safe action; action profile shapes route protection versus coordination integrity.
4. **Operational cost and FP response-chain effects.** Additional resilience is accompanied by measured mesh overhead and a response chain that can reach recovery on false positives.
5. **Short limitations paragraph.** Simulation-only, three UAV, bundled configurations, one 50 m offset, C-only loss sweep, representative trajectories unpaired.

Target conclusion:

> **Архітектура C забезпечує додаткову стійкість тоді, коли скомпрометовано площину безпеки або командний канал, однак характер виграшу залежить від того, яка інформація збереглася та яку дію реагування можна безпечно виконати.**
