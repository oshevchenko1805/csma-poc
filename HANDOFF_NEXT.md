> 🛑 **ЧИСЛА ДЕТЕКЦИИ УСТАРЕЛИ (4 августа).** Поле `detected` считалось
> без пост-атакового гейта и без проверки `target_uav`, поэтому
> передатаковые ложные срабатывания шли в зачёт. Верные значения:
> detector_takeout **0/28, 0/30**, 30/30; monitor_takeout **0/28**,
> 29/30, 30/30; gps_spoofing 14/15, 15/15, **14/15**. Механизм и
> последствия — `RESULTS_NOTES.md`, R18. Действующая таблица —
> `HANDOFF_CH45.md` §3.1.

# HANDOFF — CSMA PoC: loss-sweep ЗАКРЫТ → кампания + свипы + главы

Прочитать **этот файл + `PROJECT_STATE.md` + `RESULTS_NOTES.md` (R10)** в
репо, прежде чем что-либо делать. Репо самодостаточно.
HEAD = `e666a56` (подтвердить `git log --oneline -1`). **736 pytest passing.**

## Как со мной работать
- Русский, коротко, по сути, **один микро-шаг за раз**. Подтверждаю pytest
  перед следующим шагом (гоняю на VM сама, ты pytest на VM не запускаешь).
- Не знаешь / не сработает / мало инфы — говори сразу, не гадай. Брутально
  честно. Костыль от чистой инженерии отделять явно. Предлагаешь дизайн —
  сам оцени, норм ли он, а не жди подтверждения.
- Файлы — **anchored-патчем**: python-скрипт с `assert src.count(anchor)==1`
  на каждый якорь + guard от повторного применения. Большие файлы (>300
  строк) — только патчем. Якоря — **однострочные** где можно (multi-line
  часто не совпадают по пробелам). Я переношу патч на VM через nano —
  **паста иногда бьёт последнюю строку** (лишний символ), проверяй
  `py_compile` патча перед запуском.
- Команды paste-safe: без пустых строк внутри кавычек, commit одной строкой.
- **GitHub raw для этого репо ОТДАЁТ УСТАРЕВШИЙ КЭШ** — читать реальные
  файлы **с VM** (проси `sed -n`/`grep`), не с `raw.githubusercontent`.
  Это стоило нам путаницы; не повторять.
- Инструменты Claude: Read/Write/Edit по outputs, sandbox-bash
  (py_compile/логику проверить), web_fetch. pytest репо на VM — только V.

## Проект (одним абзацем)
PhD-монография (укр.). PoC: рой из 3 UAV, **Cybersecurity Mesh Architecture
с self-healing**, сравнение 3 архитектур (A централизованная / B
сегментированная / C CSMA+self-healing) × атаки, метрики MTTD/MTTR/impact/
FP-FN + mission resilience. Различия архитектур — **только через YAML+DI**,
никаких `if architecture` в domain-коде. Вклад = архитектурный паттерн +
эмпирическая характеризация; детектор — сменный компонент (не вклад).
- Env: Ubuntu 22.04 ARM64 VM (UTM/M4 Pro). Репо `~/csma_poc_v2/`, `.venv`,
  приватный GitHub `oshevchenko1805/csma-poc`, `origin/main`.
- Стек: PX4 SITL + Gazebo (gz-sim) + GZBridge, MAVSDK-Python, pymavlink,
  mavlink-routerd, ZeroMQ mesh (localhost), pytest.

## Что ЗАКРЫТО этим марафоном (не переделывать)
**Loss-свип (главная статистика, handoff item 4) — ЗАКРЫТ = R10.**
Сценарий: C × `detector_takeout+gps_spoofing`, локальные детекторы цели
заглушены → ловит только mesh cross_check соседей → под loss кривая.
Результат (255 валидных прогонов, belief-гейт):
- detection rate монотонно **0.96 → 0.25** при loss 0→0.65, **плато ~0.46**
  на 0.45–0.55, **не обваливается в ноль** (устойчивая деградация);
- **MTTD median ~7.5–8 c, от loss не зависит**;
- baseline A/B ≈ 0 (без mesh не ловят вовсе);
- cross_check FP-фон ~1.4% (до-атаковые ложные) — для Ch.4;
- данные/рисунок: `runs_final/detection_vs_loss.{csv,png}`.
Анализатор: `scripts/analyze_loss_sweep.py`.

## КРИТИЧЕСКИЕ тех-факты этого марафона (не переоткрывать)
1. **belief_divergence-гейт ОБЯЗАТЕЛЕН для любых gps-сценариев.** Трайл
   считается, только если спуф реально применился: `belief_divergence.uavs.
   uav_0.peak_horiz_m > 10 м` (сел ~50 м, no-op ~1 м). Иначе это «атаки не
   было», НЕ «не задетектил». Без гейта фабрикуется ложный коллапс.
   Анализатор уже гейтит; для новых gps-анализов — тоже гейтить.
