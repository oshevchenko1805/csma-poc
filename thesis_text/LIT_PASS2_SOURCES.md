# Література, прохід 2: нові джерела (P3)

> Для авторки. Нові роботи — лише ті, що підкріплюють висновок розділу 2 або закривають відсутнє посилання в розділах 3–4 (CH2_PLAN.md). Перевірка — як у проході 1 (Crossref через вбудований браузер, сторінки видавців).

## Партія 1 — рамки, стандарти, статистика (29.09)

| № | Перевірка | Повні вихідні дані | Для чого |
|---|---|---|---|
| N1 | **ок** | Kephart J. O., Chess D. M. The vision of autonomic computing. *Computer*. 2003. Vol. 36, No. 1. P. 41–50. DOI: 10.1109/MC.2003.1160055 | 2.4, 3.2: цикл самовідновлення (моніторинг — аналіз — план — виконання) |
| N2 | **ок** | Ross R., Pillitteri V., Graubart R., Bodeau D., McQuaid R. Developing Cyber-Resilient Systems: A Systems Security Engineering Approach : NIST Special Publication 800-160 Vol. 2 Rev. 1. Gaithersburg : NIST, 2021. DOI: 10.6028/NIST.SP.800-160v2r1 | 2.4–2.5: кіберстійкість як рамка |
| N3 | **ок** | Rose S., Borchert O., Mitchell S., Connelly S. Zero Trust Architecture : NIST Special Publication 800-207. Gaithersburg : NIST, 2020. DOI: 10.6028/NIST.SP.800-207 | 2.5: довіра до джерел, zero trust |
| N4 | **ок (книга)** | Kopetz H., Steiner W. Real-Time Systems: Design Principles for Distributed Embedded Applications. 3rd ed. Cham : Springer, 2022. DOI: 10.1007/978-3-031-11992-7 | розділ 3: «домен відмови» ↔ fault-containment unit / region. Розділ і сторінку звірити при цитуванні |
| N5 | **ок** | Wilson E. B. Probable Inference, the Law of Succession, and Statistical Inference. *Journal of the American Statistical Association*. 1927. Vol. 22, No. 158. P. 209–212. DOI: 10.1080/01621459.1927.10502953 | розділи 3–4: 95 % інтервал Wilson (зараз без посилання) |
| N6 | **ок (без DOI)** | Holm S. A Simple Sequentially Rejective Multiple Test Procedure. *Scandinavian Journal of Statistics*. 1979. Vol. 6, No. 2. P. 65–70 | розділи 3–4: поправка Holm (зараз без посилання). У Crossref запису немає (JSTOR 4615733) |
| N7 | **ок** | Efron B. Bootstrap Methods: Another Look at the Jackknife. *The Annals of Statistics*. 1979. Vol. 7, No. 1. P. 1–26. DOI: 10.1214/aos/1176344552 | розділ 4: бутстреп-інтервали (перевірити, чи вони є в тексті) |
| N8 | **ок** | Nosek B. A., Ebersole C. R., DeHaven A. C., Mellor D. T. The preregistration revolution. *Proceedings of the National Academy of Sciences*. 2018. Vol. 115, No. 11. P. 2600–2606. DOI: 10.1073/pnas.1708274114 | 2.6, 3.5: заздалегідь зафіксовані гіпотези |

## Партія 2 — штатні механізми автопілотів, засоби стенда, Sung 2022 (29.09)

