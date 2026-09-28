# Литература, проход 1: сводный список источников (P3)

> Для авторки (не вставлять в диссертацию). Шаг 1.1 от 28.09.2026: инвентаризация без проверки.
> Колонки «Проверка» заполняются на шаге 1.2. Статусы: **ок** — существует, выходные данные полные и сверены; **испр** — существует, данные исправлены; **?** — не удалось подтвердить; **нет** — не найден.
> «Открыто»: ПТ — полный текст; АН — аннотация; МД — только метаданные (издатель / DOI).
> Выходные данные не придумываются: если страницы или DOI не найдены, так и пишется.
> Проверка идёт через веб-поиск и страницы издателей (Crossref и arXiv API из командной строки недоступны).

## Откуда собрано

| Код | Источник | Что взято |
|---|---|---|
| L | Список REFERENCES в Thesis Draft (docx в проекте = `…-8_ch4_layout_review.docx` на Mac, списки совпадают, 30 пунктов) | все 30 |
| T2 | Текст раздела 2 (там же): ссылки в скобках с URL | к каким пунктам L привязаны URL |
| C3 / C4 | `CH3_V2_TEXT.md`, `CH4_V2_TEXT.md` | все ссылки [Автор, рік] и пометки [уточнити] |
| N | `NOVELTY_DRAFT.md` | ссылок нет, упомянуты Kerns и failsafe PX4/ArduPilot (→ кандидаты прохода 2) |
| Q | `LIT_CHECK_2026-09-27.md`, Q1–Q6 | все источники |
| + | Добавить по решению автора | Mykytyn 2023, Bi 2024, Park & Yoo 2026 (препринт) |

Старые ссылки прежнего раздела 3 (Shostack, Bekmezci и др.) не входят: раздел 3 переписан, в CH3_V2 их нет.

## Решения автора (28.09)

- ATT&CK for ICS: переходим на версию v19 (коды T1692.002, T1691.002, T1691.001 вместо T0856, T0804, T0803), в ссылке указываем версию. Правка таблицы 3.1 и примечания — шаг 1.4.
- Gartner: цитируем открытый пресс-релиз от 18.10.2021 (B№1).
- Schneier 1999: цитируем по странице автора с датой обращения (B№6).
- Формат ссылок в тексте: пока [Автор, рік]; окончательный — по требованиям учреждения, один раз при переносе в docx.
- 2.2: «аналітичний огляд» с кратким описанием поиска; без цели по числу источников.


## Итог инвентаризации

| Группа | Сколько | Замечание |
|---|---|---|
| A. Текущий список L | 30 → 29 уникальных | №26 — дубль №25 |
| B. Цитируется в CH3/CH4, нет в L | 13 → 12 новых | Bashendy 2023, вероятно, = L№23 |
| C. Из LIT_CHECK, нет в A/B | 21 | |
| **Всего к проверке** | **≈ 62** | |

Не цитируются в тексте раздела 2: L№3, 5, 6 (?), 10, 17, 21, 22, 23, 26, 27. Решение (оставить и процитировать / убрать) — после проверки, в плане раздела 2.

---

## A. Текущий список L (30)

Колонка «Проблема» — то, что видно без проверки. URL — без `utm_source`.

