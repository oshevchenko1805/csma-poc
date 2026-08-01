"""
campaign_stats.py — does architecture X differ from architecture Y?

The campaign report gives per-cell Wilson intervals. An interval states
how precisely one cell was measured; it does not test a difference. This
script supplies the tests, over exactly the trials the validity gate
accepted (imported from campaign_report, never re-implemented).

PRE-DECLARED PRIMARY FAMILY
---------------------------
Declared in code, before any p-value was looked at:

    detection rate, C vs A and C vs B, under
        detector_takeout+gps_spoofing
        monitor_takeout+gps_spoofing

Four comparisons. These carry the thesis claim: that mesh-shared
security context provides detection where a compromised local detector
or a collapsed monitoring domain leaves the baselines blind. Holm-
Bonferroni is applied over these four and nothing else.

Every other comparison printed below is EXPLORATORY: reported
uncorrected and labelled as such. Correcting the primary claim for the
existence of secondary curiosity would be the wrong trade — and folding
exploratory tests into the family after seeing them would be worse.

Tests
-----
detection            Fisher exact (two-sided) + Newcombe CI for the
                     difference of proportions. Exact, because cells sit
                     at the boundary (0/28, 30/30) where chi-square and
                     Wald intervals misbehave.
MTTD                 Mann-Whitney U. Rank-based: MTTD is not normal and
                     carries a tail from late consensus.
mission degradation  bootstrap CI for the difference of MEDIANS, seeded.
                     Medians because a single false-positive recovery
                     produces an extreme value that would drag a mean.

Usage
-----
    python campaign_stats.py runs_campaign/std_pass1 \
        runs_campaign/ci_pass{1,2,3} \
        runs_campaign/dt_pass{1,2,3,4,5,6} \
        runs_campaign/mt_pass{1,2,3,4,5,6}

    # optionally fold in the coordination metric
    python campaign_stats.py <roots...> --coord-csv runs_campaign/coordination.csv
"""

from __future__ import annotations

import argparse
import collections
import csv
import os

from campaign_report import collect
from metrics import stats as S

PRIMARY_FAMILY = [
    ("detector_takeout+gps_spoofing", "C", "A"),
    ("detector_takeout+gps_spoofing", "C", "B"),
    ("monitor_takeout+gps_spoofing", "C", "A"),
    ("monitor_takeout+gps_spoofing", "C", "B"),
]
"""Declared before inspection of any result. Do not extend this list
after seeing p-values — that is the definition of a fishing expedition."""


def detection_counts(cells: dict, arch: str, attack: str) -> tuple:
    recs = cells.get((arch, attack), [])
    n = len(recs)
    k = sum(1 for (m, _) in recs if m.detected)
    return k, n


def values(cells: dict, arch: str, attack: str, field: str) -> list:
    recs = cells.get((arch, attack), [])
    if field == "mttd_s":
        return [t for (_, t) in recs if t is not None]
    return [
        getattr(m, field)
        for (m, _) in recs
        if isinstance(getattr(m, field), (int, float))
    ]


def report_detection(cells: dict, attacks: list, archs: list) -> None:
    print("=" * 88)
    print("DETECTION — Fisher exact (two-sided), difference of proportions "
          "with Newcombe 95% CI")
    print("=" * 88)

    primary_p = {}
    for attack, a1, a2 in PRIMARY_FAMILY:
        k1, n1 = detection_counts(cells, a1, attack)
        k2, n2 = detection_counts(cells, a2, attack)
        if n1 and n2:
            primary_p["%s %s-vs-%s" % (attack, a1, a2)] = S.fisher_exact(
                k1, n1 - k1, k2, n2 - k2
            )
    adjusted = S.holm(primary_p) if primary_p else {}

    print("\nPRIMARY (pre-declared, Holm-corrected over %d comparisons):"
          % len(primary_p))
    for attack, a1, a2 in PRIMARY_FAMILY:
        key = "%s %s-vs-%s" % (attack, a1, a2)
        if key not in primary_p:
            print("  %-46s —  (cell empty)" % key)
            continue
        k1, n1 = detection_counts(cells, a1, attack)
        k2, n2 = detection_counts(cells, a2, attack)
        lo, hi = S.newcombe_diff_ci(k1, n1, k2, n2)
        p, padj = primary_p[key], adjusted[key]
        print("  %-46s %d/%d vs %d/%d   diff=%+.2f [%+.2f, %+.2f]  "
              "p=%.2e  p_adj=%.2e %s"
              % (key, k1, n1, k2, n2, k1 / n1 - k2 / n2, lo, hi, p, padj,
                 S.stars(padj)))

    print("\nEXPLORATORY (uncorrected — do not read as confirmatory):")
    for attack in attacks:
        for a1, a2 in (("C", "A"), ("C", "B"), ("B", "A")):
            if (attack, a1, a2) in PRIMARY_FAMILY:
                continue
            k1, n1 = detection_counts(cells, a1, attack)
            k2, n2 = detection_counts(cells, a2, attack)
            if not n1 or not n2:
                continue
            p = S.fisher_exact(k1, n1 - k1, k2, n2 - k2)
            lo, hi = S.newcombe_diff_ci(k1, n1, k2, n2)
            print("  %-32s %s-vs-%s  %2d/%-2d vs %2d/%-2d  diff=%+.2f "
                  "[%+.2f, %+.2f]  p=%.3f %s"
                  % (attack[:32], a1, a2, k1, n1, k2, n2,
                     k1 / n1 - k2 / n2, lo, hi, p, S.stars(p)))


