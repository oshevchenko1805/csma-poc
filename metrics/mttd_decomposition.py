"""
metrics/mttd_decomposition.py — what the MTTD of the main campaign is made
of (review P15; thesis Ch. 4, п. 4.2, табл. 4.2).

Why this module
---------------
RESULTS_NOTES R9 decomposed MTTD from ONE raw residual series (N=1), and
FINAL_RESULTS_AUDIT item 11 blocked the result because it could not be
reproduced from the authorised CSVs. It can: campaign_master.csv carries
`ratio_first_cross_s` (first sample of the recorded `pos_horiz_ratio`
series above the detector threshold, t relative to injection) for every
run. This module rebuilds the decomposition from the authorised master
alone, per cell, for every detected run.

Two detection paths, two reference events
-----------------------------------------
local   the target's own GpsSpoofingDetector (gps_spoofing,
        monitor_takeout+gps_spoofing). Sustain rule: k consecutive
        ESTIMATOR_STATUS samples above threshold, ~1 Hz on PX4 SITL, so

            MTTD = t_first + (k - 1) / f  (+ extra samples if the first
                                             breach does not start the
                                             streak that fires)

        Neither term contains the architecture: t_first is set by the
        injection ramp and the estimator, (k - 1)/f by the detector
        parameter and PX4's publishing rate.
cross   detector_takeout+gps_spoofing in C: the local detector is
        silenced and detection comes from cross_check. Its reference
        event is the estimate jump (physical_outcomes.t_estimate_jump_s),
        not the first residual crossing — cross_check compares the
        attacked UAV's ANNOUNCED position, which moves at the jump.

Classification of local-path runs (fixed before looking at the table)
----------------------------------------------------------------------
floor        |delta - FLOOR_S| <= TOL_S
late_streak  delta > FLOOR_S + TOL_S and ratio_n_above > ratio_maxcons_full
             (at least one breach sample lies outside the longest streak,
             i.e. the first crossing did not start the firing streak)
unexplained  anything else — reported, never dropped

Usage
-----
    python3 -m metrics.mttd_decomposition runs_campaign/campaign_master.csv \
        runs_campaign/physical_outcomes.csv --out-md thesis_text/MTTD_DECOMPOSITION.md
"""

from __future__ import annotations

import argparse
import collections

from detectors.gps import GpsSpoofingDetector
from metrics.ch4_physical_tables import fmt_q
from metrics.plots import flag, load, num, quartiles, valid_rows

K = GpsSpoofingDetector.DEFAULT_SUSTAINED_SAMPLES
NOMINAL_RATE_HZ = 1.0          # ESTIMATOR_STATUS on PX4 SITL (detectors/gps.py)
FLOOR_S = (K - 1) / NOMINAL_RATE_HZ
TOL_S = 0.1

LOCAL_CELLS = [
    ("gps_spoofing", "A"), ("gps_spoofing", "B"), ("gps_spoofing", "C"),
    ("monitor_takeout+gps_spoofing", "B"), ("monitor_takeout+gps_spoofing", "C"),
]
CROSS_CELLS = [("detector_takeout+gps_spoofing", "C")]

LABEL = {
    "gps_spoofing": "GPS spoofing",
    "monitor_takeout+gps_spoofing": "Monitor takeout + GPS spoofing",
    "detector_takeout+gps_spoofing": "Detector takeout + GPS spoofing",
}


def classify(delta: float, n_above, maxcons) -> str:
    if abs(delta - FLOOR_S) <= TOL_S:
        return "floor"
    if (delta > FLOOR_S + TOL_S and n_above is not None and maxcons is not None
            and n_above > maxcons):
        return "late_streak"
    return "unexplained"


def local_rows(master: list) -> list:
    """One dict per detected valid run of a local-path cell."""
    cells = set(LOCAL_CELLS)
    out = []
    for r in valid_rows(master):
        key = (r.get("attack"), r.get("architecture"))
        if key not in cells or not flag(r, "detected"):
            continue
        mttd, first = num(r, "mttd_s"), num(r, "ratio_first_cross_s")
        if mttd is None or first is None:
            out.append({"run_id": r["run_id"], "cell": key, "mttd": mttd,
                        "first": first, "delta": None, "class": "no_series"})
            continue
        d = mttd - first
        out.append({"run_id": r["run_id"], "cell": key, "mttd": mttd,
                    "first": first, "delta": d,
                    "class": classify(d, num(r, "ratio_n_above"),
                                      num(r, "ratio_maxcons_full")),
                    "n_above": num(r, "ratio_n_above"),
                    "maxcons": num(r, "ratio_maxcons_full")})
    return out


