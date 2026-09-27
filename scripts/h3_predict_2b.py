"""H3 step 2b — theta calibration and numeric predictions (before any B1 flight).

Reproduces the [2b] numbers in H3_PREREGISTRATION.md from data that
existed before B1:

  * theta: stage-3 runs (runs_stage3, 3 UAVs, 5 m altitude layers = the
    B1 geometry), pre-injection window [-45, -1] s, every ordered pair,
    20 seeded range-noise realisations; s(t) = min of 3 consecutive
    |rho|; theta = max s rounded up to 0.1 m + 0.5 m.
  * predictions: B0 nav-error vectors e(t) (belief - truth, per level)
    placed on the clean stage-3 geometry one lap (36 s) before injection:
    the victim's announced position stays on the route (clean truth), its
    true position is route - e(t); peers as flown. Alarm = 3 consecutive
    1 Hz announcements with |rho| > theta. Peer path: first peer; self
    path: both pairs bad. harm = |e| at the peer alarm (B0 definition).

Usage (Mac or VM, archives unpacked):
  python3 scripts/h3_predict_2b.py --stage3 ~/s3/runs_stage3 --b0 ~/b0/b0_runs [--east]
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
import zlib

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from metrics import spoof_rate_probe as B  # noqa: E402

UAVS = ("uav_0", "uav_1", "uav_2")
PEERS = ("uav_1", "uav_2")
K = 3
LAP_S = 36.0
CAL_WINDOW = (45.0, 1.0)
SEEDS = 20
# live range model (H3_PREREGISTRATION.md, "Range source")
SIGMA, BIAS, P_NLOS, M_NLOS = 0.1, 0.2, 0.05, 0.5


COVERAGE_MIN = 0.9      # data-quality gate: share of 1 Hz ticks with samples
PAIR_TOL_S = 0.5


def _read(path):
    with open(path) as fh:
        return [json.loads(l) for l in fh if l.strip()]


def _load_json(path):
    with open(path) as fh:
        return json.load(fh)


def coverage_ok(tr, bel, ticks):
    """Every UAV has a truth AND a belief sample within PAIR_TOL_S of at
    least COVERAGE_MIN of the ticks (no interpolation across gaps)."""
    for u in UAVS:
        for a in (tr[u], bel[u]):
            if len(a) == 0:
                return False
            idx = np.clip(np.searchsorted(a[:, 0], ticks), 1, len(a) - 1)
            near = np.minimum(np.abs(a[idx, 0] - ticks), np.abs(a[idx - 1, 0] - ticks))
            if np.mean(near <= PAIR_TOL_S) < COVERAGE_MIN:
                return False
    return True


def load_stage3(d):
    s = _load_json(os.path.join(d, "run_summary.json"))
    if not s.get("flight_at_attack") or s.get("error"):
        return None
    t_inj = s["flight_at_attack"]["t_wall"]
    tr = {u: [] for u in UAVS}
    for r in _read(os.path.join(d, "trajectory.jsonl")):
        if r["uav_id"] in tr:
            tr[r["uav_id"]].append((r["t_wall"], r["y"], r["x"], r["z"]))   # N, E, U
    bel = {}
    for u in UAVS:
        bel[u] = [(r["timestamp"], r["data"]["x"], r["data"]["y"], -r["data"]["z"])
                  for r in _read(os.path.join(d, f"telemetry_monitor_{u}.jsonl"))
                  if r.get("msg_type") == "LOCAL_POSITION_NED"]
    return (t_inj, {u: np.array(sorted(tr[u])) for u in UAVS},
            {u: np.array(sorted(bel[u])) for u in UAVS})


def interp(a, t):
    return np.stack([np.interp(t, a[:, 0], a[:, k]) for k in (1, 2, 3)], axis=-1)


def aligned(tr, bel, t_from, t_to, ticks):
    """Beliefs at ticks, frame offset = median(truth - belief) in [t_from, t_to]."""
    out = {}
    for u in UAVS:
        m = (bel[u][:, 0] >= t_from) & (bel[u][:, 0] <= t_to)
        off = np.median(interp(tr[u], bel[u][m, 0]) - bel[u][m, 1:], axis=0)
        out[u] = interp(bel[u], ticks) + off
    return out


def range_noise(n, rng):
    return (BIAS + rng.normal(0.0, SIGMA, n)
            + (rng.random(n) < P_NLOS) * rng.exponential(M_NLOS, n))


def seeded(*key):
    return np.random.default_rng(zlib.crc32("|".join(map(str, key)).encode()))


def sustained_min(a, k=K):
    if len(a) < k:
        return np.array([])
    return np.min(np.stack([a[i:len(a) - k + 1 + i] for i in range(k)]), axis=0)


def first_sustained(mask, ticks, k=K):
    run = 0
    for i, m in enumerate(mask):
        run = run + 1 if m else 0
        if run >= k:
            return float(ticks[i])
    return None


def calibrate(runs):
    worst, worst_nav = 0.0, 0.0
    n, gated = 0, []
    for d in runs:
        L = load_stage3(d)
        if L is None:
            continue
        t_inj, tr, bel = L
        ticks = np.arange(t_inj - CAL_WINDOW[0], t_inj - CAL_WINDOW[1], 1.0)
        if not coverage_ok(tr, bel, ticks):
            gated.append(os.path.basename(d))
            continue
        n += 1
        b = aligned(tr, bel, ticks[0], ticks[-1], ticks)
        x = {u: interp(tr[u], ticks) for u in UAVS}
        for i in UAVS:
            for j in UAVS:
                if i == j:
                    continue
                implied = np.linalg.norm(b[j] - b[i], axis=1)
                true_r = np.linalg.norm(x[j] - x[i], axis=1)
                worst_nav = max(worst_nav, float(sustained_min(np.abs(implied - true_r)).max()))
                for sd in range(SEEDS):
                    r = true_r + range_noise(len(ticks), seeded("cal", os.path.basename(d), i, j, sd))
                    worst = max(worst, float(sustained_min(np.abs(implied - r)).max()))
    theta = math.ceil(worst * 10 - 1e-9) / 10 + 0.5
    return {"runs": n, "gated": gated, "max_sustained_m": worst, "max_sustained_nav_only_m": worst_nav,
            "theta_m": theta, "h_max_m": theta + 5.0}


def b0_error(d):
    meta = _load_json(os.path.join(d, "meta.json"))
    ti = meta["t_inject"]
    mav = _read(os.path.join(d, "mav.jsonl"))
    tr = np.array(sorted((r["t_wall"], r["y"], r["x"]) for r in _read(os.path.join(d, "trajectory.jsonl"))
                         if r.get("uav_id", "uav_0") == "uav_0"))
    bel = np.array(sorted((r["t_wall"], r["x"], r["y"]) for r in mav if r.get("type") == "LOCAL_POSITION_NED"))
    tt = np.stack([np.interp(bel[:, 0], tr[:, 0], tr[:, k]) for k in (1, 2)], 1)
    m = (bel[:, 0] >= ti - B.BIAS_WINDOW_S) & (bel[:, 0] <= ti)
    e = bel[:, 1:] + np.median(tt[m] - bel[m, 1:], 0) - tt
    return meta["level"], bel[:, 0] - ti, e


def e_at(t_rel, e, t):
    return np.stack([np.interp(t, t_rel, e[:, 0]), np.interp(t, t_rel, e[:, 1])], 1)


def predict(runs, b0_dirs, theta, east=False):
    geoms = []
    for d in runs:
        L = load_stage3(d)
        if L is None:
            continue
        t_inj, tr, bel = L
        t0 = t_inj - LAP_S
        ticks = np.arange(t0, t0 + LAP_S - 1.0, 1.0)
        cal_ticks = np.arange(t_inj - CAL_WINDOW[0], t_inj - CAL_WINDOW[1], 1.0)
        if not (coverage_ok(tr, bel, ticks) and coverage_ok(tr, bel, cal_ticks)):
            continue
        b = aligned(tr, bel, t_inj - CAL_WINDOW[0], t_inj - CAL_WINDOW[1], ticks)
        geoms.append((os.path.basename(d), ticks - t0, b, {u: interp(tr[u], ticks) for u in UAVS}))
    levels = {}
    for d in b0_dirs:
        lv, t_rel, e = b0_error(d)
        levels.setdefault(lv, []).append((os.path.basename(d), t_rel, e))
    out = {}
    for lv, flights in levels.items():
        rows = []
        for fname, t_rel, e in flights:
            en = np.linalg.norm(e, axis=1)
            t_jump = next((float(t) for t, v in zip(t_rel, en) if t >= 0 and v > B.JUMP_M), None)
            for gname, rel, b, x in geoms:
                ev = e_at(t_rel, e, rel)
                if east:
                    ev = ev[:, [1, 0]]
                x0 = x["uav_0"] - np.concatenate([ev, np.zeros((len(rel), 1))], 1)
                for sd in range(SEEDS):
                    bad = {}
                    for p in PEERS:
                        implied = np.linalg.norm(x["uav_0"] - b[p], axis=1)
                        r = np.linalg.norm(x0 - x[p], axis=1) + range_noise(len(rel), seeded(lv, fname, gname, p, sd))
                        bad[p] = np.abs(implied - r) > theta
                    tp = [v for v in (first_sustained(bad[p], rel) for p in PEERS) if v is not None]
                    t_peer = min(tp) if tp else None
                    rows.append({
                        "t_peer": t_peer,
                        "t_self": first_sustained(bad["uav_1"] & bad["uav_2"], rel),
                        "harm": (float(np.linalg.norm(e_at(t_rel, e, np.array([t_peer]))[0]))
                                 if t_peer is not None else None),
                        "t_jump": t_jump,
                    })
        out[lv] = rows
    e_end = {f[0]: {"e60": float(np.linalg.norm(e_at(f[1], f[2], np.array([60.0]))[0])),
                    "e120": float(np.linalg.norm(e_at(f[1], f[2], np.array([120.0]))[0]))}
             for f in levels.get("L1", [])}
    return out, len(geoms), e_end


def _q(a):
    if not a:
        return "none"
    a = np.asarray(a)
    return "median %.1f, p5-p95 %.1f-%.1f, range %.1f-%.1f" % (
        np.median(a), *np.percentile(a, [5, 95]), a.min(), a.max())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage3", required=True)
    ap.add_argument("--b0", required=True)
    ap.add_argument("--east", action="store_true", help="rotate the B0 error vector north -> east")
    a = ap.parse_args(argv)
    runs = sorted(r for r in glob.glob(os.path.join(os.path.expanduser(a.stage3), "run_C_*"))
                  if os.path.exists(os.path.join(r, "trajectory.jsonl")))
    cal = calibrate(runs)
    print(json.dumps(cal, indent=1))
    b0_dirs = sorted(glob.glob(os.path.join(os.path.expanduser(a.b0), "L*_*")))
    out, ng, e_end = predict(runs, b0_dirs, cal["theta_m"], east=a.east)
    print(f"geometries {ng} x seeds {SEEDS} x B0 flights; direction {'east' if a.east else 'north'}")
    for lv in sorted(out, key=lambda l: -B.LEVELS[l]):
        rows = out[lv]
        tp = [r["t_peer"] for r in rows if r["t_peer"] is not None]
        hm = [r["harm"] for r in rows if r["harm"] is not None]
        ts = [r["t_self"] for r in rows if r["t_self"] is not None]
        early = sum(1 for r in rows if r["t_peer"] is not None and r["t_jump"] is not None
                    and r["t_peer"] < r["t_jump"] - 0.5)
        ok = sum(1 for h in hm if h <= cal["h_max_m"])
        tj = sorted({round(r["t_jump"], 2) for r in rows if r["t_jump"] is not None})
        print(f"{lv}: n={len(rows)} peer-detected={len(tp)} | t_peer s: {_q(tp)} | t_self s: {_q(ts)}")
        print(f"     harm m: {_q(hm)} | harm<=H_max {ok}/{len(hm)} | t_jump {tj} | peer before jump-0.5: {early}")
    for k, v in e_end.items():
        print(f"L1 {k}: |e|(60 s) {v['e60']:.1f} m, |e|(120 s) {v['e120']:.1f} m")


if __name__ == "__main__":
    main()
