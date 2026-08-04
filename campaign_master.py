"""
campaign_master.py — one row per run, every metric, one file.

Results otherwise live in four places (campaign.csv, coordination.csv,
extras.json, and the innards of run_summary.json). Nothing joins them, so
any figure or table has to re-derive its own view and can silently
disagree with the others. This builds the single artefact that the
figures, the tables and a replicating reader all read from.

Includes EVERY run in the given roots — valid, gated out, and errored —
with the reason recorded. A file that silently contains only the runs
that worked cannot be used to reconstruct the exclusion flow, which is
precisely what Chapter 4 has to state.

The validity gate is not re-implemented: `campaign_report.collect` is run
once and its accepted run_ids are read back. One definition of "valid" in
the codebase, by construction.

Two columns exist because deriving them later got them wrong once:
  * per-detector false-positive counts (`fp_gps`, `fp_heartbeat`,
    `fp_cross_check`) — a run can carry events from several detectors and
    splitting a total across a name list is an estimate, not a count;
  * `ratio_maxcons_*_fleet` — a false positive on a healthy swarm can
    fire on ANY vehicle, so the target-only series understates it.

Usage
-----
    python campaign_master.py runs_campaign/std_pass1 ... \
        --csv runs_campaign/campaign_master.csv
"""

from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import os
from typing import Optional

import metrics.derived as D
from campaign_report import collect, is_gps_family, belief_peak, mttd
from metrics.coordination import analyse_run_dir as coordination_of
from metrics.sustain import max_consecutive_above, window_values

POST_FIX_EPOCH = 1785265956
"""Commit e2d2d3b (real sysid guard + mission-restore recovery), the last
change that altered measured behaviour. Runs older than this are from a
different system and must never be pooled with the campaign; the flag
makes that checkable in the data rather than trusted to the operator."""

DETECTORS = ["gps", "heartbeat", "cross_check"]

COLUMNS = [
    # provenance
    "run_id", "group", "architecture", "attack", "target_uav",
    "run_epoch", "post_fix", "duration_sec",
    # validity
    "errored", "valid", "exclusion_reason",
    # detection / response (Table 3.13)
    "detected", "mttd_s", "containment_success", "time_to_isolation_s",
    "mttr_functional_s", "degradation_stopped", "total_response_time_s",
    # mission resilience
    "mission_degradation_m", "stabilisation_level_m",
    "residual_mission_func", "baseline_track_error_m",
    # coordination integrity — new metric, then the superseded one
    "phase_excess_m", "phase_peak_m", "phase_baseline_m",
    "geometry_excess_m", "geometry_peak_m", "geometry_baseline_m",
    "legacy_coordination_loss", "legacy_coordination_restored",
    # attack landing / detector signal
    "belief_peak_horiz_m", "ratio_peak", "ratio_n_above",
    "ratio_maxcons_post", "ratio_maxcons_full",
    "ratio_maxcons_post_fleet", "ratio_maxcons_full_fleet",
    "ratio_first_cross_s",
    # architectural cost
    "mesh_pub_msgs", "mesh_pub_bytes", "mesh_del_msgs", "mesh_drop_msgs",
    # false positives during clean operation
    "fp_events_clean", "fp_detectors",
    "fp_gps", "fp_heartbeat", "fp_cross_check",
]


