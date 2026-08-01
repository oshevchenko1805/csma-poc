"""
metrics/sustain.py — sensitivity of detection to the detector's sustain
rule, re-evaluated offline from recorded residual series.

Closes OPEN-3
-------------
R9 predicted a mechanism for undetected spoofs: the signature is present
but intermittent, so `sustained_samples` consecutive breaches never
accumulate and the detector stays silent. It could not be tested — the
only known non-detection predated the instrumentation.

`run_A_gps_spoofing_r1_1785561888` is that case, instrumented: the spoof
landed (belief peak 50.29 m), the residual reached the 2.0 ceiling, the
first crossing came at +0.81 s — the same instant as in every detected
run — but only 2 samples breached and they were NOT adjacent, so the
longest run was 1 against a requirement of 3. Prediction confirmed.

Why this module rather than a note
----------------------------------
Every run stores the full `pos_horiz_ratio` series, so the sustain rule
can be replayed at other settings WITHOUT re-flying anything: detection
on attack runs and false positives on clean baseline runs, as a function
of k. That turns "was 3 the right choice?" — unanswerable, and the sort
of question a reviewer enjoys asking — into a measured operating curve
on which the shipped value is a located point.

Scenario filter (do not remove)
-------------------------------
Only runs of ONE named scenario are swept, `gps_spoofing` by default,
and the count of skipped runs is reported. Two ways to get this wrong,
both of which silently inflate the denominator and understate detection:

  * pointing at a mixed batch root (std_pass1 holds comm / injection /
    baseline runs too — they have no GPS residual excursion and would be
    scored as misses);
  * including `detector_takeout+gps_spoofing`, where the local detector
    is deliberately silenced, so "would the sustain rule have fired" is
    not the question being asked.

Two windows, both reported
--------------------------
post   only samples at or after the injection instant. The right window
       for attributing a detection to the attack.
full   the whole series, which is what the LIVE detector sees: it is
       causal and knows nothing about injection time, so a breach run
       that started before the attack still counts toward its rule.

They differ by about one run in this corpus. Reporting one silently
would misstate either the detector or the metric, so both are printed
and the text must say which it quotes.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from typing import Optional

DEFAULT_THRESHOLD = 1.0
SHIPPED_SUSTAINED_SAMPLES = 3
DEFAULT_KS = (1, 2, 3, 4, 5, 6)

ATTACK_NAME = "gps_spoofing"
"""Exact `attack_name` to sweep. Exact, not substring: substring would
pull in detector_takeout+gps_spoofing, where the local detector is
disabled by design."""


# --- pure functions ----------------------------------------------------


def max_consecutive_above(values: list, threshold: float = DEFAULT_THRESHOLD) -> int:
    """Longest run of consecutive samples strictly above `threshold`."""
    best = current = 0
    for v in values:
        if isinstance(v, (int, float)) and v > threshold:
            current += 1
            if current > best:
                best = current
        else:
            current = 0
    return best


def would_detect(values: list, k: int, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """Would a sustain rule of k consecutive breaches have fired?"""
    return max_consecutive_above(values, threshold) >= k


def series_pairs(node: dict) -> list:
    """(t_rel_sec, pos_horiz_ratio) pairs from a stored estimator series."""
    times = node.get("t_rel_sec") or []
    ratios = node.get("pos_horiz_ratio") or []
    return [
        (t, r)
        for t, r in zip(times, ratios)
        if isinstance(t, (int, float)) and isinstance(r, (int, float))
    ]


def window_values(node: dict, window: str = "post") -> list:
    """Ratio values within the chosen window ('post' or 'full')."""
    pairs = series_pairs(node)
    if window == "full":
        return [r for (_t, r) in pairs]
    return [r for (t, r) in pairs if t >= 0.0]


def is_scenario(summary: dict, attack_name: str = ATTACK_NAME) -> bool:
    """Exact scenario match — see the module docstring on why exact."""
    return str(summary.get("attack_name") or "") == attack_name


# --- corpus sweep ------------------------------------------------------


def _summary(run_dir: str) -> Optional[dict]:
    path = os.path.join(run_dir, "run_summary.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def sweep(attack_roots: list, baseline_roots: list, ks=DEFAULT_KS,
          threshold: float = DEFAULT_THRESHOLD, window: str = "post",
          attack_name: str = ATTACK_NAME) -> dict:
    """
    Detection on runs of ONE scenario (target UAV) and false positives on
    clean baseline runs (ANY UAV — a security event on a healthy fleet is
    a false positive wherever it fires), as a function of k.
    """
    detected = {k: 0 for k in ks}
    fp_runs = {k: 0 for k in ks}
    attacks = 0
    baselines = 0
    skipped_scenario = 0
    skipped_no_series = 0

    for root in attack_roots:
        for run_dir in sorted(glob.glob(os.path.join(root, "run_*"))):
            summary = _summary(run_dir)
            if summary is None or summary.get("error"):
                continue
            if not is_scenario(summary, attack_name):
                skipped_scenario += 1
                continue
            uavs = (summary.get("estimator_series") or {}).get("uavs") or {}
            node = uavs.get(summary.get("target_uav") or "uav_0") or {}
            vals = window_values(node, window)
            if not vals:
                skipped_no_series += 1
                continue
            attacks += 1
            longest = max_consecutive_above(vals, threshold)
            for k in ks:
                if longest >= k:
                    detected[k] += 1

    for root in baseline_roots:
        for run_dir in sorted(glob.glob(os.path.join(root, "run_*"))):
            summary = _summary(run_dir)
            if summary is None or summary.get("error"):
                continue
            uavs = (summary.get("estimator_series") or {}).get("uavs") or {}
            if not uavs:
                continue
            baselines += 1
            longest = max(
                max_consecutive_above(window_values(n, "full"), threshold)
                for n in uavs.values()
            )
            for k in ks:
                if longest >= k:
                    fp_runs[k] += 1

    return {
        "ks": list(ks),
        "window": window,
        "threshold": threshold,
        "attack_name": attack_name,
        "attack_runs": attacks,
        "detected": detected,
        "baseline_runs": baselines,
        "fp_runs": fp_runs,
        "skipped_other_scenario": skipped_scenario,
        "skipped_no_series": skipped_no_series,
    }


def print_sweep(result: dict) -> None:
    ks = result["ks"]
    na, nb = result["attack_runs"], result["baseline_runs"]
    print("scenario=%s  window=%s  threshold=%.1f"
          % (result["attack_name"], result["window"], result["threshold"]))
    print("attack runs=%d  clean runs=%d  (skipped: %d other scenario, "
          "%d without series)"
          % (na, nb, result["skipped_other_scenario"],
             result["skipped_no_series"]))
    print("%3s %20s %20s" % ("k", "detection", "runs with FP"))
    for k in ks:
        d = result["detected"][k]
        f = result["fp_runs"][k]
        dr = "%d/%d = %.2f" % (d, na, d / na) if na else "—"
        fr = "%d/%d = %.2f" % (f, nb, f / nb) if nb else "—"
        mark = "   <-- shipped" if k == SHIPPED_SUSTAINED_SAMPLES else ""
        print("%3d %20s %20s%s" % (k, dr, fr, mark))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--attack-roots", nargs="+", required=True)
    ap.add_argument("--baseline-roots", nargs="+", required=True)
    ap.add_argument("--attack-name", default=ATTACK_NAME)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = ap.parse_args()

    for window in ("post", "full"):
        print("=" * 70)
        print_sweep(sweep(args.attack_roots, args.baseline_roots,
                          threshold=args.threshold, window=window,
                          attack_name=args.attack_name))
        print()


if __name__ == "__main__":
    main()