| L№ | Как в списке (сокращённо) | T2 (разделы) | C3/C4 | URL из текста раздела 2 | Проблема | Проверка | Открыто | Примечание 1.2 |
|---|---|---|---|---|---|---|---|---|
| 1 | Kumar N. et al. (2024). Surveying cybersecurity vulnerabilities… Computer Networks | 2.1, 2.3 | C3 | sciencedirect.com/…/S1389128624005279 | «et al.», нет тома/страниц/DOI; пометки | | | |
| 2 | Spyros A. et al. (2024). A comprehensive survey and taxonomy… UAVs and IoD. ACM Computing Surveys | 2.1, 2.3, 2.9 | C3 | dl.acm.org/doi/10.1145/3785658 | год 2024 при DOI вида 3785658 — сверить год и том | | | |
| 3 | (2024). A survey on unmanned aerial systems cybersecurity. Elsevier | — | — | — | **нет авторов и издания**; не цитируется | | | |
| 4 | Hassija V. et al. (2021). Fast, reliable, and secure drone communication… IEEE COMST 23 | 2.1, 2.3, 2.9 | C3 | researchgate.net/publication/353212475 | ссылка на ResearchGate вместо DOI | | | |
| 5 | Shrestha S. et al. (2025). A Comprehensive Survey of UAS Risks… | — | — | — | пометка «використовуй лише якщо…»; статус (препринт?) | | | |
| 6 | Ceviz O. et al. (2023). A Survey of Security in UAVs and FANETs… | ? | — | — | пометка «перевір статус»; какой Ceviz цитируется в 2.4 — №6 или №8 | | | |
| 7 | Lu Y., Yang T., Zhao C., Chen W., Zeng R. (2024). A swarm anomaly detection model… Computers & Industrial Engineering | 2.1, 2.4, 2.9 | C3 | sciencedirect.com/…/S0360835224005758 | нет тома/номера статьи/DOI | | | |
| 8 | Ceviz O. (2023/2025). A Novel Federated Learning-Based IDS… | 2.4 | — | arxiv.org/pdf/2312.04135 | год «2023/2025»; препринт или журнал | | | |
| 9 | Islam M.D.S. et al. (2025). AI-Enhanced Intrusion Detection for UAV Systems. Drones 9(10):682 | 2.1, 2.3, 2.4, 2.9 | C3 | mdpi.com/2504-446X/9/10/682 | «et al.», нет DOI | | | |
| 10 | Akram J. et al. (2024). DroneSSL… IEEE Trans. Consumer Electronics | — | — | — | название обрезано «…»; не цитируется | | | |
| 11 | Alhoraibi L. et al. (2024). Detection of GPS Spoofing Attacks in UAVs… Sensors 24(18):6156 | 2.3, 2.4, 2.8 | C3 | mdpi.com/1424-8220/24/18/6156 | «et al.», нет DOI | | | |
| 12 | Abdullayeva F. et al. (2025). Multimodal deep neural network for UAV GPS jamming… (Elsevier) | 2.4, 2.8 | — | sciencedirect.com/…/S2772918425000116 | **нет журнала** | | | |
| 13 | Kfir T. et al. (2025). Real-time detection of acoustic anomalies… Machine Learning with Applications | 2.4 | — | sciencedirect.com/…/S2666827025001380 | нет тома/DOI | | | |
| 14 | Lopez M.A. et al. (2021). Towards Secure Wireless Mesh Networks for UAV Swarm Connectivity… IEEE | 2.1, 2.3, 2.5, 2.9 | C3 | michaelbaddeley.com/…/lopez2021towards.pdf | **ссылка на личный сайт**; издание «IEEE» без названия; автор = Andreoni Lopez M. (LIT_CHECK: arXiv 2108.13154) | | | |
| 15 | Amponis G. et al. (2021). A survey on FANET routing from a cross-layer design perspective. Computer Communications | 2.5 | C3 | sciencedirect.com/…/S1383762121001934 | **подозрение: PII с ISSN 1383-7621 = Journal of Systems Architecture, а не Computer Communications** | | | |
| 16 | Almansor M.J. et al. (2024). Routing protocols strategies for FANET… Alexandria Engineering Journal | 2.1, 2.5, 2.9 | — | sciencedirect.com/…/S1110016824010469 | нет тома/страниц/DOI | | | |
| 17 | Lu Y. et al. (2023). UAV Ad Hoc Network Routing Algorithms in SAGIN… Drones 7(7):448 | — | — | — | не цитируется | | | |
| 18 | Phadke A. et al. (2023). Examining application-specific resiliency implementations for UAV swarms (OAEPublish) | 2.5, 2.6 | C3 | oaepublish.com/articles/ir.2023.27 | нет журнала (Intelligence & Robotics?) и тома | | | |
| 19 | Phadke A. et al. (2022). Towards Resilient UAV Swarms—A Breakdown of… Drones 6(11):340 | 2.6 | C3 | mdpi.com/2504-446X/6/11/340 | название обрезано «…» | | | |
| 20 | Johnphill O. et al. (2023). Self-Healing in CPS Using Machine Learning… Future Internet 15(7):244 | 2.1, 2.6, 2.9 | C3 | mdpi.com/1999-5903/15/7/244 | «et al.», нет DOI | | | |
| 21 | Furrer F.J. et al. (2023). Safe and secure system architectures for CPS. Informatik Spektrum | — | — | — | не цитируется; нет тома | | | |
| 22 | Singh P. et al. (2022). Using log analytics and process mining to enable self-healing… Empirical Software Engineering | — | — | — | название обрезано; не цитируется | | | |
| 23 | (2022). Intrusion response systems for cyber-physical systems. Computers & Security | — | C3 (как Bashendy 2023) | — | **нет авторов**; год 2022 или 2023 (том 124 — январь 2023) | **ок** | АН | **= B№7 Bashendy, Tantawy, Erradi 2023** — объединить |
| 24 | Eckhart M., Ekelhart A. (2021). Digital twins as run-time predictive models… Phil. Trans. R. Soc. A 379(2207):20200369 | 2.6, 2.9 | C3 | royalsocietypublishing.org/doi/10.1098/rsta.2020.0369 | выглядит полным; сверить авторов | | | |
| 25 | Ramos-Cruz B. et al. (2024). The cybersecurity mesh: A comprehensive survey… Applied Soft Computing | 2.7, 2.9 | C3 | sciencedirect.com/…/S092523122400198X | **подозрение: PII с ISSN 0925-2312 = Neurocomputing, а не Applied Soft Computing** | | | |
| 26 | (2024). The cybersecurity mesh: … (ScienceDirect) | — | — | — | **дубль №25 — удалить** | | | |
| 27 | Abdulrazak B. et al. (2022). Self-healing Approach for IoT Architecture: AMI Platform (Springer/ACM index) | — | — | — | нет издания; не цитируется | | | |
| 28 | Patil D.A. et al. (2025). A comprehensive survey on securing the social internet of things (PMC) | 2.7 | — | pmc.ncbi.nlm.nih.gov/articles/PMC12624021 | нет журнала | | | |
| 29 | Mohammed A.B. et al. (2025). Investigation on datasets toward intelligent IDS for intra and inter-UAV communication… Computers & Security | 2.8 | — | sciencedirect.com/…/S0167404824005212 | нет тома/DOI | | | |
| 30 | Hutchins C. et al. (2025). A flying ad-hoc network dataset for early time series classification of grey hole attacks. Scientific Data 12 | 2.8 | — | nature.com/articles/s41597-025-05560-1 | нет номера статьи; пометка «(dataset paper)» | | | |