| № | Перевірка | Повні вихідні дані | Що підтверджено / для чого |
|---|---|---|---|
| N9 | **ок (веб)** | Using PX4's Navigation Filter (EKF2) // PX4 Autopilot User Guide (main). URL: https://docs.px4.io/main/en/advanced_config/tuning_the_ecl_ekf.html (дата звернення: 29.09.2026) | Інноваційні перевірки: «All observations have a statistical confidence checks applied to the innovations», межа — параметри EKF2_*_GATE; pos_test_ratio = відношення інновації горизонтальної позиції до межі; довге відхилення даних → EKF «attempt a reset of the states». Пояснює режими серії B0 і стрибок оцінки (2.3б, 3.6, 4.6) |
| N10 | **ок (веб)** | Safety (Failsafe) Configuration // PX4 Autopilot User Guide (main). URL: https://docs.px4.io/main/en/config/safety.html (дата звернення: 29.09.2026) | Position Loss Failsafe спрацьовує, лише коли оцінка позиції стає **недійсною** (тайм-аут даних або перевищення порогу похибки COM_POS_FS_EPH). Підмінена, але узгоджена оцінка його не запускає. Довід до 2.4 і відповіді «це вже є в автопілоті» |
| N11 | **ок (веб)** | EKF Failsafe // ArduPilot Copter Documentation. URL: https://ardupilot.org/copter/docs/ekf-inav-failsafe.html (дата звернення: 29.09.2026) | Спрацьовує, коли дві з дисперсій EKF (компас, позиція, швидкість) перевищують FS_EKF_THRESH протягом 1 с; дія за замовчуванням — Land. Про спуфінг окремо не сказано. Той самий довід для ArduPilot |
| N12 | **ок** | Meier L., Honegger D., Pollefeys M. PX4: A node-based multithreaded open source robotics framework for deeply embedded platforms. *2015 IEEE International Conference on Robotics and Automation (ICRA)*. 2015. P. 6235–6240. DOI: 10.1109/ICRA.2015.7140074 | розділ 3.6: автопілот стенда |
| N13 | **ок** | Koenig N., Howard A. Design and use paradigms for Gazebo, an open-source multi-robot simulator. *2004 IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)*. 2004. Vol. 3. P. 2149–2154. DOI: 10.1109/IROS.2004.1389727 | розділ 3.6: симулятор (класична робота). Стенд використовує gz-sim 8 (Harmonic) — додатково сторінка документації gazebosim.org з датою звернення |
| N14 | **ок** | Koubaa A., Allouch A., Alajlan M., Javed Y., Belghith A., Khalgui M. Micro Air Vehicle Link (MAVlink) in a Nutshell: A Survey. *IEEE Access*. 2019. Vol. 7. P. 87658–87680. DOI: 10.1109/ACCESS.2019.2924410 | 3.1, 3.6: протокол MAVLink (разом із [MAVLink, Message Signing]) |
| N15 | **ок (веб)** | MAVSDK Guide / Dronecode Foundation. URL: https://mavsdk.mavlink.io/main/en/index.html (дата звернення: 29.09.2026) | 3.6: бібліотека керування місією (стенд — MAVSDK-Python 3.15.3) |
| N16 | **ок (веб)** | mavlink-router: Route mavlink packets between endpoints : GitHub repository. URL: https://github.com/mavlink-router/mavlink-router (дата звернення: 29.09.2026) | 3.6: маршрутизація MAVLink між кінцевими точками стенда |
| N17 | **ок (книга, без DOI)** | Hintjens P. ZeroMQ: Messaging for Many Applications. Sebastopol : O'Reilly Media, 2013. ISBN 978-1-449-33406-2 | 3.6: транспорт mesh |
| N18 | **ок** | Sung Y.-H., Park S.-J., Kim D.-Y., Kim S. GPS Spoofing Detection Method for Small UAVs Using 1D Convolution Neural Network. *Sensors*. 2022. Vol. 22, No. 23. Art. 9412. DOI: 10.3390/s22239412 | **Твердження звірено з текстом статті:** «The flight control system forced the manipulated drone to drift to its previous position according to the hovering command. However, this deviation could not be reduced.» Реальні польоти (Pixhawk і DJI Phantom 4) з працюючим спуфером. Для 2.4 і мотиву H2 (механізм відомий, наш внесок — вимір на рівні архітектури і інша дія) |

**Висновок для розділу 2 (2.4):** штатні failsafe PX4 і ArduPilot реагують на **недійсну або ненадійну** оцінку, а не на узгоджено підмінену. Тому реакція, що спирається на оцінку позиції, лишається вразливою — це підтверджено документацією (N10, N11) і реальними польотами (N18, Kerns 2014).

