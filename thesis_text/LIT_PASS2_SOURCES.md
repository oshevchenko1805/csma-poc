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

Далі: партія 3 — пошук, чи немає ще робіт, ближчих до пунктів новизни 1–3 (кооперативне виявлення з перевіркою поза доменом відмови; вибір дії за класом скомпрометованих даних у групі). Після неї — заповнення таблиці 2.7.