Во всех пунктах L есть рабочие пометки «Key findings» / «Gap link» — убираются целиком. Ссылки на базы данных в 2.2 (голые домены IEEE Xplore, ACM DL, ScienceDirect, SpringerLink, MDPI) — не источники; 2.2 переписывается.

---

## B. Цитируется в новых разделах 3–4, нет в списке L (13) — партия 1 проверена 28.09

Приоритет: эти ссылки закрываются до переноса раздела 3 в docx. «Соответствие» — подтверждает ли источник утверждение, к которому он стоит (подробно — шаг 1.4).

| B№ | Ссылка в тексте | Где | Проверка | Открыто | Полные выходные данные (сверено) | Соответствие утверждению | Примечание |
|---|---|---|---|---|---|---|---|
| 1 | [Gartner, 2021] | C3 3.2 | **испр** | стр. | Gartner Identifies the Top Strategic Technology Trends for 2022 : press release / Gartner, Inc. 18.10.2021. URL: https://www.gartner.com/en/newsroom/press-releases/2021-10-18-gartner-identifies-the-top-strategic-technology-trends-for-2022 (дата звернення: 28.09.2026) | да: «security perimeter is gone … requires a cybersecurity mesh architecture (CSMA)». Описание «компонуемый, масштабируемый подход; единое управление политиками, аналитика безопасности, identity fabric» — в отчёте Gartner «Top Strategic Technology Trends for 2022: Cybersecurity Mesh» | Платный отчёт: копия без даты и авторов — его выходные данные не подтверждены. Предлагаю цитировать открытый пресс-релиз (год 2021 в тексте сохраняется). Есть и ранний отчёт «Top Strategic Technology Trends for 2021: Cybersecurity Mesh» (Gartner doc 3996593) — метаданные не открылись |
| 2 | [Dash et al., 2024] | C3 3.2 (2 раза) | **ок** | АН + метаданные arXiv | Dash P., Li G., Karimibiuki M., Pattabiraman K. Diagnosis-guided Attack Recovery for Securing Robotic Vehicles from Sensor Deception Attacks. *ASIA CCS '24: Proc. 19th ACM Asia Conf. on Computer and Communications Security*. 2024. P. 915–929. DOI: 10.1145/3634737.3644997 | да: диагностика атакованных датчиков → восстановление по нескомпрометированным (DeLorean), один аппарат | [уточнити] снять. Ближайшая работа №2 |
| 3 | [Flueratoru et al., 2022] | C3 3.6.3 | **ок** | ПТ (arXiv 2104.11042) | Flueratoru L., Wehrli S., Magno M., Lohan E. S., Niculescu D. High-Accuracy Ranging and Localization With Ultrawideband Communications for Energy-Constrained Devices. *IEEE Internet of Things Journal*. 2022. Vol. 9, No. 10. P. 7463–7480. DOI: 10.1109/JIOT.2021.3125256 | да: DW1000 в прямой видимости 0.00 ± 0.05 м (→ σ = 0.1 м вдвое консервативнее); за бетонной стеной +0.44 м, за телом человека +0.60 м (→ 0.5 м) | **Расхождение снято**: цитируем именно журнальную статью 2022. GLOBECOM 2020 (C/Q6) — её конференционная версия, в список не нужна. [уточнити] снять |
| 4 | [MAVLink, Message Signing] | C3 3.1.2 | **ок** | стр. | Message Signing (Authentication) // MAVLink Developer Guide. URL: https://mavlink.io/en/guide/message_signing.html (дата звернення: 28.09.2026) | да, кроме одной фразы: ключ передаётся сообщением SETUP_SIGNING, «only … over a secure link (e.g. USB or wired Ethernet)» — в тексте «ключ розподіляють поза протоколом» | Правка текста → шаг 1.4. Состав подписи (link ID, 48-бит метка, 48-бит подпись = первые 6 байт SHA-256, ключ 32 байта), «только аутентификация, не шифрование», необязательность — подтверждены |
| 5 | MITRE ATT&CK for ICS | C3 3.1, табл. техник | **испр** | стр. | MITRE ATT&CK for ICS : knowledge base. Version 19 / The MITRE Corporation. URL: https://attack.mitre.org/versions/v19/ (дата звернення: 28.09.2026) — или v18 (см. примечание) | **7 из 10 кодов действуют**: T0832, T0826, T0814, T0860, T0821, T0831, T0813. **3 кода устарели в v19** (28.04.2026): T0856 Spoof Reporting Message → T1692.002 Unauthorized Message: Reporting Message; T0804 Block Reporting Message → T1691.002; T0803 Block Command Message → T1691.001 | Решение автора: (а) перейти на коды v19 и указать версию; (б) оставить старые коды и сослаться на v18 (https://attack.mitre.org/versions/v18/, действовала до 27.04.2026). Рекомендую (а) |
| 6 | [Schneier, 1999] | C3 3.1 | **испр / ?** | стр. автора | Schneier B. Attack Trees. *Dr. Dobb's Journal*. 1999. December. URL: https://www.schneier.com/academic/archives/1999/12/attack_trees.html | да | Том/номер/страницы (часто цитируют 24(12):21–29) первоисточником **не подтверждены** — цитировать по странице автора с датой обращения. [уточнити] снять после выбора |
| 7 | [Bashendy et al., 2023] | C3 | **ок** | АН | Bashendy M., Tantawy A., Erradi A. Intrusion response systems for cyber-physical systems: A comprehensive survey. *Computers & Security*. 2023. Vol. 124. Art. 102984. DOI: 10.1016/j.cose.2022.102984 | да (обзор IRS для CPS; «still at its early stages and lacks applicability to real CPS») | **= L№23** (там без авторов и с годом 2022) — объединить |
| 8 | [Cardenas et al., 2011] | C3 3.1 | **ок / соответствие слабое** | АН | Cárdenas A. A., Amin S., Lin Z.-S., Huang Y.-L., Huang C.-Y., Sastry S. Attacks against process control systems: risk assessment, detection, and response. *ASIACCS '11: Proc. 6th ACM Symp. on Information, Computer and Communications Security*. 2011. P. 355–366. DOI: 10.1145/1966913.1966959 | **частично**: статья об обнаружении атак по физической модели процесса, а в тексте — «межі, на яких змінюються припущення про довіру, контроль і фізичну доступність» | Шаг 1.4: оставить только Humayed или заменить Cárdenas на более подходящую его работу |
| 9 | [Humayed et al., 2017] | C3 3.1 | **ок** | МД | Humayed A., Lin J., Li F., Luo B. Cyber-Physical Systems Security—A Survey. *IEEE Internet of Things Journal*. 2017. Vol. 4, No. 6. P. 1802–1831. DOI: 10.1109/JIOT.2017.2703172 | да (обзор безопасности CPS по кибер- и физическим аспектам) | |
| 10 | [Kerns et al., 2014] | C4 4.x (2 раза) | **ок** | ПТ (сайт лаборатории) | Kerns A. J., Shepard D. P., Bhatti J. A., Humphreys T. E. Unmanned Aircraft Capture and Control Via GPS Spoofing. *Journal of Field Robotics*. 2014. Vol. 31, No. 4. P. 617–636. DOI: 10.1002/rob.21513 | да: вертолёт в режиме удержания точки («maintain hover at a specified waypoint») захвачен и уведён подменой GPS | |
| 11 | [Mykytyn et al., 2023] | C3 3.6.3, C4 4.6 | **ок** | ПТ (arXiv) | Mykytyn P., Brzozowski M., Dyka Z., Langendoerfer P. GPS-Spoofing Attack Detection Mechanism for UAV Swarms. *2023 12th Mediterranean Conference on Embedded Computing (MECO)*. Budva, 2023. P. 1–8. DOI: 10.1109/MECO58584.2023.10154998 | да: сравнение GPS-расстояний с дальностями IR-UWB, порог | Страницы подтверждены Crossref (партия 2). Ближайшая работа №3 |
| 12 | [Bi et al., 2024] | C3 3.6.3, C4 4.6 | **ок** | ПТ (arXiv) | Bi S., Li K., Hu S., Ni W., Wang C., Wang X. Detection and Mitigation of Position Spoofing Attacks on Cooperative UAV Swarm Formations. *IEEE Transactions on Information Forensics and Security*. 2024. Vol. 19. P. 1883–1895. DOI: 10.1109/TIFS.2023.3341398 | да | Страницы — по странице публикаций соавтора (UNSW) и ссылке в OUCI |
| 13 | [Park & Yoo, 2026] | C3 3.5, 3.6.3; C4 4.6 | **ок (препринт)** | ПТ (arXiv HTML v1) | Park M., Yoo J. S. Rigid-Covert GNSS Spoofing of UAV Swarms: A Structural Blind Spot, Its Detection Limit, and Absolute-Anchor Defenses : preprint. arXiv:2608.06885. 2026. URL: https://arxiv.org/abs/2608.06885 | да: общий медленный сдвиг сохраняет попарные расстояния и «unobservable to any relative-only detector» | Не рецензирован; журнальной версии не найдено (28.09). Проверить перед защитой. Ближайшая работа №1. Авторы — Jeonbuk National University |

