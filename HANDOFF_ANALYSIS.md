# HANDOFF — CSMA PoC: КАМПАНИЯ ЗАКРЫТА → рисунки + главы 4–5

Прочитать **этот файл + `PROJECT_STATE.md` + `RESULTS_NOTES.md`** в репо,
прежде чем что-либо делать. Репо самодостаточно. Подтвердить на VM:
`git log --oneline -1`, `python -m pytest -q` (ожидаем **750 passed**),
`systemctl is-active falco-modern-bpf` (inactive), `df -h /`.

**Тяжёлая симуляция ЗАВЕРШЕНА. Новых больших прогонов НЕ нужно.**
Дальше — только анализ (`campaign_report.py` читает готовые данные) и текст.

## Как со мной работать
- Русский, коротко, по сути, один микро-шаг за раз. Подтверждаю pytest
  перед следующим шагом (гоняю на VM сама).
- Не знаешь / не сработает / мало инфы — говори сразу, брутально честно.
  Костыль от чистой инженерии отделять явно. От «почти работает» —
  предупреждать до вложения часов, а не после.
- Файлы — **anchored-патчем** (python-скрипт с `assert count==1` на якорь
  + guard от повторного применения) либо новым файлом целиком. Большие
  файлы правим только патчем. Переношу на VM через nano.
- **GitHub raw для этого репо ОТДАЁТ УСТАРЕВШИЙ КЭШ** для только что
  запушенного — свежие числа читать **с VM** (`sed`/`grep`/скрипт). Логику
  стабильного кода по raw читать можно.
- Claude файлы на Маке не видит; всё — через VM (V запускает команды).

## Проект (одним абзацем)
PhD-монография (укр.). PoC: рой из 3 UAV, Cybersecurity Mesh Architecture
с self-healing. Сравнение 3 архитектур (A централизованная / B
сегментированная / C CSMA+self-healing) × атаки, метрики табл. 3.13
(MTTD/MTTR/detection/FP-FN/isolation/recovery/mission resilience/
coordination). Различия архитектур — **только через YAML+DI**, никаких
`if architecture` в domain-коде. Вклад = архитектурный паттерн +
эмпирическая характеризация; детектор — сменный компонент (не вклад).
Env: Ubuntu 22.04 ARM64 VM (UTM/M4 Pro). Репо `~/csma_poc_v2/`, `.venv`,
приватный GitHub `oshevchenko1805/csma-poc`, `origin/main`. Стек: PX4
SITL + Gazebo + mavlink-routerd + MAVSDK-Python + ZeroMQ mesh + pytest.

## Что ЗАКРЫТО этой сессией (не переделывать)
**Полная кампания сравнения архитектур — ЗАКРЫТА.** 254 валидных прогона,
belief-гейт на gps-семействе, Wilson 95% CI. Данные:
`runs_campaign/{std_pass1, ci_pass1-3, dt_pass1-6, mt_pass1-6}`,
сводка — `runs_campaign/campaign.csv`. Анализатор — `campaign_report.py`.

**Detection rate (valid trials, Wilson 95% CI):**
| Атака | A | B | C |
|---|---|---|---|
| detector_takeout+gps | 0.07 [0.02,0.23] | 0.10 [0.03,0.26] | **1.00 [0.89,1.00]** |
| monitor_takeout+gps | 0.07 (A-домен рухнул) | 0.97 [0.83,0.99] | **1.00 [0.89,1.00]** |
| gps_spoofing | 1.00 | 1.00 | 1.00 |
| comm_disruption | 1.00 | 1.00 | 1.00 |
| command_injection | 1.00 | 1.00 | 1.00 |
| none (baseline) | FP 0/5 | FP 0/5 | FP 0/5 |

**Mission degradation, м (Gazebo ground truth) — сдерживание ущерба:**
| Атака | A | B | C |
|---|---|---|---|
| detector_takeout+gps | 49.6 | 49.8 | **0.97** |
| monitor_takeout+gps | — (спуф не гейтится) | 48.8 | **20.8** |
| command_injection | 36.5 | 37.6 | **2.84** |
| gps_spoofing | 49.8 | 49.9 | **12.8** |
| comm_disruption | 2.3 | 2.0 | 1.3 |

**Residual mission function:** detector_takeout A/B=0.67 → C=1.00;
command_injection A/B=0.67 → C=0.96; gps A/B=0.67 → C=0.73. **MTTD:**
detector_takeout C=7.47 c; gps ~3 c; comm ~3.4 c.

**Три главных вывода (ядро глав 4–5):**
1. **Выигрыш при компрометации плоскости безопасности.** detector_takeout:
   локальный детектор заглушён → A/B слепы (7–10%), C ловит через
   mesh cross_check (100%) и сдерживает (0.97 м vs ~50 м).
2. **SPOF централизации.** monitor_takeout: общий домен A рушит все
   мониторы (детекция 7%, борт угнан 49.9 м при belief=1 м — ложно-чистая
   картина); сегментация B (97%) и mesh C (100%) выживают.
3. **Цена автоматики (честный трейд-офф для Ch5).** В штатном режиме C не
   даёт выигрыша в детекции (MTTD 7.5 c консенсуса vs ~3 c локально) и
   имеет FP-фон ~1.4%; ложное срабатывание запускает recovery, зря
   уводящий здоровый борт (см. крит-факт 5). comm_disruption: C не
   помогает — недоступность ≠ компрометация.