## Партія 3 — цільовий пошук робіт, ближчих до пунктів новизни (29.09)

Запити (веб-пошук + Crossref): кооперативне виявлення підміни GNSS у рої за дальностями; дія відновлення за довіреними датчиками після спуфінгу; CSMA для БПЛА; PX4 SITL + Gazebo, кілька БПЛА, спуфінг, самовідновлення; відновлення після атак на датчики в мультиробототехнічних системах.

| № | Перевірка | Повні вихідні дані | Що зроблено | Відношення до роботи |
|---|---|---|---|---|
| N19 | **ок (препринт); журнальний DOI не підтверджено** | Sharma D. D., Singh S. N., Lin J. Adaptive GPS Spoofing Detection and Mitigation Strategy Using Blockchain-Enabled Machine Learning for Networked UAVs. *Recent Advances in Electrical and Electronic Engineering*. 2026. Препринт: Authorea, 2024. DOI: 10.22541/au.172906784.48776529/v1 | Після виявлення апарат «switches to … control law using data available from trusted sensors» (IMU, барометр), ML прогнозує правильну точку маршруту; для групи — консенсус «proof of location». ArduPilot + MATLAB UAV Toolbox | **Найближча до п. 2 новизни (H2)** для окремого апарата: принцип «не спиратися на підмінені дані» є. Відмінності: немає PX4 EKF2, архітектур групи, фізичного зносу за істинним положенням і заздалегідь зафіксованої гіпотези. Цитувати в 2.4 разом з DeLorean. Журнальний DOI 10.2174/0123520965391556250614175147 у Crossref не знайдено — звірити |
| N20 | **ок** | Ranganathan A., Belfki A., Closas P. Analyzing the Impact of GNSS Spoofing on the Formation of Unmanned Vehicles Swarms. *Proc. 36th International Technical Meeting of the Satellite Division of The Institute of Navigation (ION GNSS+ 2023)*. 2023. P. 3138–3147. DOI: 10.33012/2023.19438 | Вплив спуфінгу на формацію рою (Voronoi / Lloyd), ArduPilot + Gazebo; до 3× довша збіжність, до 5× довший шлях. Виявлення і відновлення не розглядаються | 2.2–2.3: вразливість рою як системи; стенд того ж класу |
| N21 | **ок** | Tariq U., Ahanger T. A. Multi-model fusion for robust detection and resilient mitigation of BeiDou spoofing in decentralized UAV swarm systems. *PeerJ Computer Science*. 2026. Vol. 12. Art. e3875. DOI: 10.7717/peerj-cs.3875 | Калманівський трекер залишків + ансамбль ML + трансформер; власна симуляційна платформа; точність ~99 %, хибні тривоги < 2 %, пом'якшення за ~3 с, успіх місії > 97 % | 2.3 (а, в): рій, виявлення + пом'якшення. Відмінності: без автопілота в контурі, без вибору місця перевірки відносно домену відмови, без порівняння архітектур. Той самий перший автор, що й C№12 |
| N22 | **ок** | Gil S., Kumar S., Mazumder M., Katabi D., Rus D. Guaranteeing spoof-resilient multi-robot networks. *Autonomous Robots*. 2017. Vol. 41, No. 6. P. 1383–1400. DOI: 10.1007/s10514-017-9621-5 | Довіра між роботами через фізичний рівень (радіосигнатури) проти Sybil-атак | 2.5: довіра на основі незалежних фізичних вимірювань у мультиробототехніці — аналог ідеї «незалежне джерело» |
| N23 | **метадані ок; текст не відкрито** | Kose K., Wing J., Kose N. A., Guadarrama-Trejo C., Sowers A., Rasheed A. A UAV Testbed for Diagnosing Hardware Vulnerabilities: Quantifying Sim-to-Real Discrepancies in PX4 Flight Logs. *Sensors*. 2026. Vol. 26, No. 10. Art. 3188. DOI: 10.3390/s26103188 | Розбіжності SITL і реального польоту PX4 за журналами | 2.6 і обмеження (розділ 5): межа перенесення результатів SITL. Відкрити текст перед цитуванням |