Выходные данные здесь даны полностью, но ещё не по ДСТУ 8302:2015 — оформление в проходе 2.

**Итог партии 1:** 13 из 13 существуют. [уточнити] можно снять у Dash, Flueratoru, MAVLink, Gartner (после выбора варианта). Открытые решения автора: ATT&CK (версия v19 или v18), Gartner (пресс-релиз), Schneier (цитировать по странице автора). Не подтверждено: страницы Mykytyn 2023; том/страницы Schneier 1999. В шаг 1.4 переходят: фраза о ключе MAVLink, соответствие Cárdenas 2011.

---

## C. Из проверки новизны (LIT_CHECK Q1–Q6), нет в A/B (21)

Уже открыты 27.09; на шаге 1.2 — только дозаполнить выходные данные и статус.

| C№ | Источник (как в LIT_CHECK) | Q | Открыто 27.09 | Чего не хватает |
|---|---|---|---|---|
| 1 | Michieletto G., Formaggio F., Cenedese A., Tomasin S. (2023). Robust Localization for Secure Navigation of UAV Formations Under GNSS Spoofing Attack. IEEE T-ASE 20(4):2383–2396. DOI 10.1109/TASE.2022.3208662 | Q1 | АН | — (сверить) |
| 2 | Meng L., Zhang L., Yang L., Yang W. (2023). A GPS-Adaptive Spoofing Detection Method for the Small UAV Cluster. Drones 7(7):461. DOI 10.3390/drones7070461 | Q1 | ПТ | — (сверить) |
| 3 | Dev K. et al. (2025). SwarmRaft. IEEE IoT J. DOI 10.1109/JIOT.2025.3645453 (arXiv 2508.00622) | Q1 | АН | полное название, авторы, том |
| 4 | Jung J.H., Hong M.Y., Choi H., Yoon J.W. (2024). An Analysis of GPS Spoofing Attack and Efficient Approach to Spoofing Detection in PX4. IEEE Access 12:46668–46677. DOI 10.1109/ACCESS.2024.3382543 | Q2 | АН | — (сверить); ближайшая по обходу EKF2 |
| 5 | Finn A., Jia M., Li Y., Yuan J. (2024). Detecting Stealthy GPS Spoofing Attack Against UAVs Using Onboard Sensors. IEEE INFOCOM WKSHPS. DOI 10.1109/INFOCOMWKSHPS61880.2024.10620818 | Q2 | ПТ | страницы |
| 6 | Khazraei A., Meng H., Pajic M. (2024). Black-box Stealthy GPS Attacks on UAVs. IEEE CDC. arXiv 2409.11405 | Q2 | АН | страницы, DOI |
| 7 | Mo Y., Sinopoli B. (2010). False data injection attacks in control systems. 1st Workshop on Secure Control Systems | Q2 | **не открыт** | открыть; выходные данные |
| 8 | Psiaki M.L., Humphreys T.E. (2016). GNSS Spoofing and Detection. Proc. IEEE 104(6):1258–1270 | Q2 | МД | DOI |
| 9 | Dash P. et al. (2021). PID-Piper. IEEE/IFIP DSN, pp. 26–38. DOI 10.1109/DSN48987.2021.00020 | Q3 | МД | полное название, авторы |
| 10 | Zhang L. et al. (2021). Real-Time Attack-Recovery for CPS Using LQR. ACM TECS 20(5s), Art. 79. DOI 10.1145/3477010 | Q3 | МД | авторы |
| 11 | Kong F. et al. (2018). CPS Checkpointing and Recovery. ICCPS, pp. 22–31. DOI 10.1109/ICCPS.2018.00011 | Q3 | МД | полное название, авторы |
| 12 | Tariq U., Shaukat K. (2026). Mission-aware BeiDou Spoofing Defense in UAV Swarms with LLM-assisted Context Validation. Front. Commun. Netw. 7:1760543. DOI 10.3389/frcmn.2026.1760543 | Q3 | фрагменты | сверить |
| 13 | Ouiazzane S., Addou M., Barramou F. (2023). A Zero-Trust Model for Intrusion Detection in Drone Networks. IJACSA 14(11):525–537 | Q4 | ПТ | DOI |
| 14 | A Survey on Security of UAV Swarm Networks: Attacks and Countermeasures. ACM Computing Surveys. DOI 10.1145/3703625 | Q4 | фрагмент | **авторы**, том, год |
| 15 | Li S., Coppola M., De Wagter C., de Croon G. An Autonomous Swarm of Micro Flying Robots with Range-based Relative Localization. arXiv 2003.05853 | Q5, Q6 | ПТ | журнальная версия (вероятно, IEEE RA-L / T-RO) |
| 16 | Güler S., Abdelkader M., Shamma J.S. (2021). Peer-to-Peer Relative Localization of Aerial Robots with UWB Sensors. IEEE TCST 29(5):1981–1996. DOI 10.1109/TCST.2020.3027627 | Q5 | МД | — (сверить) |
| 17 | Guo K., Li X., Xie L. (2020). UWB and Odometry-Based Cooperative Relative Localization… IEEE Trans. Cybernetics 50(6):2590–2603 | Q5 | МД | полное название, DOI |
| 18 | Formation-Constrained Cooperative Localization for UAV Swarms in GNSS-Denied Environments. PMC13029989 | Q5 | фрагмент | **авторы, журнал** |
| 19 | Degradation-Aware Cooperative Multi-Modal GNSS-Denied Localization. arXiv 2510.20480 | Q5 | фрагмент | **авторы**, статус |
| 20 | Qorvo DWM1000 (страница продукта) | Q6 | стр. | дата обращения; лучше даташит |
| 21 | Qorvo DW3110 (страница продукта) | Q6 | стр. | дата обращения; лучше даташит |

