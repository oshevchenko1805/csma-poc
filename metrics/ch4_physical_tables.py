"""
metrics/ch4_physical_tables.py — tables 4.6–4.8 of Ch. 4 rebuilt on the
physical metrics (review P1), plus the collision sensitivity table for
the appendix. Pure read of committed CSVs; no raw data needed.

Inputs
------
runs_campaign/physical_outcomes.csv   metrics.physical_outcomes (3e57dab)
runs_campaign/campaign_master.csv     recovery success, MTTR, phase and
                                      geometry excess (unchanged metrics)
runs_campaign/collision_flags.csv     metrics.collision_flags (sensitivity
                                      only; main tables use ALL valid runs)
runs_campaign/stage3_h2_rows.json     metrics.h2_analysis rows of the stage-3
                                      H2 campaign (table 4.7, panel B)

What changed against the draft
------------------------------
4.7  (was 4.6 in the draft) Panel A (thesis-campaign-v1, A/B/C). Recovery Success / MTTR / Stabilisation Level for GPS cells measured
     "growth of route distance stopped", which for A/B is the 50 m spoof
     ceiling. Replaced by navigation integrity (estimate jump, nav error)
     and what the response physically held (drift after response).
     Panel B (stage 3, C only): current vs improved recovery rule vs
     detection only; verdict numbers via metrics.h2_analysis.verdict, so
     the table cannot drift from the pre-registered decision rule.
4.6  (was 4.7 in the draft) Mission Degradation (distance to the route LINE) replaced by mission
     execution (corners reached vs clean flight). Route distance is kept
     only where the estimate is not attacked (command injection, comm
     disruption) — there it is a physical displacement.
Table numbers 4.6/4.7 were swapped against the draft so that numbering
follows first mention in the rewritten Ch. 4 text (thesis_text/CH4_V2_TEXT.md).
4.8  Phase/Geometry Excess unchanged (truth-based); the Mission
     Degradation column is replaced by drift after response and mission
     execution.

Quartiles: metrics.plots.quartiles (same as the draft tables).

Usage
-----
    python3 -m metrics.ch4_physical_tables [--out thesis_text/CH4_PHYSICAL_TABLES.md]
"""

from __future__ import annotations

import argparse
import collections
import json
import os

from metrics.plots import flag, load, num, quartiles, valid_rows
from metrics.stats import fisher_exact, wilson_bounds

PHYS = "runs_campaign/physical_outcomes.csv"
MASTER = "runs_campaign/campaign_master.csv"
FLAGS = "runs_campaign/collision_flags.csv"
H2_ROWS = "runs_campaign/stage3_h2_rows.json"

ARCHS = ("A", "B", "C")
GPS_CELLS = ("gps_spoofing", "monitor_takeout+gps_spoofing",
             "detector_takeout+gps_spoofing")
ALL_CELLS = ("gps_spoofing", "monitor_takeout+gps_spoofing",
             "detector_takeout+gps_spoofing", "command_injection",
             "comm_disruption", "none")
UA = {
    "gps_spoofing": "GPS spoofing",
    "monitor_takeout+gps_spoofing": "Monitor takeout + GPS spoofing",
    "detector_takeout+gps_spoofing": "Detector takeout + GPS spoofing",
    "command_injection": "Command injection",
    "comm_disruption": "Comm disruption",
    "none": "Без атаки",
}
ACTION_UA = {"mode_loiter": "LOITER", "filter_commands": "фільтрація команд",
             "hold_zero_velocity": "утримання нульової швидкості"}
FULL_EXEC = 0.999


def fmt_q(values: list, nd: int = 2, with_n: bool = True) -> str:
    q = quartiles([v for v in values if v is not None])
    if q is None:
        return "н/д"
    med, q1, q3, n = q
    s = "%.*f [%.*f; %.*f]" % (nd, med, nd, q1, nd, q3)
    return s + ("; n=%d" % n if with_n else "")


def fmt_med(values: list, nd: int = 2) -> str:
    q = quartiles([v for v in values if v is not None])
    return "н/д" if q is None else "%.*f" % (nd, q[0])


def cells(rows: list) -> dict:
    g = collections.defaultdict(list)
    for r in rows:
        g[(r["attack"], r["architecture"])].append(r)
    return g


def col(rows: list, key: str) -> list:
    return [num(r, key) for r in rows]


# ---------------------------------------------------------------- 4.7 (GPS: navigation integrity)

