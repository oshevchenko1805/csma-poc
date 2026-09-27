"""
metrics/collision_flags.py — per-run flag: did any UAV fall after a peer
contact? Used ONLY for the sensitivity table of Ch. 4 (main tables keep
the full valid sample; validity rules are not changed after the fact).

Background: OPEN-5 (metrics/fp_contact.py). In thesis-campaign-v1 the
three UAVs share one 20 m layer; peers touch in a sizeable share of runs
and the touched UAV drops towards the ground, then PX4 climbs back.

Definitions (fixed before the sensitivity table was computed)
-------------------------------------------------------------
fall            truth altitude above its own origin goes from > FALL_FROM_M
                to < FALL_TO_M within FALL_WITHIN_S. A normal PX4 landing
                (~0.7 m/s) cannot do this; a knocked-down airframe does.
collision_fall  a fall of ANY UAV with a contact (< 1 m, metrics.
                peer_separation) of that UAV starting within
                LOOKBACK_S before the fall. Whole run, not only before
                injection — the sensitivity table asks "does anything
                change without these runs", so the stricter flag is used.
target_fell_pre a collision_fall of the target before inject_start.

Usage
-----
    python3 -m metrics.collision_flags <runs_root> <campaign_master.csv> <out.csv>
"""

from __future__ import annotations

import bisect
import csv
import sys

from metrics.derived import _attack_ts, load_events
from metrics.fp_contact import contact_starts, load_world_xyz, run_dirs
from metrics.plots import load, valid_rows

FALL_FROM_M = 15.0
FALL_TO_M = 5.0
FALL_WITHIN_S = 5.0
FALL_MIN_GAP_S = 20.0
LOOKBACK_S = 10.0

FIELDS = ["run_id", "architecture", "attack", "collision_fall",
          "n_collision_falls", "target_fell_pre", "uavs_fallen"]


def fall_times(samples: list) -> list:
    """Times at which a fall completes (altitude < FALL_TO_M), deduplicated."""
    if not samples:
        return []
    z0 = samples[0][3]
    ts = [s[0] for s in samples]
    out = []
    for k, s in enumerate(samples):
        if s[3] - z0 <= FALL_FROM_M:
            continue
        j = bisect.bisect_right(ts, s[0] + FALL_WITHIN_S)
        hit = next((y for y in samples[k:j] if y[3] - z0 < FALL_TO_M), None)
        if hit and (not out or hit[0] - out[-1] > FALL_MIN_GAP_S):
            out.append(hit[0])
    return out


def collision_falls(xyz: dict) -> dict:
    """{uav: [fall times preceded by a contact within LOOKBACK_S]}."""
    out = {}
    for u, s in xyz.items():
        starts = contact_starts(xyz, u, float("-inf"), float("inf"))
        out[u] = [t for t in fall_times(s)
                  if any(t - LOOKBACK_S <= c <= t for c in starts)]
    return out


def flag_run(run_dir: str, row: dict) -> dict:
    xyz = load_world_xyz(run_dir)
    cf = collision_falls(xyz)
    target = row.get("target_uav") or "uav_0"
    t0 = _attack_ts(load_events(run_dir))
    pre = [t for t in cf.get(target, []) if t0 is not None and t < t0]
    n = sum(len(v) for v in cf.values())
    return {
        "run_id": row["run_id"], "architecture": row["architecture"],
        "attack": row["attack"], "collision_fall": n > 0,
        "n_collision_falls": n,
        "target_fell_pre": bool(pre) and str(row["attack"]).lower() not in ("", "none"),
        "uavs_fallen": "|".join(sorted(u for u, v in cf.items() if v)),
    }


def main(argv: list) -> int:
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    root, master, out = argv[1:]
    dirs = run_dirs(root)
    rows = valid_rows(load(master))
    missing = [r["run_id"] for r in rows if r["run_id"] not in dirs]
    if missing:
        print("MISSING %d run dirs, not writing a partial file" % len(missing),
              file=sys.stderr)
        return 1
    res = [flag_run(dirs[r["run_id"]], r) for r in rows]
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(res)
    print("wrote %s: %d runs, collision_fall %d, target_fell_pre %d"
          % (out, len(res), sum(r["collision_fall"] for r in res),
             sum(r["target_fell_pre"] for r in res)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