Flueratoru 2020 GLOBECOM (Q6) — конференционная версия B№3; в список не включаем.

### C, партия 2 (C№1–12) — проверено 28.09 по Crossref (через встроенный браузер) и страницам авторов

| C№ | Проверка | Полные выходные данные (сверено) | Примечание |
|---|---|---|---|
| 1 | **ок** | Michieletto G., Formaggio F., Cenedese A., Tomasin S. Robust Localization for Secure Navigation of UAV Formations Under GNSS Spoofing Attack. *IEEE Transactions on Automation Science and Engineering*. 2023. Vol. 20, No. 4. P. 2383–2396. DOI: 10.1109/TASE.2022.3208662 | |
| 2 | **ок** | Meng L., Zhang L., Yang L., Yang W. A GPS-Adaptive Spoofing Detection Method for the Small UAV Cluster. *Drones*. 2023. Vol. 7, No. 7. Art. 461. DOI: 10.3390/drones7070461 | |
| 3 | **испр** | Dev K., Madhwal Y., Shevelo S., Osinenko P., Yanovich Y. SwarmRaft: Leveraging Consensus for Robust Drone Swarm Coordination in GNSS-Degraded Environments. *IEEE Internet of Things Journal*. 2026. Vol. 13, No. 5. P. 9112–9120. DOI: 10.1109/JIOT.2025.3645453 | Год 2026 (в LIT_CHECK — 2025, по DOI); добавлены название и авторы |
| 4 | **ок** | Jung J. H., Hong M. Y., Choi H., Yoon J. W. An Analysis of GPS Spoofing Attack and Efficient Approach to Spoofing Detection in PX4. *IEEE Access*. 2024. Vol. 12. P. 46668–46677. DOI: 10.1109/ACCESS.2024.3382543 | Ближайшая по обходу EKF2 |
| 5 | **ок** | Finn A., Jia M., Li Y., Yuan J. Detecting Stealthy GPS Spoofing Attack Against UAVs Using Onboard Sensors. *IEEE INFOCOM 2024 — IEEE Conference on Computer Communications Workshops (INFOCOM WKSHPS)*. Vancouver, 2024. P. 1–6. DOI: 10.1109/INFOCOMWKSHPS61880.2024.10620818 | |
| 6 | **испр** | Khazraei A., Meng H., Pajic M. Black-box Stealthy GPS Attacks on Unmanned Aerial Vehicles. *2024 IEEE 63rd Conference on Decision and Control (CDC)*. 2024. P. 2857–2862. DOI: 10.1109/CDC56724.2024.10885819 | Добавлены DOI и страницы (было только arXiv) |
| 7 | **ок (без DOI)** | Mo Y., Sinopoli B. False data injection attacks in control systems. *Proc. 1st Workshop on Secure Control Systems (SCS), CPS Week 2010*. Stockholm, 2010. URL: https://yilinmo.github.io/papers/scs2010.html | Сборник без DOI и страниц. Аннотация подтверждает: условие дестабилизации системы с фильтром Калмана при обходе детектора отказов. Рецензируемая альтернатива с DOI: Mo Y., Garone E., Casavola A., Sinopoli B. False data injection attacks against state estimation in wireless sensor networks. *49th IEEE CDC*. 2010. P. 5967–5972. DOI: 10.1109/CDC.2010.5718158 — выбрать при плане раздела 2 |
| 8 | **испр** | Psiaki M. L., Humphreys T. E. GNSS Spoofing and Detection. *Proceedings of the IEEE*. 2016. Vol. 104, No. 6. P. 1258–1270. DOI: 10.1109/JPROC.2016.2526658 | Добавлен DOI |
| 9 | **испр** | Dash P., Li G., Chen Z., Karimibiuki M., Pattabiraman K. PID-Piper: Recovering Robotic Vehicles from Physical Attacks. *2021 51st Annual IEEE/IFIP International Conference on Dependable Systems and Networks (DSN)*. Taipei, 2021. P. 26–38. DOI: 10.1109/DSN48987.2021.00020 | Добавлены название и авторы |
| 10 | **испр** | Zhang L., Lu P., Kong F., Chen X., Sokolsky O., Lee I. Real-time Attack-recovery for Cyber-physical Systems Using Linear-quadratic Regulator. *ACM Transactions on Embedded Computing Systems*. 2021. Vol. 20, No. 5s. Art. 79 (24 p.). DOI: 10.1145/3477010 | Авторы добавлены; номер статьи 79 — по LIT_CHECK, Crossref даёт только «1–24» |
| 11 | **испр** | Kong F., Xu M., Weimer J., Sokolsky O., Lee I. Cyber-Physical System Checkpointing and Recovery. *2018 ACM/IEEE 9th International Conference on Cyber-Physical Systems (ICCPS)*. Porto, 2018. P. 22–31. DOI: 10.1109/ICCPS.2018.00011 | Добавлены название и авторы |
| 12 | **ок** | Tariq U., Shaukat K. Mission-aware BeiDou spoofing defense in UAV swarms with LLM-assisted context validation. *Frontiers in Communications and Networks*. 2026. Vol. 7. Art. 1760543. DOI: 10.3389/frcmn.2026.1760543 | |

