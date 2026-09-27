"""H3 step 2c — attribution seen from every monitor, including the victim's.

Before any B1 code or flight. Step 2b modelled only the peers' view of the
victim (peer path) and the victim's self path. It did not model what the
victim's OWN monitor concludes about its peers. Its p_i is the victim's
EKF position (tainted), so "bad with uav_1, fine with uav_2" can occur
while the pair 0-2 is still below theta, and the literal rule would flag
uav_1 (a misattribution).

This script re-runs the 2b model (same data, geometries, B0 error series,
theta, seed keys for the peer path) for all three monitors and compares
definitions of "fine with peer k" in the attribution rule:

  literal   fine = not bad (fewer than K consecutive |rho| > theta)
  okT       fine = the last K consecutive |rho| <= T, T in {theta, 1.3, 0.9}
  +latch    once monitor i has flagged itself, it flags no peer afterwards

Chosen (H3_PREREGISTRATION.md, [2c]): ok1.3+latch. 1.3 m = calibration
max of sustained honest |rho| (1.24 m) rounded up, i.e. theta without the
0.5 m margin.

"bad" is unchanged in every rule: K = 3 consecutive |rho| > theta.
Attribution per monitor i at each tick (fresh pairs = both peers):
  all pairs bad (>= 2 peers)          -> flag i (self path)
  pair ij bad and some pair ik fine   -> flag j (peer path)

Assumptions beyond 2b: every ordered pair is measured by its own monitor
with independent range noise (pair (p, uav_0) keeps the 2b seed key, so
the peers' view reproduces 2b); all announcements fall on the same whole-
second ticks; the window is one lap (35 s) after injection.

Usage (Mac or VM, archives unpacked):
  python3 scripts/h3_predict_2c.py --stage3 ~/s3/runs_stage3 --b0 ~/b0/b0_runs
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import h3_predict_2b as P  # noqa: E402

VICTIM = "uav_0"
BASE_RULES = ("literal", "ok_theta", "ok1.3", "ok0.9")
# "+latch": once monitor i has flagged itself, it stops flagging peers
# (its own position is then known to be tainted).
RULES = BASE_RULES + tuple(r + "+latch" for r in BASE_RULES)


def runs_of(mask, k=P.K):
    """Boolean array: True where the last k entries of mask are all True."""
    out = np.zeros(len(mask), dtype=bool)
    run = 0
    for i, m in enumerate(mask):
        run = run + 1 if m else 0
        out[i] = run >= k
    return out


def fine_mask(rule, absrho, theta, bad):
    rule = rule.split("+")[0]
    if rule == "literal":
        return ~bad
    t = theta if rule == "ok_theta" else float(rule[2:])
    return runs_of(absrho <= t)


def attribute(i, bad, fine, n, latch=False):
    """Per tick, the set of UAVs monitor i flags. bad/fine: peer -> mask."""
    peers = [u for u in P.UAVS if u != i]
    flags = []
    self_seen = False
    for t in range(n):
        if all(bad[p][t] for p in peers):
            flags.append({i})
            self_seen = True
            continue
        f = set()
        if latch and self_seen:
            flags.append(f)
            continue
        for j in peers:
            if bad[j][t] and any(fine[k][t] for k in peers if k != j):
                f.add(j)
        flags.append(f)
    return flags


def views(x_true, b, noise_key, n):
    """|rho| for every ordered pair (i, j) as measured by monitor i."""
    out = {}
    for i in P.UAVS:
        for j in P.UAVS:
            if i == j:
                continue
            implied = np.linalg.norm(b[j] - b[i], axis=1)
            true_r = np.linalg.norm(x_true[j] - x_true[i], axis=1)
            out[(i, j)] = np.abs(implied - (true_r + P.range_noise(n, noise_key(i, j))))
    return out


def evaluate(absrho, theta, n):
    """rule -> monitor -> per-tick flag sets."""
    bad = {ij: runs_of(a > theta) for ij, a in absrho.items()}
    res = {}
    for rule in RULES:
        fine = {ij: fine_mask(rule, absrho[ij], theta, bad[ij]) for ij in absrho}
        res[rule] = {i: attribute(i, {j: bad[(i, j)] for j in P.UAVS if j != i},
                                  {j: fine[(i, j)] for j in P.UAVS if j != i}, n,
                                  latch=rule.endswith("+latch"))
                     for i in P.UAVS}
    return res


def first(ticks, flags_per_tick, pred):
    for t, f in zip(ticks, flags_per_tick):
        if pred(f):
            return float(t)
    return None


def load_geoms(runs):
    geoms = []
    for d in runs:
        L = P.load_stage3(d)
        if L is None:
            continue
        t_inj, tr, bel = L
        t0 = t_inj - P.LAP_S
        ticks = np.arange(t0, t0 + P.LAP_S - 1.0, 1.0)
        cal_ticks = np.arange(t_inj - P.CAL_WINDOW[0], t_inj - P.CAL_WINDOW[1], 1.0)
        if not (P.coverage_ok(tr, bel, ticks) and P.coverage_ok(tr, bel, cal_ticks)):
            continue
        b = P.aligned(tr, bel, t_inj - P.CAL_WINDOW[0], t_inj - P.CAL_WINDOW[1], ticks)
        bc = P.aligned(tr, bel, cal_ticks[0], cal_ticks[-1], cal_ticks)
        geoms.append({"name": os.path.basename(d), "rel": ticks - t0, "b": b,
                      "x": {u: P.interp(tr[u], ticks) for u in P.UAVS},
                      "cal_rel": cal_ticks - cal_ticks[0], "cal_b": bc,
                      "cal_x": {u: P.interp(tr[u], cal_ticks) for u in P.UAVS}})
    return geoms


def no_attack(geoms, theta):
    """Flags of any kind on the calibration windows (no attack): must be 0."""
    count = {r: 0 for r in RULES}
    for g in geoms:
        n = len(g["cal_rel"])
        for sd in range(P.SEEDS):
            key = lambda i, j: P.seeded("2c-cal", g["name"], i, j, sd)  # noqa: E731
            res = evaluate(views(g["cal_x"], g["cal_b"], key, n), theta, n)
            for r in RULES:
                count[r] += sum(1 for i in P.UAVS for f in res[r][i] if f)
    return count


def attack(geoms, b0_dirs, theta):
    levels = {}
    for d in b0_dirs:
        lv, t_rel, e = P.b0_error(d)
        levels.setdefault(lv, []).append((os.path.basename(d), t_rel, e))
    out = {}
    for lv, flights in levels.items():
        rows = {r: [] for r in RULES}
        for fname, t_rel, e in flights:
            for g in geoms:
                rel, b, x = g["rel"], g["b"], g["x"]
                n = len(rel)
                ev = P.e_at(t_rel, e, rel)
                xt = dict(x)
                xt[VICTIM] = x[VICTIM] - np.concatenate([ev, np.zeros((n, 1))], 1)
                for sd in range(P.SEEDS):
                    def key(i, j, sd=sd, g=g, fname=fname):
                        if j == VICTIM:   # the peers' view: same key as 2b
                            return P.seeded(lv, fname, g["name"], i, sd)
                        return P.seeded("2c", lv, fname, g["name"], i, j, sd)
                    res = evaluate(views(xt, b, key, n), theta, n)
                    for r in RULES:
                        peer_t = [first(rel, res[r][p], lambda f: VICTIM in f)
                                  for p in P.UAVS if p != VICTIM]
                        peer_t = [t for t in peer_t if t is not None]
                        t_peer = min(peer_t) if peer_t else None
                        mis_v = first(rel, res[r][VICTIM], lambda f: bool(f - {VICTIM}))
                        mis_p = [first(rel, res[r][p], lambda f: bool(f - {VICTIM}))
                                 for p in P.UAVS if p != VICTIM]
                        rows[r].append({
                            "t_peer": t_peer,
                            "t_self": first(rel, res[r][VICTIM], lambda f: VICTIM in f),
                            "harm": (float(np.linalg.norm(P.e_at(t_rel, e, np.array([t_peer]))[0]))
                                     if t_peer is not None else None),
                            "mis_victim": mis_v,
                            "mis_peers": any(m is not None for m in mis_p),
                        })
        out[lv] = rows
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage3", required=True)
    ap.add_argument("--b0", required=True)
    ap.add_argument("--theta", type=float, default=1.8, help="frozen 2b value")
    a = ap.parse_args(argv)
    runs = sorted(r for r in glob.glob(os.path.join(os.path.expanduser(a.stage3), "run_C_*"))
                  if os.path.exists(os.path.join(r, "trajectory.jsonl")))
    geoms = load_geoms(runs)
    b0_dirs = sorted(glob.glob(os.path.join(os.path.expanduser(a.b0), "L*_*")))
    h_max = a.theta + 5.0
    print(f"theta {a.theta} m, H_max {h_max} m; geometries {len(geoms)} x seeds {P.SEEDS}")
    print("no-attack flags (all monitors, any target):", json.dumps(no_attack(geoms, a.theta)))
    out = attack(geoms, b0_dirs, a.theta)
    for lv in sorted(out, key=lambda l: -P.B.LEVELS[l]):
        for r in RULES:
            rows = out[lv][r]
            tp = [x["t_peer"] for x in rows if x["t_peer"] is not None]
            hm = [x["harm"] for x in rows if x["harm"] is not None]
            ts = [x["t_self"] for x in rows if x["t_self"] is not None]
            mv = [x["mis_victim"] for x in rows if x["mis_victim"] is not None]
            mp = sum(1 for x in rows if x["mis_peers"])
            ok = sum(1 for h in hm if h <= h_max)
            print(f"{lv} {r:8s} n={len(rows)} peer-det={len(tp)} | t_peer {P._q(tp)} | "
                  f"t_self {P._q(ts)}")
            print(f"{'':12s} harm {P._q(hm)} | <=H_max {ok}/{len(hm)} | "
                  f"misattr: victim's monitor {len(mv)}/{len(rows)} (t {P._q(mv)}), "
                  f"peers' monitors {mp}/{len(rows)}")


if __name__ == "__main__":
    main()