def table_nav_integrity(phys: dict, h2_rows: list = None) -> list:
    out = [
        "**Таблиця 4.7. Навігаційна цілісність і фізичний результат реагування за GPS-пов'язаних атак**",
        "",
        "**Панель A. Основна кампанія: архітектури A, B, C**",
        "",
        "| Сценарій | Арх. | n | Стрибок оцінки позиції, с | Помилка навігації наприкінці вікна, м | Перша дія реагування, с | Знос після реагування, м | Виконання місії |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for a in GPS_CELLS:
        for arch in ARCHS:
            rs = phys.get((a, arch), [])
            acts = collections.Counter(r["first_response_action"] for r in rs
                                       if r["first_response_action"])
            if acts:
                act, k = acts.most_common(1)[0]
                resp = "%s, %s (%d/%d)" % (
                    ACTION_UA.get(act, act),
                    fmt_med(col(rs, "t_first_response_s")), k, len(rs))
            else:
                resp = "немає (реагування вимкнене)"
            out.append("| %s | %s | %d | %s | %s | %s | %s | %s |" % (
                UA[a], arch, len(rs),
                fmt_q(col(rs, "t_estimate_jump_s"), with_n=False),
                fmt_med(col(rs, "nav_error_end_m")),
                resp,
                fmt_q(col(rs, "post_response_drift_m"), with_n=False)
                if acts else "—",
                fmt_med(col(rs, "mission_execution"))))
    notes = ("Примітки. Стрибок оцінки — перший момент після початку атаки, коли |оцінка − істина| > 25 м. "
             "Помилка навігації — медіана |оцінка − істина| за останні 10 с вікна 60 с. "
             "Знос після реагування — найбільша відстань (істина Gazebo) від точки, де апарат був у момент підтвердження дії утримання. "
             "Виконання місії — частка кутових точок маршруту, пройдених у вікні, відносно польоту без атаки тієї ж архітектури. "
             "н/д: оцінку позиції не записано (монітор вимкнено атакою).")
    if h2_rows:
        out += [""] + table_h2_panel(h2_rows)
        notes += (" Панель B: окрема кампанія, лише архітектура C, апарати на різних висотах (крок 5 м); "
                  "з панеллю A її пов'язує плече «чинне правило», яке відтворює C основної кампанії. "
                  "Кутові точки — кількість кутів маршруту, пройдених у вікні 60 с (у польоті без атаки — близько 7). "
                  "Перевірка H2 — за правилом, зафіксованим до першого прогону: однобічний критерій Манна–Вітні "
                  "з поправкою Holm на дві підтверджувальні комірки та медіана зносу ≤ 7.91 м; "
                  "комірка detector takeout — описова (різниця медіан, bootstrap 95% ДІ).")
    out += ["", notes, ""]
    return out


RULE_UA = {"proportionate": "чинне (LOITER)",
           "trust_aware": "удосконалене (нульова швидкість)",
           "detect_only": "лише виявлення"}


def _sci(p: float) -> str:
    m, e = ("%.1e" % p).split("e")
    sup = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
    return "%s·10%s" % (m, str(int(e)).translate(sup))


def table_h2_panel(h2_rows: list) -> list:
    from metrics.h2_analysis import ARMS, BOUND_M, CONFIRMATORY_CELLS, verdict
    v = verdict(h2_rows)
    inc = [r for r in h2_rows if r["included"]]
    out = [
        "**Панель B. Перевірочна кампанія H2: архітектура C, чинне й удосконалене правило відновлення**",
        "",
        "| Сценарій | Правило відновлення | n | Стрибок оцінки позиції, с | Помилка навігації наприкінці вікна, м | Дія, с (підтверджено) | Знос після реагування, м | Кутові точки у вікні | Перевірка H2 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for a in GPS_CELLS:
        info = v["cells"].get(a, {})
        for arm in ARMS:
            rs = [r for r in inc if r["attack"] == a and r["policy"] == arm]
            if arm == "detect_only":
                act, drift = "немає", "—"
            else:
                ok = [r for r in rs if r.get("action_ok")]
                act = "%s (%d/%d)" % (fmt_med([r.get("t_action_s") for r in ok]),
                                      len(ok), len(rs))
                drift = fmt_q([r.get("drift_itt_m") for r in rs], with_n=False)
            check = "—"
            if arm == "trust_aware":
                if a in CONFIRMATORY_CELLS:
                    check = "p(Holm) = %s; медіана ≤ %.2f м: %s → %s" % (
                        _sci(info["p_holm"]), BOUND_M,
                        "так" if info["median_trust_m"] <= BOUND_M else "ні",
                        "прийнято" if info["accepted"] else "не прийнято")
                else:
                    d, lo, hi = info["diff_median_ci"]
                    check = ("описово: Δ медіан %.1f [%.1f; %.1f] м" % (d, lo, hi)).replace("-", "−")
            out.append("| %s | %s | %d | %s | %s | %s | %s | %s | %s |" % (
                UA[a], RULE_UA[arm], len(rs),
                fmt_q([r.get("t_estimate_jump_s") for r in rs], with_n=False),
                fmt_med([r.get("nav_error_end_m") for r in rs]),
                act, drift,
                fmt_med([r.get("waypoints_captured") for r in rs], nd=0),
                check))
    out.append("")
    out.append("Висновок за заздалегідь зафіксованим правилом: H2 %s." % (
        {"CONFIRMED": "підтверджено", "PARTIAL": "підтверджено частково",
         "NOT CONFIRMED": "не підтверджено"}[v["H2"]]))
    return out


# ---------------------------------------------------------------- 4.6 (mission execution)

def table_mission(phys: dict, master: dict) -> list:
    out = [
        "**Таблиця 4.6. Виконання місії за типом атаки й архітектурою**",
        "",
        "**Панель A. Виконання місії, медіана [IQR]; повне виконання, k/n**",
        "",
        "| Сценарій | A | B | C |",
        "| --- | --- | --- | --- |",
    ]
    for a in ALL_CELLS:
        cells_txt = []
        for arch in ARCHS:
            rs = phys.get((a, arch), [])
            ex = col(rs, "mission_execution")
            k = sum(1 for v in ex if v is not None and v >= FULL_EXEC)
            n = sum(1 for v in ex if v is not None)
            cells_txt.append("%s; %d/%d" % (fmt_q(ex, with_n=False), k, n))
        out.append("| %s | %s |" % (UA[a], " | ".join(cells_txt)))

    # Fisher: full execution C vs A / C vs B, command injection
    def kn(a, arch):
        ex = [v for v in col(phys.get((a, arch), []), "mission_execution") if v is not None]
        return sum(1 for v in ex if v >= FULL_EXEC), len(ex)
    kc, nc = kn("command_injection", "C")
    fis = []
    for other in ("A", "B"):
        ko, no = kn("command_injection", other)
        fis.append("C−%s: p = %s" % (other, _sci(fisher_exact(kc, nc - kc, ko, no - ko))))

    out += ["",
            "**Панель B. Command injection: відновлення і фізичне відхилення від маршруту**",
            "",
            "| Арх. | Recovery Success | Wilson 95% CI | MTTR, с | Відстань до маршруту, м |",
            "| --- | --- | --- | --- | --- |"]
    for arch in ARCHS:
        ms = master.get(("command_injection", arch), [])
        st = [flag(r, "degradation_stopped") for r in ms]
        k, n = sum(1 for v in st if v), sum(1 for v in st if v is not None)
        lo, hi = wilson_bounds(k, n)
        out.append("| %s | %d/%d | %.3f–%.3f | %s | %s |" % (
            arch, k, n, lo, hi,
            fmt_q(col(ms, "mttr_functional_s"), nd=3) if k else "не визначено",
            fmt_q(col(phys.get(("command_injection", arch), []), "route_distance_m"), with_n=False)))
    out += ["",
            "Примітки. Повне виконання — виконання місії ≥ 1.00 (стільки ж кутових точок, скільки в польоті без атаки). "
            "Точний тест Фішера для повного виконання за command injection: %s. "
            "Відстань до маршруту наведено лише для command injection, де оцінка стану не атакована і відстань є фізичним відхиленням; "
            "за GPS-атак вона не характеризує фізичне зміщення (див. табл. 4.7)." % "; ".join(fis),
            ""]
    return out


# ---------------------------------------------------------------- 4.8

def table_4_8(phys: dict, master: dict, flags: dict) -> list:
    out = [
        "**Таблиця 4.8. Профілі координації C і контрольний рівень без атаки**",
        "",
        "**Панель A. Спостережувані профілі C**",
        "",
        "| Сценарій | Phase Excess, м | Geometry Excess, м | Знос після реагування, м | Виконання місії |",
        "| --- | --- | --- | --- | --- |",
    ]
    for a in ("command_injection", "detector_takeout+gps_spoofing",
              "monitor_takeout+gps_spoofing", "gps_spoofing"):
        ms = master.get((a, "C"), [])
        ps = phys.get((a, "C"), [])
        drift = col(ps, "post_response_drift_m")
        out.append("| %s | %s | %s | %s | %s |" % (
            UA[a], fmt_q(col(ms, "phase_excess_m"), nd=3, with_n=False),
            fmt_q(col(ms, "geometry_excess_m"), nd=3, with_n=False),
            fmt_med(drift) if any(v is not None for v in drift) else "— (дія не утримує позицію)",
            fmt_med(col(ps, "mission_execution"))))

    clean = [r for arch in ARCHS for r in master.get(("none", arch), [])]
    out += ["",
            "**Панель B. Контрольний рівень без атаки**",
            "",
            "| Метрика | n | Медіана [IQR], м | Хвіст | З них прогони зі зіткненням |",
            "| --- | --- | --- | --- | --- |"]
    for key, thr in (("phase_excess_m", 10.0), ("geometry_excess_m", 30.0)):
        vals = [(num(r, key), r["run_id"]) for r in clean if num(r, key) is not None]
        tail = [rid for v, rid in vals if v > thr]
        coll = sum(1 for rid in tail if flags.get(rid))
        out.append("| %s | %d | %s | >%.0f м: %d/%d | %d/%d |" % (
            "Phase Excess" if key.startswith("phase") else "Geometry Excess",
            len(vals), fmt_q([v for v, _ in vals], nd=3, with_n=False),
            thr, len(tail), len(vals), coll, len(tail)))
    out += ["",
            "Примітки. Phase Excess і Geometry Excess обчислено за істинними положеннями Gazebo і не залежать від атакованої оцінки. "
            "Хвости розподілів у польотах без атаки зіставлено з прогонами, де сталося зіткнення апаратів (див. табл. Д.1).",
            ""]
    return out


# ---------------------------------------------------------------- appendix

def table_sensitivity(phys: dict, flags: dict) -> list:
    out = [
        "**Таблиця Д.1. Стійкість ключових фізичних результатів до вилучення прогонів зі зіткненнями**",
        "",
        "| Сценарій | Арх. | n (усі / без зіткнень) | Помилка навігації, м | Знос після реагування, м | Виконання місії |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for a in ALL_CELLS:
        for arch in ARCHS:
            rs = phys.get((a, arch), [])
            cl = [r for r in rs if not flags.get(r["run_id"])]

            def pair(key):
                x, y = fmt_med(col(rs, key)), fmt_med(col(cl, key))
                return "—" if x == y == "н/д" else "%s / %s" % (x, y)
            out.append("| %s | %s | %d / %d | %s | %s | %s |" % (
                UA[a], arch, len(rs), len(cl), pair("nav_error_end_m"),
                pair("post_response_drift_m"), pair("mission_execution")))
    n_all = sum(len(v) for v in phys.values())
    n_flag = sum(1 for v in phys.values() for r in v if flags.get(r["run_id"]))
    out += ["",
            "Примітка. Зіткнення — падіння будь-якого UAV з висоти > 15 м нижче 5 м за ≤ 5 с після контакту з іншим UAV (< 1 м), "
            "у будь-який момент прогону (metrics/collision_flags.py). Позначено %d із %d валідних прогонів. "
            "Основні таблиці 4.6–4.8 побудовано на всій валідній вибірці; ця таблиця лише перевіряє стійкість." % (n_flag, n_all),
            ""]
    return out


def build(phys_csv: str = PHYS, master_csv: str = MASTER, flags_csv: str = FLAGS,
          h2_json: str = H2_ROWS) -> str:
    phys = cells(load(phys_csv))
    h2_rows = None
    if h2_json and os.path.exists(h2_json):
        with open(h2_json) as fh:
            h2_rows = json.load(fh)
    master = cells(valid_rows(load(master_csv)))
    flags = {r["run_id"]: flag(r, "collision_fall") for r in load(flags_csv)}
    lines = ["# Розділ 4 — таблиці на фізичних метриках (P1)",
             "",
             "Згенеровано `python3 -m metrics.ch4_physical_tables`. Не редагувати вручну.",
             ""]
    # numbering follows first mention in the text: 4.6 mission, 4.7 GPS, 4.8 coordination
    lines += table_mission(phys, master) + table_nav_integrity(phys, h2_rows) + table_4_8(phys, master, flags)
    lines += table_sensitivity(phys, flags)
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="thesis_text/CH4_PHYSICAL_TABLES.md")
    a = ap.parse_args(argv)
    md = build()
    with open(a.out, "w") as fh:
        fh.write(md)
    print("wrote %s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