Попутно Crossref подтвердил страницы **B№11 Mykytyn 2023: P. 1–8** (Budva, Montenegro) и данные **B№12 Bi 2024**.


---

## D. Утверждения в тексте, которые надо подтвердить источником (не библиография)

| D№ | Где | Что проверить |
|---|---|---|
| 1 | C3 3.1, таблица техник | коды ATT&CK: проверены (B№5) — 3 устарели в v19, решение автора |
| 2 | C3 3.1.2 | MAVLink 2 signing поддерживается PX4 на коммите стенда `9fe69d4f33` (документация PX4) |
| 3 | C3 3.6.3 | закрыто: числа σ и смещения совпадают с Flueratoru et al. 2022 (B№3) |
| 4 | C3 3.2 / N | формулировки о DeLorean, Mykytyn, Park & Yoo соответствуют их тексту (шаг 1.4) |
| 5 | C4 | закрыто: Kerns 2014 — захват в режиме удержания точки подтверждён (B№10) |

## Кандидаты прохода 2 (сейчас не проверяются)

- Программные средства стенда: PX4 Autopilot, Gazebo (gz-sim 8), MAVSDK, MAVLink, mavlink-router, ZeroMQ — ссылки на документацию.
- Failsafe PX4 и ArduPilot при недостоверной оценке позиции (из NOVELTY_DRAFT).
- Работы о самовосстановлении роя и CPS с физическими метриками исхода (из NOVELTY_DRAFT).
- Источник для описания поиска в 2.2 (если нужен).

## Порядок шага 1.2 (партии)

| Партия | Что | Почему первой |
|---|---|---|
| 1 | B№1–13 — **готово 28.09** | закрывают [уточнити] в разделе 3 до переноса в docx; три ближайшие работы |
| 2 | C№1–12 — **готово 28.09** | спуфинг, обход EKF, восстановление — ядро новизны |
| 3 | C№13–21 | архитектуры, кооперативная локализация, UWB |
| 4 | L№1–10 | |
| 5 | L№11–20 | |
| 6 | L№21–30 | |
