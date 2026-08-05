# CH3 semantic conservation audit

Дата відновлення контрольного артефакту: 2026-08-05  
Об’єкт контролю: глава 3 дисертації  
Authoritative basis: `FINAL_RESULTS_AUDIT.md`, frozen results, commit `7451258`

## Статус і provenance

Цей файл додано до repository audit package, оскільки окремий `CH3_SEMANTIC_CONSERVATION_AUDIT.md`, на який посилався `CH3_FINAL_PATCH_LOG.md`, був відсутній у доступному пакеті. Це **відновлена контрольна копія**, а не заява про byte-identical відтворення раніше створеного файла. Вимоги R1–R9 реконструйовано лише з `CH3_FINAL_PATCH_LOG.md`, `CH23_ALIGNMENT_WITH_FROZEN_RESULTS.md`, frozen audit commit `7451258` та незалежного ревью фактичного DOCX. Старі handoff-файли не використовувалися як джерело чисел, визначень або statistical status.

## Незмінні semantic invariants

1. Наукова логіка повинна зберігати послідовність: наукова прогалина → target architecture → PoC boundary → baselines → experimental design → metrics → hypotheses.
2. Target architecture, реалізований PoC і фактичні outcomes не є взаємозамінними рівнями опису.
3. A/B/C є повними bundled-конфігураціями; component-level causal effect не ідентифікується без окремого ablation design.
4. Detection coverage не підміняється detection speed.
5. `isolation_announce` є event-level timing і не означає фізичний containment.
6. Recovery Success, MTTR functional і Stabilisation Level не доводять повне повернення на маршрут, завершення місії або повну реінтеграцію.
7. Єдине observation window не створює єдиного знаменника: eligibility filters і denominators залишаються metric-specific.
8. Реалізовані corpus sizes, conditional n і factual outcomes належать главі 4, крім чисел, необхідних для limitation statement або pre-specified statistical protocol.
9. Python module names, internal audit-log language і заблоковані analytical claims не належать основному науковому тексту.

## Реєстр R1–R9

| ID | Обов’язковий semantic requirement | Acceptance criterion |
|---|---|---|
| R1 | Відновити теоретичне обґрунтування centralized baseline | §3.3.2 пояснює monitoring/C2 trust assumption і роль reference model; external recovery не приписується конфігурації A |
| R2 | Відновити теоретичне обґрунтування distributed baseline | §3.3.3 пояснює local monitoring і усунення спільного monitoring failure domain; shared security context і closed recovery loop не приписуються B |
| R3 | Перейти від обіцянки formal definitions до operationalization | Назва §3.4 і переходи використовують `operationalization` / `операціоналізовані security properties`; stale `formal properties` відсутні |
| R4 | Зберегти повний підсумок §3.4 | §3.4.7 містить literature-grounded conceptual definitions, operational outcomes, valid time intervals і metric-presentation rules |
| R5 | Пов’язати п’ять security properties з літературою та outcomes | §3.4.3 містить literature bridge і прямо фіксує study-specific характер operational outcomes |
| R6 | Відокремити observation window від eligibility/denominators | Немає універсальних `τisolate`, `τrecover`, `τtotal`; experimental timing pre-specified; recovery, containment і stabilisation є outcomes усередині fixed window, а не stopping conditions |
| R7 | Зафіксувати H1 і authoritative comparison language | §3.5.5 і табл. 3.15 не використовують `successful isolation`, `recovery completion`, `isolation time` або `recovery time`; H1 і statistical status описані вузько |
| R8 | Додати adversary bridges для composite cases без нового estimand | Case 4 пов’язаний із compromised UAV node; case 5 — з monitoring failure domain; різний радіус ураження не оголошено новим adversary class |
| R9 | Зберегти prospective metric contract без результатів і internal provenance | §3.5.4 і табл. 3.14 містять operational definitions, eligibility rules і presentation status; realized n, module names і internal blocked language вилучені |

## Final-candidate verification

Для `Thesis Draft Semerenska-7_ch3_frozen_candidate.docx` підтверджено:

- R1–R5 і R7–R9 виконані;
- R6 закрито fixed timing: injection на `t = 90 s`, post-attack window `60 s`, завершення run на `t = 150 s`;
- у всіх п’яти injection cases recovery, containment і stabilisation спостерігаються та обчислюються всередині спільного fixed window;
- metric-specific eligibility filters і denominators збережені;
- застарілі `формальними security properties` і `formal properties` замінені на operationalized terminology;
- factual results глави 4, Python module names та internal audit-log claims до основного тексту не додавалися.

## Scope boundary

Цей audit не змінює frozen numerical contract, statistical status або content глави 4. Він фіксує лише semantic constraints, які має зберігати глава 3.