## КРИТИЧЕСКИЕ тех-факты этой сессии (не переоткрывать)
1. **command_injection = guard + mission-resume.** `enforcement/
   command_guard.py`: UDP-релей, фильтрует по MAVLink sysid (не по порту).
   Инжектор шлёт в guard (14590+i), guard форвардит в PX4 (14580+i); по
   recovery в C дропает не-whitelist sysid. Плюс `FilterCommandsHandler`
   зовёт `MissionResumeRunner.resume()` (start_mission) — отменяет
   перехват, случившийся до включения фильтра (первый кадр всегда доходит
   до детекции). Результат: C=2.84 м/resid 0.96 vs A/B=37 м/0.67. Порт-
   артефакта нет — фильтр по содержимому. Юнит-тесты: `tests/
   test_command_guard.py`, `tests/test_filter_resume.py`.
2. **heartbeat_loss recovery УБРАН.** Был `restart_process` (перезапуск
   PX4 в воздухе, портил миссию: 36 м). Теперь действия нет — недоступность
   ≠ компрометация. Старое отображение сохранено как
   `COARSE_POLICY_REASON_TO_ACTION` в `decision/recovery.py` для сравнения
   политик в Ch4. Регресс-тесты в `tests/test_decision_recovery.py`.
3. **belief_divergence НЕДОСТОВЕРЕН под monitor_takeout.** Атака убивает
   мониторы, чья телеметрия нужна belief → читает ~1 м при физическом
   угоне 49.9 м. Для gps-валидности под monitor_takeout гейтить по
   **траектории Gazebo** (`mission_degradation_m`), НЕ по belief. Везде
   иначе — belief-гейт (peak_horiz>10 м) обязателен. Это уже в
   `campaign_report.py`.
4. **Харнесс закалён.** `run_batch` теперь: circuit-breaker (стоп после
   4 подряд падений, rc=3) + verified teardown (ждёт реальной смерти
   px4/gz/mavsdk). Первая 16-часовая кампания зависла (~термотроттлинг M4
   → Gazebo грузится дольше фикс. 20 c → PX4 стартует до готовности →
   `is_armable` не наступает → каскад TimeoutError) без fail-fast и
   смолотила сутки. **Перепрогон — короткими чанками (≤15) с охлаждением
   между** (`run_reruns.sh`). Одиночный прогон с полным teardown долетает
   всегда (проверено 4/4).
5. **FP-издержка C (находка для Ch5).** Ложный gps/EKF-FP на здоровом
   борту → loiter → ущерб миссии. Фон ~1.4%. Раздувает разброс
   mission_degradation у C (report'ить медиану + долю FP-прогонов). Это
   честная цена self-healing, а не баг; детектор сменный — не чинить.
6. **Честные оговорки метрик (в текст, не баги):** MTTD command_injection
   ~10 мс = регистрация в процессе, не латентность канала. Time to
   Isolation ≈ 0 = изоляция синхронна детекции. detector_takeout A/B
   ~7–10% (не 0) = локальный детектор изредка успевает до заглушки.

## Решения, которые НЕ переобсуждать
- Различия архитектур — только конфигом (`configs/architecture_{a,b,c}.yaml`).
- Детектор сменный (пишем в Ch4). command_injection recovery = guard(sysid)
  + resume mission. comm_disruption: C честно без recovery-преимущества.
- spoof-magnitude свип выкинут (характеризует детектор, не вклад).
- N=30 для takeout-ядра, N=15 стандарт, N=5 где помечено.
- Ground truth — только Gazebo (`trajectory.jsonl`, `belief_divergence`
  где мониторы живы). Оценка PX4 отравлена спуфом.

## Work queue (следующая фаза — БЕЗ прогонов)
| # | Пункт | Статус |
|---|-------|--------|
| 1 | `metrics/plots.py` — публикационные рисунки из `campaign.csv` (detection-bar с CI, degradation-bar, per-cell). Шаблон — `analyze_loss_sweep.py`. | 🔴 следующее |
| 2 | Написание глав 4–5 из результатов выше + R10 (loss-свип). | 🔴 |
| 3 | Опционально: k-мониторов свип, масштаб 5–7 дронов, ML-детектор. | ⚪ |

## Команды для получения результатов
```
cd ~/csma_poc_v2 && source .venv/bin/activate
# Полный отчёт кампании (belief-гейт, Wilson CI, все метрики табл. 3.13):
python campaign_report.py runs_campaign/std_pass1 \
  runs_campaign/ci_pass{1,2,3} \
  runs_campaign/dt_pass{1,2,3,4,5,6} \
  runs_campaign/mt_pass{1,2,3,4,5,6} --csv runs_campaign/campaign.csv
# Derived-метрики одной группы (диагностика клетки):
python -m metrics.derived runs_campaign/dt_pass1
# CSV для рисунков: runs_campaign/campaign.csv (254 валидных прогона)
```

## Первый шаг в новом чате
Подтвердить на VM `git log --oneline -1` и `python -m pytest -q` (=750),
затем прогнать команду отчёта выше и сверить числа с таблицами этого
файла. Потом проектировать `plots.py` (item 1) — какие рисунки нужны для
глав 4–5, из `campaign.csv`, без новых прогонов.
