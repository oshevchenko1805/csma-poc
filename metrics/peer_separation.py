"""
metrics/peer_separation.py — swarm-safety outcome of a response
(review stage 3, secondary metric; defined after pilot run B1, BEFORE
the H2 campaign — see STAGE3_PILOT.md).

Why
---
Pilot B1 (trust_aware, GPS spoofing): the zero-velocity hold stopped
uav_0 on its route within 1.4 m for 30 s; uav_2, still flying its own
overlapping square at the same 20 m layer, then hit it (min 3D gap
0.39 m at +33.1 s) and pushed it ~8 m. Stopping one vehicle without
deconfliction creates a collision hazard for the swarm. This module
measures that hazard for EVERY arm (proportionate, trust_aware,
detect_only), because LOITER's 50 m spoof drift and a spoofed mission
continuing 50 m off-route can also cross peers' routes.

Definitions (fixed now)
-----------------------
Window         [t_inject, t_inject + WINDOW_S] — identical for all arms,
               independent of when (or whether) a response happened.
Separation     3D Euclidean distance between the target and each peer,
               Gazebo world frame (trajectory.jsonl x, y, z — truth, not
               the spoofable estimate). Target samples paired with the
               nearest peer sample within PAIR_TOL_S.
min_peer_sep_m min over the window and all peers.
n_contacts     episodes with separation < CONTACT_M (1.0 m: less than an
               x500 airframe span — physical contact in SITL).
n_near_miss    episodes with separation < NEAR_MISS_M (3.0 m).
Episode        maximal run of consecutive paired target samples below the
               threshold; a gap > EPISODE_GAP_S between below-threshold
               samples starts a new episode. Counted per peer, summed.

Reported descriptively per arm and cell (counts with Wilson CI); no
hypothesis is tested on it — it explains, it does not decide.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import sys
from typing import Optional

from metrics.derived import _attack_ts, load_events
from metrics.physical_outcomes import WINDOW_S

CONTACT_M = 1.0
NEAR_MISS_M = 3.0
PAIR_TOL_S = 0.25
EPISODE_GAP_S = 1.0


def load_world_xyz(run_dir: str) -> dict:
    """{uav_id: [(t_wall, x, y, z), ...]} sorted, Gazebo world frame."""
    path = os.path.join(run_dir, "trajectory.jsonl")
    out: dict = {}
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                out.setdefault(r["uav_id"], []).append(
                    (float(r["t_wall"]), float(r["x"]), float(r["y"]), float(r["z"])))
            except (ValueError, KeyError, TypeError):
                continue
    for v in out.values():
        v.sort()
    return out


def _nearest(samples: list, ts: list, t: float) -> Optional[tuple]:
    i = bisect.bisect_left(ts, t)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(samples) and abs(samples[j][0] - t) <= PAIR_TOL_S:
            if best is None or abs(samples[j][0] - t) < abs(best[0] - t):
                best = samples[j]
    return best


def separation_series(target: list, peer: list, t_from: float, t_to: float) -> list:
    """[(t, 3D distance)] at target timestamps within [t_from, t_to]."""
    ts = [s[0] for s in peer]
    out = []
    for s in target:
        if t_from <= s[0] <= t_to:
            p = _nearest(peer, ts, s[0])
            if p is not None:
                out.append((s[0], math.dist(s[1:], p[1:])))
    return out


def count_episodes(series: list, threshold: float, gap: float = EPISODE_GAP_S) -> int:
    n, last_below = 0, None
    for t, d in series:
        if d < threshold:
            if last_below is None or t - last_below > gap:
                n += 1
            last_below = t
    return n


def summarize(xyz: dict, target: str, t_inject: float,
              window: float = WINDOW_S) -> dict:
    out = {"min_peer_sep_m": None, "t_min_peer_sep_s": None,
           "closest_peer": None, "n_contacts": None, "n_near_miss": None}
    tgt = xyz.get(target)
    peers = [u for u in xyz if u != target]
    if not tgt or not peers:
        return out
    t_to = t_inject + window
    n_c = n_n = 0
    best = None
    for u in peers:
        ser = separation_series(tgt, xyz[u], t_inject, t_to)
        if not ser:
            continue
        n_c += count_episodes(ser, CONTACT_M)
        n_n += count_episodes(ser, NEAR_MISS_M)
        m = min(ser, key=lambda s: s[1])
        if best is None or m[1] < best[1]:
            best = (m[0], m[1], u)
    if best is None:
        return out
    out.update(min_peer_sep_m=best[1], t_min_peer_sep_s=best[0] - t_inject,
               closest_peer=best[2], n_contacts=n_c, n_near_miss=n_n)
    return out


def analyse_run(run_dir: str) -> dict:
    with open(os.path.join(run_dir, "run_summary.json")) as fh:
        s = json.load(fh)
    t0 = _attack_ts(load_events(run_dir))
    if t0 is None:
        return summarize({}, "", 0.0)
    return summarize(load_world_xyz(run_dir), s.get("target_uav") or "uav_0", t0)


def main(argv: list) -> int:
    for d in argv[1:]:
        r = analyse_run(d)
        print(os.path.basename(d.rstrip("/")), json.dumps(
            {k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
