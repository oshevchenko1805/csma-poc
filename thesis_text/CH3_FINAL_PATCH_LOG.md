# CH3 final patch log

Дата: 2026-08-04

## Обсяг проходу

- Вхідний документ: `Thesis Draft Semerenska-5_aligned_patched.docx`.
- Вихідний документ: `Thesis Draft Semerenska-6_ch3_final_candidate.docx`.
- Змінено лише главу 3.
- Застосовано обов’язкові пакети R1–R7 і R9 із `CH3_SEMANTIC_CONSERVATION_AUDIT.md`.
- R8 застосовано як два короткі adversary bridges без зміни experimental estimand.
- Закрито alignment-позиції A02, A03, A08 і A35.
- Незалежний semantic/alignment review у цьому проході не виконувався; проведено лише технічну перевірку документа.

## Відповідність пакетів правок зміненим місцям

| ID | Місце у главі 3 | Застосована зміна |
|---|---|---|
| R1 | §3.3.2, перед operational description конфігурації A | Відновлено один теоретичний абзац про centralized baseline, її monitoring/C2 trust assumption і роль референтної моделі; твердження про external recovery не повернуто. |
| R2 | §3.3.3, перед operational description конфігурації B | Відновлено один теоретичний абзац про distributed baseline, local monitoring, відсутність shared security context і closed recovery loop. |
| R3 | Назва §3.4; переходи у §§3.4.1–3.4.3, 3.5.1 і 3.5.7 | §3.4 перейменовано на `Security properties and operationalization`; застарілі обіцянки `formal definitions` замінено на operationalization/operationalized properties. |
| R4 | §3.4.7 | Підсумок синхронізовано з literature-grounded conceptual definitions, operational outcomes, valid time intervals і metric presentation rules. |
| R5 | Перший абзац §3.4.3 | Додано компактний literature bridge для п’яти security properties та прямо зафіксовано study-specific характер operational outcomes. |
| R6 | Загальний абзац §3.5.3 про observation window | Видалено залишкові `τisolate`/`τrecover`; observation window відокремлено від metric-specific eligibility filters і denominators. |
| R7 | Початок §3.5.5; абзац comparative interpretation; табл. 3.15 | Додано вузький confirmatory bridge для H1; видалено `successful isolation`, `recovery completion`, `isolation time` і `recovery time`; таблицю синхронізовано з authoritative metric contract. |
| R8 | Перші абзаци injection cases 4 і 5 | Додано короткі adversary bridges: compromised UAV node для detector takeout та monitoring failure domain для monitor takeout; різний радіус ураження не оголошено новим класом противника. |
| R9 | §3.5.4 і табл. 3.14 | Realized corpus sizes і conditional denominators вилучено з методологічного contract; залишено prospective eligibility rules і statistical status. Python provenance та internal blocked status вилучено з основного тексту. |
| A02 | §3.1.2.3, профіль RF/GNSS-противника | Загальну RF/GNSS threat model прямо відділено від PoC: software injection фіксованого 50-метрового offset для одного UAV без моделювання фізичного RF propagation. |
| A03 | §3.1.6.1 | Три базові класи атак прямо пов’язано з п’ятьма injection cases, включно з detector-takeout + GPS та monitor-takeout + GPS для security-plane detection coverage. |
| A08 | §§3.2.2–3.2.4, 3.2.6, 3.3.4, 3.5.2; табл. 3.11 | Реалізований coordinator описано як deterministic `lowest-alive-sysid` з виключенням unavailable/isolated peers. У всіх застарілих місцях прибрано твердження, що coordinator не реалізований; механізм не названо fault-tolerant consensus або універсальним election protocol. |
| A35 | §3.5.6 | Зафіксовано: simulation-only, три UAV, ZeroMQ/TCP, один 50-метровий GPS offset, C-only loss sweep, два high-loss рівні з realized `n=12` і широкими CI, FP loop-depth C на `n=2`, configuration-level causal limit. |

## Таблиці і терміни

- Табл. 3.11 збережена як Word-таблиця `11 × 2`; оновлено лише рядки про спрощену реалізацію coordinator і відсутність універсального consensus/election protocol.
- Табл. 3.14 збережена як Word-таблиця `18 × 4`; фактичні знаменники замінено symbolic eligibility rules без зміни metric names.
- Табл. 3.15 збережена як Word-таблиця `8 × 2`; синхронізовано `Observation window` та `Інтерпретація результатів`.
- Старі формули `τrecover`, `τtotal`, `M(t)` і `C(t)` не відновлювалися.
- Залишкові `τisolate`, `τrecover`, `successful isolation`, `recovery completion`, `isolation time` і `recovery time` у главі 3 відсутні.

## Фрагменти, вилучені з глави 3 і зарезервовані для глави 4

Нижче наведено саме матеріал для перенесення; у методологічному тексті залишено лише правила формування знаменників.

1. Corpus flow: `435 → 414`, `309 attack-runs`, `105 clean flights`, A/B/C `101/105/103`.
2. Time to Isolation accounting: 222 non-null у master; attack-response `n=220`; дві baseline FP rows виключено.
3. MTTR functional: realized conditional `n=267`.
4. Coordination: attack `n=309`; full valid clean `n=103`; `base_pass n=88` як окремий підкорпус.
5. Total Response Time: C/recovery-event `n=88`.
6. Clean-flight FP exposure: 35 flights на architecture.
7. All-valid-clean-window exposure: A/B/C `136/140/138`.
8. FP loop-depth mechanism C: realized `n=2`; у §3.5.6 збережено лише limitation statement, а детальний case result зарезервовано для глави 4.
9. Sustain sensitivity: 45 GPS attack-runs і 105 clean flights.
10. Mesh-loss tails: два high-loss levels з realized `n=12` і широкими CI; у §3.5.6 збережено лише обов’язкове limitation statement A35.

## Фрагменти, вилучені з основного тексту і зарезервовані для appendix/reproducibility note

- Module provenance: `campaign_report.mttd`, `metrics/coordination.py`, `metrics/sustain.py`, `campaign_master.py`, `metrics/derived.py`, `metrics/stats.py`, `campaign_stats.py`.
- Internal audit status до окремого primary-artifact audit: MTTD decomposition, R15 policy ablation і mesh message-type composition.
- У §3.5.4 залишено тільки вказівку, що mapping між metric fields і analytical pipeline має бути наведений у додатку або repository provenance note.

## Технічна перевірка

- SHA-256 input: `c3967c2bcb1502547ba425eee00c0525007b4cf837aafe37e20a33fd3c7cbd5b`.
- SHA-256 output DOCX: `6009baa63efd0311b520625251aa56c28c51f6f1c9ef5ee856ea0627160c0c1c`.
- SHA-256 control PDF: `ec4fe6a40c7af55cdc7023c6ac74ac384ae2ac64a3dbf5123ee986b0ab2773d9`.
- DOCX ZIP integrity: pass.
- Єдина змінена package part: `word/document.xml`.
- XML до початку глави 3 та від `REFERENCES` до кінця документа: byte-equivalent після canonicalization.
- Таблиці: 16; rows: 122; cells: 473; table shapes і geometry unchanged.
- Hyperlinks: 48; pictures: 5; comment ranges/references: 3/3/3; counts unchanged.
- Control PDF: 103 сторінки; усі сторінки переглянуто на clipping, overlap, missing glyphs, broken tables і unexpected page furniture.
- Нових layout defects не виявлено. Наявний у source червоний diagram placeholder на сторінках 36–38 не змінювався, оскільки він не належить до пакета R1–R9/A02/A03/A08/A35.
- Source DOCX files не змінено; commit не створювався.