def cross_rows(master: list, physical: list) -> list:
    """Detected valid runs of the cross_check path, referenced to the jump."""
    jump = {p["run_id"]: num(p, "t_estimate_jump_s") for p in physical}
    cells = set(CROSS_CELLS)
    out = []
    for r in valid_rows(master):
        key = (r.get("attack"), r.get("architecture"))
        if key not in cells or not flag(r, "detected"):
            continue
        mttd, tj = num(r, "mttd_s"), jump.get(r["run_id"])
        out.append({"run_id": r["run_id"], "cell": key, "mttd": mttd,
                    "jump": tj,
                    "delta": None if mttd is None or tj is None else mttd - tj})
    return out


def _mm(vals: list) -> str:
    v = [x for x in vals if x is not None]
    return "н/д" if not v else "%.2f–%.2f" % (min(v), max(v))


def summary(local: list, cross: list) -> dict:
    by = collections.defaultdict(list)
    for x in local:
        by[x["cell"]].append(x)
    pooled = [x["delta"] for x in local if x["class"] == "floor"]
    q = quartiles(pooled)
    return {
        "cells": {c: by.get(c, []) for c in LOCAL_CELLS},
        "cross": cross,
        "n_local": len(local),
        "n_floor": len(pooled),
        "pooled_floor_median": q[0] if q else None,
        "implied_rate_hz": (K - 1) / q[0] if q and q[0] else None,
        "exceptions": [x for x in local if x["class"] != "floor"],
    }


def build_md(s: dict) -> str:
    L = ["# Розкладання MTTD (табл. 4.2) — згенеровано metrics/mttd_decomposition.py",
         "",
         "k = %d, номінальна частота ESTIMATOR_STATUS %.1f Гц → (k − 1)/f = %.2f с; допуск ±%.2f с."
         % (K, NOMINAL_RATE_HZ, FLOOR_S, TOL_S),
         "",
         "| Сценарій | Арх. | Шлях | n | MTTD, с | Опорна подія, с | MTTD − опорна подія, с | Діапазон різниці, с | У межах (k − 1)/f ± допуск |",
         "|---|---|---|---|---|---|---|---|---|"]
    for c, xs in s["cells"].items():
        fl = sum(1 for x in xs if x["class"] == "floor")
        L.append("| %s | %s | локальний детектор | %d | %s | t_перш = %s | %s | %s | %d/%d |" % (
            LABEL[c[0]], c[1], len(xs),
            fmt_q([x["mttd"] for x in xs], 3, False),
            fmt_q([x["first"] for x in xs], 3, False),
            fmt_q([x["delta"] for x in xs], 3, False),
            _mm([x["delta"] for x in xs]), fl, len(xs)))
    by = collections.defaultdict(list)
    for x in s["cross"]:
        by[x["cell"]].append(x)
    for c, xs in by.items():
        L.append("| %s | %s | перехресна перевірка | %d | %s | t_стрибка = %s | %s | %s | — |" % (
            LABEL[c[0]], c[1], len(xs),
            fmt_q([x["mttd"] for x in xs], 3, False),
            fmt_q([x["jump"] for x in xs], 3, False),
            fmt_q([x["delta"] for x in xs], 3, False),
            _mm([x["delta"] for x in xs])))
    L += ["",
          "Медіана [Q1; Q3]. Лише валідні прогони з виявленням.",
          "",
          "Разом локальний шлях: %d прогонів, у межах (k − 1)/f ± допуск — %d; медіана різниці %s с; "
          "відповідна частота (k − 1)/різниця = %s Гц." % (
              s["n_local"], s["n_floor"],
              "н/д" if s["pooled_floor_median"] is None else "%.3f" % s["pooled_floor_median"],
              "н/д" if s["implied_rate_hz"] is None else "%.3f" % s["implied_rate_hz"]),
          "",
          "Винятки (не floor):"]
    if not s["exceptions"]:
        L.append("- немає")
    for x in s["exceptions"]:
        L.append("- %s: %s, MTTD %.3f с, t_перш %s с, різниця %s с, перевищень %s, найдовша серія %s" % (
            x["run_id"], x["class"], x["mttd"] if x["mttd"] is not None else float("nan"),
            x["first"], "н/д" if x["delta"] is None else "%.3f" % x["delta"],
            x.get("n_above"), x.get("maxcons")))
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("master")
    ap.add_argument("physical")
    ap.add_argument("--out-md", default=None)
    a = ap.parse_args(argv)
    master, phys = load(a.master), load(a.physical)
    md = build_md(summary(local_rows(master), cross_rows(master, phys)))
    if a.out_md:
        with open(a.out_md, "w") as fh:
            fh.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