def report_continuous(cells: dict, attacks: list, field: str, title: str,
                      test: str) -> None:
    print("\n" + "=" * 88)
    print("%s — %s  (EXPLORATORY, uncorrected)" % (title, test))
    print("=" * 88)
    for attack in attacks:
        for a1, a2 in (("C", "A"), ("C", "B")):
            x = values(cells, a1, attack, field)
            y = values(cells, a2, attack, field)
            if len(x) < 2 or len(y) < 2:
                continue
            line = "  %-32s %s-vs-%s  n=%d/%d  " % (attack[:32], a1, a2,
                                                    len(x), len(y))
            if test == "mannwhitney":
                res = S.mann_whitney_u(x, y)
                if res is None:
                    continue
                _u, p = res
                line += "p=%.4f %s" % (p, S.stars(p))
            else:
                res = S.bootstrap_diff_median(x, y)
                if res is None:
                    continue
                obs, lo, hi = res
                excludes = "excludes 0" if (lo > 0 or hi < 0) else "includes 0"
                line += "median diff=%+.2f [%+.2f, %+.2f]  %s" % (
                    obs, lo, hi, excludes)
            print(line)


def report_coordination(path: str) -> None:
    if not os.path.exists(path):
        print("\n(coordination CSV not found: %s)" % path)
        return
    rows = list(csv.DictReader(open(path)))
    buckets = collections.defaultdict(list)
    for r in rows:
        for field in ("phase_excess_m", "geometry_excess_m"):
            v = r.get(field, "")
            if v not in ("", "None"):
                buckets[(r["attack"], r["architecture"], field)].append(float(v))
    attacks = sorted({r["attack"] for r in rows})

    print("\n" + "=" * 88)
    print("COORDINATION — bootstrap CI for the difference of medians "
          "(EXPLORATORY)")
    print("=" * 88)
    for field, label in (("phase_excess_m", "phase divergence"),
                         ("geometry_excess_m", "geometry deviation")):
        print("\n%s:" % label)
        for attack in attacks:
            for a1, a2 in (("C", "A"), ("C", "B")):
                x = buckets.get((attack, a1, field), [])
                y = buckets.get((attack, a2, field), [])
                if len(x) < 2 or len(y) < 2:
                    continue
                res = S.bootstrap_diff_median(x, y)
                if res is None:
                    continue
                obs, lo, hi = res
                excludes = "excludes 0" if (lo > 0 or hi < 0) else "includes 0"
                print("  %-32s %s-vs-%s  median diff=%+8.1f m [%+.1f, %+.1f]  %s"
                      % (attack[:32], a1, a2, obs, lo, hi, excludes))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--coord-csv", default=None)
    args = ap.parse_args()

    cells = collect(args.roots)["cells"]
    archs = sorted({a for (a, _) in cells})
    attacks = sorted({t for (_, t) in cells})

    report_detection(cells, attacks, archs)
    report_continuous(cells, attacks, "mttd_s", "MTTD", "mannwhitney")
    report_continuous(cells, attacks, "mission_degradation_m",
                      "MISSION DEGRADATION", "bootstrap")
    if args.coord_csv:
        report_coordination(args.coord_csv)

    print("\nPrimary family was fixed in source before any p-value was read;")
    print("exploratory rows are labelled and uncorrected by design.")


if __name__ == "__main__":
    main()
