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
| 23 | (2022). Intrusion response systems for cyber-physical systems. Computers & Security | — | C3 (как Bashendy 2023) | — | **нет авторов**; год 2022 или 2023 (том 124 — январь 2023) | | | |
| 24 | Eckhart M., Ekelhart A. (2021). Digital twins as run-time predictive models… Phil. Trans. R. Soc. A 379(2207):20200369 | 2.6, 2.9 | C3 | royalsocietypublishing.org/doi/10.1098/rsta.2020.0369 | выглядит полным; сверить авторов | | | |
| 25 | Ramos-Cruz B. et al. (2024). The cybersecurity mesh: A comprehensive survey… Applied Soft Computing | 2.7, 2.9 | C3 | sciencedirect.com/…/S092523122400198X | **подозрение: PII с ISSN 0925-2312 = Neurocomputing, а не Applied Soft Computing** | | | |
| 26 | (2024). The cybersecurity mesh: … (ScienceDirect) | — | — | — | **дубль №25 — удалить** | | | |
| 27 | Abdulrazak B. et al. (2022). Self-healing Approach for IoT Architecture: AMI Platform (Springer/ACM index) | — | — | — | нет издания; не цитируется | | | |
| 28 | Patil D.A. et al. (2025). A comprehensive survey on securing the social internet of things (PMC) | 2.7 | — | pmc.ncbi.nlm.nih.gov/articles/PMC12624021 | нет журнала | | | |
| 29 | Mohammed A.B. et al. (2025). Investigation on datasets toward intelligent IDS for intra and inter-UAV communication… Computers & Security | 2.8 | — | sciencedirect.com/…/S0167404824005212 | нет тома/DOI | | | |
| 30 | Hutchins C. et al. (2025). A flying ad-hoc network dataset for early time series classification of grey hole attacks. Scientific Data 12 | 2.8 | — | nature.com/articles/s41597-025-05560-1 | нет номера статьи; пометка «(dataset paper)» | | | |

Во всех пунктах L есть рабочие пометки «Key findings» / «Gap link» — убираются целиком. Ссылки на базы данных в 2.2 (голые домены IEEE Xplore, ACM DL, ScienceDirect, SpringerLink, MDPI) — не источники; 2.2 переписывается.

---

## B. Цитируется в новых разделах 3–4, нет в списке L (13)

Приоритет: эти ссылки закрываются до переноса раздела 3 в docx.