def _summary(run_dir: str) -> Optional[dict]:
    path = os.path.join(run_dir, "run_summary.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def _epoch(run_id: str) -> Optional[int]:
    tail = str(run_id).rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else None


def clean_window_events(run_dir: str, summary: dict) -> tuple:
    """(count, 'a|b', {detector: count}) for security events during clean
    operation: the pre-injection window on an attack run, the WHOLE flight
    on a baseline run. A baseline run carries an attack marker at the
    nominal instant although nothing is injected; using it as a boundary
    discards most of the run and hides any false positive in the second
    half — measured case: B_none_r4, a false gps detection that triggered
    an isolation and cost 190 m of phase divergence on a healthy fleet."""
    events = D.load_events(run_dir)
    is_baseline = str(summary.get("attack_name") or "none").lower() in ("", "none")
    boundary = None if is_baseline else D._attack_ts(events)
    clean = [
        e for e in events
        if e.get("event_type") == "security"
        and (boundary is None or float(e["timestamp"]) < boundary)
    ]
    by_detector = collections.Counter(
        str(e.get("detector") or "?") for e in clean
    )
    return len(clean), "|".join(sorted(by_detector)), by_detector


def _mesh(summary: dict) -> dict:
    fleet = (summary.get("mesh_cost") or {}).get("fleet_total") or {}

    def tot(side: str, key: str):
        return ((fleet.get(side) or {}).get("total") or {}).get(key)

    return {
        "mesh_pub_msgs": tot("published", "msgs"),
        "mesh_pub_bytes": tot("published", "bytes"),
        "mesh_del_msgs": tot("delivered", "msgs"),
        "mesh_drop_msgs": tot("dropped", "msgs"),
    }


def _fleet_maxcons(est_uavs: dict, window: str) -> Optional[int]:
    """Longest breach run across ALL vehicles — the right quantity for a
    false positive, which need not occur on the attack target."""
    if not est_uavs:
        return None
    return max(
        max_consecutive_above(window_values(node, window))
        for node in est_uavs.values()
    )


def build(roots: list) -> list:
    valid_ids = {
        m.run_id for recs in collect(roots)["cells"].values() for (m, _t) in recs
    }

    rows = []
    for root in roots:
        group = os.path.basename(os.path.normpath(root))
        for run_dir in sorted(glob.glob(os.path.join(root, "run_*"))):
            summary = _summary(run_dir)
            if summary is None:
                continue
            run_id = str(summary.get("run_id") or os.path.basename(run_dir))
            attack = str(summary.get("attack_name") or "?")
            errored = bool(summary.get("error"))
            m = None if errored else D.analyse_run(run_dir)
            cm = None if errored else coordination_of(run_dir)

            valid = run_id in valid_ids
            if errored:
                reason = "errored"
            elif valid:
                reason = ""
            elif m is None:
                reason = "no_metrics"
            elif is_gps_family(attack):
                reason = "attack_did_not_land"
            else:
                reason = "excluded"

            target = summary.get("target_uav") or "uav_0"
            est_uavs = (summary.get("estimator_series") or {}).get("uavs") or {}
            node = est_uavs.get(target) or {}
            epoch = _epoch(run_id)
            fp_n, fp_names, fp_by = clean_window_events(run_dir, summary)

            row = {c: "" for c in COLUMNS}
            row.update({
                "run_id": run_id,
                "group": group,
                "architecture": summary.get("architecture"),
                "attack": attack,
                "target_uav": target,
                "run_epoch": epoch,
                "post_fix": (epoch >= POST_FIX_EPOCH) if epoch else "",
                "duration_sec": summary.get("duration_sec"),
                "errored": errored,
                "valid": valid,
                "exclusion_reason": reason,
                "belief_peak_horiz_m": belief_peak(summary),
                "ratio_peak": node.get("peak"),
                "ratio_n_above": node.get("n_above_threshold"),
                "ratio_maxcons_post": (max_consecutive_above(
                    window_values(node, "post")) if node else ""),
                "ratio_maxcons_full": (max_consecutive_above(
                    window_values(node, "full")) if node else ""),
                "ratio_maxcons_post_fleet": _fleet_maxcons(est_uavs, "post"),
                "ratio_maxcons_full_fleet": _fleet_maxcons(est_uavs, "full"),
                "ratio_first_cross_s": node.get("first_cross_t_rel_sec"),
                "fp_events_clean": fp_n,
                "fp_detectors": fp_names,
            })
            for det in DETECTORS:
                row["fp_" + det] = fp_by.get(det, 0)
            row.update(_mesh(summary))

            if m is not None:
                row.update({
                    "detected": m.detected,
                    "mttd_s": mttd(run_dir),
                    "containment_success": m.containment_success,
                    "time_to_isolation_s": m.time_to_isolation_s,
                    "mttr_functional_s": m.mttr_functional_s,
                    "degradation_stopped": m.degradation_stopped,
                    "total_response_time_s": m.total_response_time_s,
                    "mission_degradation_m": m.mission_degradation_m,
                    "stabilisation_level_m": m.stabilisation_level_m,
                    "residual_mission_func": m.residual_mission_func,
                    "baseline_track_error_m": m.baseline_track_error_m,
                    "legacy_coordination_loss": m.coordination_loss,
                    "legacy_coordination_restored": m.coordination_restored,
                })
            if cm is not None:
                row.update({
                    "phase_excess_m": cm.phase_excess_m,
                    "phase_peak_m": cm.phase_divergence_peak_m,
                    "phase_baseline_m": cm.phase_baseline_m,
                    "geometry_excess_m": cm.geometry_excess_m,
                    "geometry_peak_m": cm.geometry_deviation_peak_m,
                    "geometry_baseline_m": cm.geometry_baseline_m,
                })
            rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--csv", default="runs_campaign/campaign_master.csv")
    args = ap.parse_args()

    rows = build(args.roots)
    with open(args.csv, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    valid = sum(1 for r in rows if r["valid"])
    errored = sum(1 for r in rows if r["errored"])
    prefix = sum(1 for r in rows if r["post_fix"] is False)

    # Інваріант: `detected` і MTTD походять з одного правила, тому
    # «виявлено, але MTTD немає» неможливе за побудовою. Саме ця
    # розбіжність була підписом дефекту `detected` (8 прогонів A і B під
    # takeout-сценаріями рахувались виявленими за рахунок передатакових
    # хибних спрацювань, і в усіх восьми MTTD був порожній). Визначення
    # живе в трьох місцях — derived.py, analyzer.py, campaign_report.mttd
    # — і вже одного разу розʼїхалось. Перевірка стоїть тут, бо це
    # єдина точка, крізь яку проходить кожен прогін.
    inconsistent = [
        r["run_id"] for r in rows
        if r["valid"] and r["detected"] is True and r["mttd_s"] is None
    ]
    print("wrote %s" % args.csv)
    print("  runs          %d" % len(rows))
    print("  valid         %d" % valid)
    print("  errored       %d" % errored)
    print("  gated out     %d" % (len(rows) - valid - errored))
    print("  PRE-FIX runs  %d %s" % (prefix, "<-- MUST BE 0" if prefix else "(ok)"))
    print("  detected w/o MTTD  %d %s"
          % (len(inconsistent),
             "<-- MUST BE 0, detection gate broken" if inconsistent
             else "(ok)"))
    for rid in inconsistent[:10]:
        print("      %s" % rid)

    print("\n  false positives in clean operation (patched accounting):")
    print("  %-6s %8s %8s %12s %10s" % ("arch", "gps", "heartbeat",
                                        "cross_check", "FP runs"))
    per = collections.defaultdict(lambda: collections.Counter())
    fp_runs = collections.Counter()
    runs_by_arch = collections.Counter()
    for r in rows:
        # Той самий фільтр, що й у звітній таблиці R13: `valid`, а не
        # просто «не впав». Раніше тут стояло `if r["errored"]`, через що
        # знаменник у діагностиці був 137 для A проти 136 у тексті —
        # рівно на той один прогін, який відсіяв валідаційний гейт.
        # Для B і C числа збігались, бо відсіяний прогін був у A, і
        # розбіжність видно було лише в одному рядку з трьох.
        if not r["valid"]:
            continue
        arch = str(r["architecture"])
        runs_by_arch[arch] += 1
        if (r["fp_events_clean"] or 0) > 0:
            fp_runs[arch] += 1
        for det in DETECTORS:
            per[arch][det] += r["fp_" + det] or 0
    for arch in sorted(per):
        print("  %-6s %8d %8d %12d %10s"
              % (arch, per[arch]["gps"], per[arch]["heartbeat"],
                 per[arch]["cross_check"],
                 "%d/%d" % (fp_runs[arch], runs_by_arch[arch])))


if __name__ == "__main__":
    main()