**Висновок партії 3:** нових робіт, які поєднують (а) перевірку поза доменом відмови атакованого апарата, (б) вибір дії відновлення за класом скомпрометованих даних у групі, (в) PX4 у контурі і (г) порівняння архітектур, не знайдено. Найближча нова робота — Sharma et al. 2026 (N19) для п. 2: окремий апарат, ArduPilot/MATLAB.
**Пропозиція до NOVELTY_DRAFT (не внесено):** у п. 1 посилання «[Dash et al., 2024]» → «[Dash et al., 2024; Sharma et al., 2026]».

Далі: заповнення таблиці 2.7 (читання найближчих робіт за стовпцями).

## Партія 4 — статистика, додатково до партії 1 (29.09)

| № | Перевірка | Повні вихідні дані | Для чого |
|---|---|---|---|
| N24 | **ок** (Crossref) | Newcombe R. G. Interval estimation for the difference between independent proportions: comparison of eleven methods. *Statistics in Medicine*. 1998. Vol. 17, No. 8. P. 873–890. DOI: 10.1002/(SICI)1097-0258(19980430)17:8<873::AID-SIM779>3.0.CO;2-I | розділи 3–4: інтервал Newcombe для різниці часток |
| N25 | **ок** (Crossref) | Mann H. B., Whitney D. R. On a Test of Whether one of Two Random Variables is Stochastically Larger than the Other. *The Annals of Mathematical Statistics*. 1947. Vol. 18, No. 1. P. 50–60. DOI: 10.1214/aoms/1177730491 | розділи 3–4: критерій Манна–Вітні |

Точний критерій Фішера — класичний, без окремого посилання (за потреби: Fisher R. A. The Design of Experiments, 1935).

**Вставки в розділи 3–4 (29.09):** CH3 — Wilson, Newcombe, Holm, Mann & Whitney, Efron (примітка 3 до табл. метрик, п. 3.5.4); Nosek (п. 3.5.5); Koubaa (п. 3.1.2, MAVLink); Meier (PX4) і Koenig & Howard (Gazebo) (п. 3.5.2); MAVSDK, mavlink-router (п. 3.6.1–3.6.2); Hintjens (ZeroMQ, п. 3.6.4). CH4 — ті самі статистичні посилання в п. 4.1; «bootstrap … seed» → «бутстрепом із зафіксованим початковим значенням генератора» (P13).

## Рішення перед оформленням за ДСТУ 8302:2015 (29.09)

- Порядок списку — **алфавітний** (рішення авторки): вступ, розділи 1 і 5 пишуться пізніше, нумерація за першою згадкою зсувалася б. Посилання в тексті — номер у квадратних дужках: [12], [12, с. 5], [3; 7; 15].
- **N19 Sharma:** журнальний запис (DOI 10.2174/0123520965391556250614175147) не підтверджено — цитуємо препринт: Sharma D. D., Singh S. N., Lin J. Adaptive GPS Spoofing Detection and Mitigation Strategy Using Blockchain-Enabled Machine Learning for Networked UAVs : preprint. Authorea, 2024. DOI: 10.22541/au.172906784.48776529/v1. У CH2 ключ → [Sharma et al., 2024, препринт] (3 місця).
- **N23 Kose:** твердження в 2.6 (розбіжності SITL і реальних польотів у точності датчиків, впливі завад GPS, поведінці бортових ресурсів) звірено з анотацією (Crossref, 29.09) — відповідає.
- **L№27 Abdulrazak:** у Crossref тому LNCS немає (серія, с. 3–17, ISBN 978-3-031-09592-4) — оформлюємо серію без тому, не вигадуємо.
- CH3: [Phadke et al., 2022/2023] → [Phadke & Medrano, 2022/2023] (4 місця; двоє авторів, L№18–19).
- Ceviz et al., 2025 — дві різні роботи: огляд COMST (L№6; CH2, рядки 67, 69, 77) і FL-IDS в Internet of Things (L№8; CH2, рядок 89). У списку — обидві; при заміні на номери розрізняються за контекстом.