| B№ | Ссылка в тексте | Где | Что утверждается в тексте (кратко) | Известно из LIT_CHECK / проблема | Проверка | Открыто | Примечание 1.2 |
|---|---|---|---|---|---|---|---|
| 1 | [Gartner, 2021] | C3 3.2 (с [уточнити]) | первичный источник понятия CSMA | нужен конкретный документ Gartner (отчёт / Top Strategic Technology Trends); доступ платный — возможно, цитировать открытую страницу Gartner | | | |
| 2 | [Dash et al., 2024] | C3 3.2, 3.x (один раз с [уточнити]) | выбор действия восстановления по скомпрометированным датчикам для одного аппарата (DeLorean) | Q3: ACM AsiaCCS'24, pp. 915–929, DOI 10.1145/3634737.3644997, ПТ; **одна из трёх ближайших работ** | | | |
| 3 | [Flueratoru et al., 2022] | C3 3.6.3 (с [уточнити]) | σ дальномера, смещение за препятствиями | **расхождение:** в CH3 — IEEE IoT J. 2022; в LIT_CHECK проверена Flueratoru 2020, GLOBECOM (DOI 10.1109/GLOBECOM42002.2020.9347984). Выяснить, какая работа содержит использованные числа | | | |
| 4 | [MAVLink, Message Signing] | C3 3.1.2 (с [уточнити]) | MAVLink 2 предусматривает необязательную подпись | электронный ресурс (mavlink.io); плюс проверить поддержку в PX4 на коммите стенда | | | |
| 5 | MITRE ATT&CK for ICS | C3 3.1 (с [уточнити]), табл. техник | рамка моделирования; коды T0856, T0832, T0826, T0814, T0860, T0821, T0804, T0831, T0813, T0803 | электронный ресурс; **сверить каждый код с названием техники** | | | |
| 6 | [Schneier, 1999] | C3 3.1 (с [уточнити]) | деревья атак | Schneier B. Attack Trees. Dr. Dobb's Journal, 1999 — сверить том/номер | | | |
| 7 | [Bashendy et al., 2023] | C3 | обзор IRS для CPS | Q3: Computers & Security 124:102984, DOI 10.1016/j.cose.2022.102984; авторы не сверены; вероятно = L№23 | | | |
| 8 | [Cardenas et al., 2011] | C3 3.1 | CPS: меняются допущения о доверии и доступе | какая работа Cardenas 2011 — сверить | | | |
| 9 | [Humayed et al., 2017] | C3 3.1 | то же | вероятно, Cyber-Physical Systems Security — A Survey, IEEE IoT J. 2017 — сверить | | | |
| 10 | [Kerns et al., 2014] | C4 (2 раза) | удержание позиции захватывается спуфингом | Q2: J. Field Robotics 31(4):617–636, DOI 10.1002/rob.21513, АН | | | |
| 11 | [Mykytyn et al., 2023] (+) | C3, C4 | проверка GPS-дистанций по UWB-дальностям | Q1: MECO-2023, IEEE 10154998, arXiv 2301.12766, ПТ; **ближайшая работа**; экспериментов нет | | | |
| 12 | [Bi et al., 2024] (+) | C3, C4 | обнаружение как задача допустимости локализации (SDP) | Q1: IEEE TIFS 19, arXiv 2312.03787, ПТ; DOI не сверен | | | |
| 13 | [Park & Yoo, 2026] (+) | C3, C4 (по 2 раза) | общий медленный сдвиг роя невидим для относительных детекторов | Q1: arXiv 2608.06885, ПТ, **препринт**; **ближайшая работа**; проверить, не вышла ли рецензированная версия | | | |

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

Flueratoru 2020 GLOBECOM (Q6) — см. B№3.

---

## D. Утверждения в тексте, которые надо подтвердить источником (не библиография)

| D№ | Где | Что проверить |
|---|---|---|
| 1 | C3 3.1, таблица техник | каждый код ATT&CK for ICS соответствует названию и смыслу сценария (B№5) |
| 2 | C3 3.1.2 | MAVLink 2 signing поддерживается PX4 на коммите стенда `9fe69d4f33` (документация PX4) |
| 3 | C3 3.6.3 | числа σ и смещения дальномера взяты из той работы Flueratoru, на которую ссылаемся (B№3) |
| 4 | C3 3.2 / N | формулировки о DeLorean, Mykytyn, Park & Yoo соответствуют их тексту (шаг 1.4) |
| 5 | C4 4.6 | Kerns 2014: «удержание позиции захватывается спуфингом» — есть ли это в статье именно так |

## Кандидаты прохода 2 (сейчас не проверяются)

- Программные средства стенда: PX4 Autopilot, Gazebo (gz-sim 8), MAVSDK, MAVLink, mavlink-router, ZeroMQ — ссылки на документацию.
- Failsafe PX4 и ArduPilot при недостоверной оценке позиции (из NOVELTY_DRAFT).
- Работы о самовосстановлении роя и CPS с физическими метриками исхода (из NOVELTY_DRAFT).
- Источник для описания поиска в 2.2 (если нужен).

## Порядок шага 1.2 (партии)

| Партия | Что | Почему первой |
|---|---|---|
| 1 | B№1–13 | закрывают [уточнити] в разделе 3 до переноса в docx; три ближайшие работы |
| 2 | C№1–12 | спуфинг, обход EKF, восстановление — ядро новизны |
| 3 | C№13–21 | архитектуры, кооперативная локализация, UWB |
| 4 | L№1–10 | |
| 5 | L№11–20 | |
| 6 | L№21–30 | |
