"""
metrics/fp_census.py — перепис усіх хибних спрацювань, по одному рядку
на прогін.

Навіщо
------
Твердження про «ціну» архітектури C спиралось спершу на два прогони, а
потім на чотири. Обидва рази при розширенні вибірки механізм читався
інакше: спочатку «каскад подій», далі «радіус по мешу», далі — після
симетричного підрахунку — «глибина циклу». Вибірка з чотирьох прогонів
на три архітектури не витримує жодного з цих формулювань.

Тут рахуються **всі 17** валідних прогонів із хибним спрацюванням, одним
проходом, за визначеннями, зафіксованими ДО перегляду тринадцяти
недовезених прогонів. Скрипт нічого не інтерпретує: він виводить CSV.

Визначення (оголошені заздалегідь)
----------------------------------
`exposure`
    `clean_flight`  — базовий прогін (`attack == none`): рахується ВЕСЬ
                      політ, атаки не було взагалі;
    `pre_attack`    — атакуючий прогін: рахується лише вікно ДО
                      `inject_start`.
    Це різні експозиції, і змішувати їх в одну частоту не можна (R19.3).

`fp_events`
    security-події у вікні експозиції.

`accused_uavs`
    кількість РІЗНИХ `target_uav` серед цих подій. «Кого звинуватили».

`reporting_monitors`
    кількість РІЗНИХ `source` серед цих подій. «Хто доповів».

`isolation_events`, `recovery_requests`, `recovery_acks`
    відповідні події у тому ж вікні. `recovery_acks` — це дії, які
    ФАКТИЧНО виконано над справним апаратом; саме вони, а не кількість
    подій, розрізняли архітектури на вибірці з чотирьох.

`cascade_span_s`
    від першої до останньої security-події вікна. Нуль означає, що всі
    спрацювання одномоментні (як сплеск heartbeat), а не ланцюг.

`detectors`
    які детектори спрацювали, з кратністю.

`mission_degradation_m`, `phase_excess_m`, `residual_mission_func`
    наслідки для місії, з мастер-файла. Для базових прогонів це наслідки
    самої хибної тривоги, бо атаки не було.

Запуск
------
    python -m metrics.fp_census                       # у stdout
    python -m metrics.fp_census --csv runs_campaign/fp_census.csv

Потребує `merged.jsonl` кожного прогону у `figdata/`. Якщо чогось немає,
скрипт друкує рівно те, що треба довезти з VM, і не рахує часткову
вибірку мовчки.
"""

from __future__ import annotations

import argparse
import collections
import csv
import glob
import os
import sys

import metrics.derived as D
from metrics.plots import load, valid_rows, num, flag

MASTER = "runs_campaign/campaign_master.csv"
FIGDATA = "figdata/runs_campaign"

FIELDS = [
    "run_id", "architecture", "attack", "exposure", "target_uav",
    "fp_events", "accused_uavs", "reporting_monitors",
    "isolation_events", "recovery_requests", "recovery_acks",
    "cascade_span_s", "detectors", "accused_list", "monitor_list",
    "mission_degradation_m", "phase_excess_m", "residual_mission_func",
]

WINDOW_TYPES = ("security", "isolation_announce",
                "recovery_request", "recovery_ack")


def fp_runs(master: str = MASTER) -> list:
    """Валідні прогони, у яких є хоча б одне хибне спрацювання."""
    out = []
    for r in valid_rows(load(master)):
        n = num(r, "fp_events_clean")
        if n and n > 0:
            out.append(r)
    return sorted(out, key=lambda r: (r["architecture"], r["attack"],
                                      r["run_id"]))


def run_dir(run_id: str):
    hits = glob.glob(os.path.join(FIGDATA, "*", "run_" + run_id))
    return hits[0] if hits else None


def census_row(row: dict) -> dict:
    d = run_dir(row["run_id"])
    events = D.load_events(d)
    is_clean = str(row["attack"]).lower() in ("", "none")
    t0 = None if is_clean else D._attack_ts(events)

    def in_window(e) -> bool:
        if is_clean:
            return True
        return t0 is not None and float(e["timestamp"]) < t0

    sec = [e for e in events
           if e.get("event_type") == "security" and in_window(e)]
    counts = {}
    for t in WINDOW_TYPES[1:]:
        counts[t] = len([e for e in events
                         if e.get("event_type") == t and in_window(e)])

    accused = sorted({str(e.get("target_uav")) for e in sec})
    monitors = sorted({str(e.get("source")) for e in sec})
    det = collections.Counter(str(e.get("detector")) for e in sec)
    span = 0.0
    if len(sec) > 1:
        ts = [float(e["timestamp"]) for e in sec]
        span = max(ts) - min(ts)

    return {
        "run_id": row["run_id"],
        "architecture": row["architecture"],
        "attack": row["attack"],
        "exposure": "clean_flight" if is_clean else "pre_attack",
        "target_uav": row["target_uav"],
        "fp_events": len(sec),
        "accused_uavs": len(accused),
        "reporting_monitors": len(monitors),
        "isolation_events": counts["isolation_announce"],
        "recovery_requests": counts["recovery_request"],
        "recovery_acks": counts["recovery_ack"],
        "cascade_span_s": round(span, 2),
        "detectors": " ".join("%s:%d" % kv for kv in sorted(det.items())),
        "accused_list": "|".join(accused),
        "monitor_list": "|".join(monitors),
        "mission_degradation_m": row.get("mission_degradation_m", ""),
        "phase_excess_m": row.get("phase_excess_m", ""),
        "residual_mission_func": row.get("residual_mission_func", ""),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--master", default=MASTER)
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    runs = fp_runs(args.master)
    missing = [r["run_id"] for r in runs if run_dir(r["run_id"]) is None]
    if missing:
        # Часткову вибірку не рахуємо: саме так і зʼявились три різні
        # формулювання механізму на двох, а потім на чотирьох прогонах.
        print("НЕ ВИСТАЧАЄ %d прогонів із %d. Довезти з VM:\n"
              % (len(missing), len(runs)), file=sys.stderr)
        print('cd ~/csma_poc_v2\nRUNS="%s"' % " ".join(missing),
              file=sys.stderr)
        print("""for r in $RUNS; do
  d=$(find runs_campaign -maxdepth 2 -type d -name "run_$r")
  [ -n "$d" ] && tar czf - $d/merged.jsonl $d/run_summary.json \\
    | tar xzf - -C figdata || echo "НЕ ЗНАЙДЕНО $r"
done
git add -f figdata && git commit -m "data: all FP runs for the census" \\
  && git push""", file=sys.stderr)
        raise SystemExit(1)

    rows = [census_row(r) for r in runs]

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        print("wrote %s (%d рядків)" % (args.csv, len(rows)))

    head = ("%-46s %-3s %-14s %-5s %-4s %-4s %-4s %-4s %-4s %-7s %s"
            % ("run_id", "арх", "експозиція", "подій", "обв.", "мон.",
               "iso", "req", "ack", "розтяг", "детектори"))
    print(head)
    print("-" * len(head))
    for r in rows:
        print("%-46s %-3s %-14s %-5d %-4d %-4d %-4d %-4d %-4d %-7.2f %s"
              % (r["run_id"], r["architecture"], r["exposure"],
                 r["fp_events"], r["accused_uavs"], r["reporting_monitors"],
                 r["isolation_events"], r["recovery_requests"],
                 r["recovery_acks"], r["cascade_span_s"], r["detectors"]))


if __name__ == "__main__":
    main()