2. **GPS-спуф (`SIM_GPS_OFF_N`) применяется НЕнадёжно в длинных батчах,
   быстрее при высоком loss.** Причина — не хватало settle: mesh (ZeroMQ
   под высоким loss) медленно встаёт, GZBridge пропускает окно применения
   офсета. **ФИКС В РЕПО:** `run_batch --post-launch-settle` (default 20 c).
   Всегда использовать для gps-кампаний. При очень высоком loss (0.6+) в
   длинном батче может всё равно деградировать — тогда короткие свежие
   чанки или петля одиночных прогонов (`sleep 25` после launch дала 12/12).
   **Одиночный прогон долетает всегда** при любом loss.
3. **`run_batch` cleanup теперь добивает `mavsdk_server`** (иначе
   прогрессирующий TimeoutError за длинный батч). Уже в репо.
4. **falco ДОЛЖЕН быть masked.** Он флудил `/var/log/syslog` до 60 ГБ
   (забивал диск → disk-guard стопил свип) + syscall/I/O-нагрузка портила
   тайминг. Проверять каждую сессию: `systemctl is-active falco-modern-bpf`
   (ждём inactive). Если воскрес: `sudo systemctl mask 'falco*' 'falcoctl*'`.
5. **Диск:** run-данные теперь в `.gitignore` (`runs*/`, `pilot_archive/`).
   Следить `df -h /`. Если пухнет — искать `/var/log/syslog` (falco).
6. **run_batch resumability пропускает трайлы с exit 0.** Но «спуф не сел»
   = exit 0 → resume их НЕ перегонит. Перед пере-прогоном уровня удалять
   деградировавшие dir'ы (или весь `dt_loss_X`).
7. Ground truth — только Gazebo: `belief_divergence` (валидность атаки),
   `flight_at_attack` (летел ли в момент атаки). Оценка PX4 отравлена
   спуфом, мониторы убиваются атаками.
8. **4-й UDP endpoint в router ломает** MAVSDK PARAM_SET. Держать 3.
   Params PX4 в `rootfs/{0,1,2}/parameters*.bson` — чистить между прогонами
   (run_batch делает). gRPC-порты 50051-53 mission, 50054-56 loiter.
9. Между прогонами вручную: полный teardown + `sleep 25` после launch, иначе
   gRPC `Connection refused` на 50051 (mavsdk_server не успел).

## Решения, которые НЕ переобсуждать
- Различия архитектур — только конфигом (`configs/architecture_{a,b,c}.yaml`).
- Детектор сменный (пишем в Ch.4).
- MTTR доминирует холодный старт PX4, не архитектура (в Ch.5 честно).
- CPU/RAM не мерить (в VM под 3×PX4 шум).
- Все три арх. несут детектор `gps` локально → A/B детектят обычный gps
  спуф (~3 c); differentiator C — cross_check-консенсус + recovery, НЕ
  сам факт детекции. (Для `detector_takeout+gps` A/B не ловят вовсе — mesh
  единственный путь.)

## Work queue (следующая фаза)
| # | Пункт | Статус |
|---|-------|--------|
| 1 | **Полная кампания A/B/C × {none,comm_disruption,command_injection,gps_spoofing} × N=30**, CI — ядро сравнения архитектур (handoff item 3). run_batch с `--post-launch-settle 20`. gps-клетки гейтить по belief. | 🔴 следующее |
| 2 | spoof-magnitude свип (SIM_GPS_OFF_N: 10/25/50/75/100 м) | 🔴 |
| 3 | k-мониторов свип (устойчивость к takeout) | 🔴 |
| 4 | `metrics/plots.py` — публикационные рисунки (шаблон — analyze_loss_sweep.py) | 🔴 |
| 5 | Анализ → главы 4–5 (написание) | 🔴 |

Замечание по кампании: 12 клеток × N=30 = 360 прогонов × ~3.7 мин + settle
20 c ≈ ~15 ч. Гнать в tmux, `caffeinate` на Маке, falco masked, следить
belief-гейт на gps-клетках (если no_atk растёт — чанковать/петля). Свип по
loss/magnitude — временно править `mesh`/атаку в конфиге или через CLI-флаги
run_one (`--mesh-loss-prob`; для magnitude флага нет — правь атаку/конфиг).

## Типовой чистый одиночный прогон (для отладки)
```
cd ~/csma_poc_v2
./scripts/kill_router.sh 2>/dev/null; ./scripts/kill_px4.sh 2>/dev/null
pkill -9 -f gz; pkill -9 -f px4; pkill -9 -f mavsdk_server; sleep 2
rm -f ~/PX4-Autopilot/build/px4_sitl_default/rootfs/{0,1,2}/parameters*.bson
./scripts/launch_px4.sh && ./scripts/launch_router.sh
sleep 25
source .venv/bin/activate
python scripts/run_one.py --arch c --attack gps_spoofing --mission mavsdk \
  --target-uav uav_0 --attack-at-sec 90 --observation-after-attack-sec 60 \
  --px4-pid-file /tmp/px4_pids
```

## Первый шаг в новом чате
Подтвердить на VM: `git log --oneline -1` (= e666a56), `python -m pytest -q`
(= 736), `systemctl is-active falco-modern-bpf` (= inactive), `df -h /`.
Потом проектируем кампанию (item 1): состав клеток, N, порядок, belief-гейт
для gps, оценка времени.
