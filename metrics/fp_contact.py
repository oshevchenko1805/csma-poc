"""
metrics/fp_contact.py — OPEN-5: are the v1 false positives and the 1–2 m
baseline navigation-error peaks caused by peer contacts?

Why
---
Stage-3 pilot (STAGE3_PILOT.md) found that in thesis-campaign-v1 the three
UAVs fly on one 20 m layer with squares offset 5/10 m, and touch (< 1 m)
in 13 of 34 clean flights. A contact pushes the airframe faster than the
EKF follows, so it can (a) drive the GPS innovation ratio over 1.0 for
k=3 samples -> `gps` detector fires with no attack; (b) make a peer's
announced position jump -> `cross_check` fires; (c) show up as a peak of
|belief - truth| in clean flights (RESULTS_NOTES: "peaks 1-2 m ...
baseline ceiling ~2 m"). If so, these are testbed artefacts and Ch. 4
must present them that way, not as the detector's false-positive rate.

Everything below is fixed BEFORE the first run of this script on data.

Definitions
-----------
Contact        separation < CONTACT_M (1.0 m) between the UAV and any
               peer, Gazebo truth, 3D; pairing/episodes exactly as in
               metrics.peer_separation. Only while the UAV is airborne
               (truth z - z_origin > AIRBORNE_M).
Coincident     a contact episode of the ACCUSED/affected UAV starts in
               [t - LOOKBACK_S, t + LEAD_S] around the event time t.
               LOOKBACK_S = 10 s covers k=3 samples at ~1 Hz plus EKF lag;
               LEAD_S = 1 s covers timestamp jitter.
Exposure       as in metrics.fp_census: clean flight = whole run; attack
               run = before inject_start.
Base rate p0   fraction of 1 s grid points t inside airborne exposure
               windows (all valid runs x 3 UAVs for Q1; valid clean
               flights x 3 UAVs for Q2) that would be "coincident" by the
               same rule. The chance level of the coincidence test.

Q1 — false positives (unit = FP run; the FIRST event of the tested
     detector class in the exposure window, so a burst counts once)
     Tested class: `gps` and `cross_check`.
     `heartbeat` FPs are reported, not tested: they fire on all three
     UAVs within 0.06 s, and a contact has no path into heartbeat timing.
     Pre-stated prediction for them: not coincident beyond p0.
Q2 — baseline peaks (unit = peak episode)
     Clean flights only. Peak episode = maximal run of airborne samples
     of run_summary.belief_divergence (1 Hz) with horizontal error
     > PEAK_M (1.0 m); gap > PEAK_GAP_S starts a new episode; t = first
     sample of the episode.

Verdict rule (per question)
---------------------------
  ARTEFACT       coincident fraction >= 0.80 AND one-sided binomial
                 P(X >= k | n, p0) < 0.01.
  NOT_EXPLAINED  coincident fraction <= max(0.20, 2 * p0).
  MIXED          anything else; the coincident units are reclassified as
                 artefacts, the rest stay genuine.
Reverse direction (descriptive only): share of contact episodes in the
exposure windows followed within LOOKBACK_S by an FP / a peak.

Usage
-----
    python -m metrics.fp_contact <runs_root> <campaign_master.csv> \\
        <fp_census.csv> [--csv out.csv]
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import sys
from typing import Optional

from metrics.derived import _attack_ts, load_events
from metrics.peer_separation import CONTACT_M, EPISODE_GAP_S, separation_series
from metrics.plots import load, valid_rows

LOOKBACK_S = 10.0
LEAD_S = 1.0
AIRBORNE_M = 1.0
PEAK_M = 1.0
PEAK_GAP_S = 2.0
GRID_S = 1.0
TESTED_DETECTORS = ("gps", "cross_check")
ALPHA = 0.01
ARTEFACT_FRAC = 0.80
NOT_EXPLAINED_FLOOR = 0.20


# ---------------------------------------------------------------- pure parts

def airborne_mask_fn(samples: list):
    """samples [(t, x, y, z)] -> f(t) -> bool, using the first sample as z origin."""
    if not samples:
        return lambda t: False
    z0 = samples[0][3]
    ts = [s[0] for s in samples]
    import bisect

    def f(t: float) -> bool:
        i = bisect.bisect_left(ts, t)
        for j in (i - 1, i):
            if 0 <= j < len(samples) and abs(samples[j][0] - t) <= 0.5:
                return samples[j][3] - z0 > AIRBORNE_M
        return False
    return f


def contact_starts(xyz: dict, uav: str, t_from: float, t_to: float) -> list:
    """Start times of contact episodes of `uav` with any peer, airborne only."""
    tgt = xyz.get(uav) or []
    air = airborne_mask_fn(tgt)
    starts = []
    for peer, ps in xyz.items():
        if peer == uav:
            continue
        ser = [(t, d) for t, d in separation_series(tgt, ps, t_from, t_to) if air(t)]
        last = None
        for t, d in ser:
            if d < CONTACT_M:
                if last is None or t - last > EPISODE_GAP_S:
                    starts.append(t)
                last = t
    return sorted(starts)


def coincident(t: float, starts: list,
               lookback: float = LOOKBACK_S, lead: float = LEAD_S) -> bool:
    return any(t - lookback <= s <= t + lead for s in starts)


def grid_points(t_from: float, t_to: float, air, step: float = GRID_S) -> list:
    out, t = [], t_from
    while t <= t_to:
        if air(t):
            out.append(t)
        t += step
    return out


def peak_episode_starts(t_wall: list, err: list, air,
                        thr: float = PEAK_M, gap: float = PEAK_GAP_S) -> list:
    out, last = [], None
    for t, e in zip(t_wall, err):
        if e is None or not air(t):
            continue
        if e > thr:
            if last is None or t - last > gap:
                out.append(t)
            last = t
    return out


def binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k), X ~ Bin(n, p)."""
    if k <= 0:
        return 1.0
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def verdict(k: int, n: int, p0: float) -> dict:
    frac = k / n if n else float("nan")
    p = binom_sf(k, n, p0) if n else float("nan")
    if n and frac >= ARTEFACT_FRAC and p < ALPHA:
        v = "ARTEFACT"
    elif n and frac <= max(NOT_EXPLAINED_FLOOR, 2 * p0):
        v = "NOT_EXPLAINED"
    else:
        v = "MIXED"
    return {"k": k, "n": n, "frac": frac, "p0": p0, "p_binom": p, "verdict": v}


# ---------------------------------------------------------------- I/O parts

def load_world_xyz(run_dir: str) -> dict:
    out: dict = {}
    path = os.path.join(run_dir, "trajectory.jsonl")
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        for line in fh:
            try:
                r = json.loads(line)
                out.setdefault(r["uav_id"], []).append(
                    (float(r["t_wall"]), float(r["x"]), float(r["y"]), float(r["z"])))
            except (ValueError, KeyError, TypeError):
                continue
    for v in out.values():
        v.sort()
    return out


def run_dirs(root: str) -> dict:
    return {os.path.basename(d)[4:]: d
            for d in glob.glob(os.path.join(root, "*", "run_*")) if os.path.isdir(d)}


def exposure(events: list, attack: str, xyz: dict) -> tuple:
    ts = [s[0] for v in xyz.values() for s in v]
    if not ts:
        return None, None
    t_from, t_to = min(ts), max(ts)
    if str(attack).lower() not in ("", "none"):
        t0 = _attack_ts(events)
        if t0 is None:
            return None, None
        t_to = min(t_to, t0)
    return t_from, t_to


def analyse(runs_root: str, master_csv: str, census_csv: str) -> dict:
    dirs = run_dirs(runs_root)
    master = valid_rows(load(master_csv))
    with open(census_csv) as fh:
        census = {r["run_id"]: r for r in csv.DictReader(fh)}

    grid_all, grid_clean = [], []          # per grid point: coincident?
    fp_rows, peak_rows, reverse = [], [], {"fp": [0, 0], "peak": [0, 0]}
    missing = []

    for r in master:
        rid = r["run_id"]
        d = dirs.get(rid)
        if d is None:
            missing.append(rid)
            continue
        is_clean = str(r["attack"]).lower() in ("", "none")
        events = load_events(d)
        xyz = load_world_xyz(d)
        t_from, t_to = exposure(events, r["attack"], xyz)
        if t_from is None:
            continue
        starts = {u: contact_starts(xyz, u, t_from, t_to) for u in xyz}
        airs = {u: airborne_mask_fn(xyz[u]) for u in xyz}
        for u in xyz:
            g = [coincident(t, starts[u]) for t in grid_points(t_from, t_to, airs[u])]
            grid_all += g
            if is_clean:
                grid_clean += g

        # Q1 — false positives
        sec = [e for e in events if e.get("event_type") == "security"
               and t_from <= float(e["timestamp"]) <= t_to + 1e-6]
        fp_times = {}
        for e in sec:
            fp_times.setdefault(str(e.get("target_uav")), []).append(float(e["timestamp"]))
        if rid in census:
            for cls in ("tested", "heartbeat"):
                ev = [e for e in sec if (e.get("detector") in TESTED_DETECTORS) == (cls == "tested")]
                if not ev:
                    continue
                e = min(ev, key=lambda e: float(e["timestamp"]))
                u, t = str(e.get("target_uav")), float(e["timestamp"])
                prior = [s for s in starts.get(u, []) if s <= t + LEAD_S]
                fp_rows.append({
                    "run_id": rid, "architecture": r["architecture"],
                    "attack": r["attack"], "class": cls,
                    "detector": e.get("detector"), "accused": u,
                    "t_fp_rel_s": round(t - t_from, 2),
                    "coincident": coincident(t, starts.get(u, [])),
                    "dt_contact_s": (round(t - prior[-1], 2) if prior else ""),
                    "n_contacts_uav": len(starts.get(u, [])),
                    "evidence": json.dumps(e.get("evidence", {}))[:120],
                })
        for u, ss in starts.items():
            for s in ss:
                reverse["fp"][1] += 1
                if any(s - LEAD_S <= t <= s + LOOKBACK_S for t in fp_times.get(u, [])):
                    reverse["fp"][0] += 1

        # Q2 — baseline peaks (clean flights only)
        if is_clean:
            with open(os.path.join(d, "run_summary.json")) as fh:
                bd = (json.load(fh).get("belief_divergence") or {})
            a = bd.get("attack_at_wall")
            for u, ser in (bd.get("uavs") or {}).items():
                if a is None or u not in xyz:
                    continue
                tw = [a + t for t in ser.get("t_rel_sec", [])]
                err = ser.get("divergence_horiz_m", [])
                pks = peak_episode_starts(tw, err, airs[u])
                for t in pks:
                    i = tw.index(t)
                    peak_rows.append({
                        "run_id": rid, "uav": u, "t_rel_s": round(t - t_from, 2),
                        "peak_m": round(max(e for tt, e in zip(tw, err)
                                            if t <= tt <= t + 30 and e is not None), 2),
                        "coincident": coincident(t, starts[u]),
                        "n_contacts_uav": len(starts[u]),
                    })
                for s in starts[u]:
                    reverse["peak"][1] += 1
                    if any(s - LEAD_S <= t <= s + LOOKBACK_S for t in pks):
                        reverse["peak"][0] += 1

    p_all = sum(grid_all) / len(grid_all) if grid_all else float("nan")
    p_clean = sum(grid_clean) / len(grid_clean) if grid_clean else float("nan")
    tested = [x for x in fp_rows if x["class"] == "tested"]
    hb = [x for x in fp_rows if x["class"] == "heartbeat"]
    return {
        "missing": missing,
        "p0_all": p_all, "p0_clean": p_clean,
        "q1_tested": verdict(sum(x["coincident"] for x in tested), len(tested), p_all),
        "q1_heartbeat": verdict(sum(x["coincident"] for x in hb), len(hb), p_all),
        "q2_peaks": verdict(sum(x["coincident"] for x in peak_rows), len(peak_rows), p_clean),
        "reverse_contact_to_fp": reverse["fp"],
        "reverse_contact_to_peak": reverse["peak"],
        "fp_rows": fp_rows, "peak_rows": peak_rows,
    }


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs_root")
    ap.add_argument("master")
    ap.add_argument("census")
    ap.add_argument("--csv", default=None)
    a = ap.parse_args(argv)
    res = analyse(a.runs_root, a.master, a.census)
    if res["missing"]:
        print("MISSING %d run dirs, not computing a partial sample" % len(res["missing"]),
              file=sys.stderr)
        return 1
    for r in res["fp_rows"]:
        print("FP  %-46s %-9s %-11s %-5s coinc=%-5s dt=%s n_c=%d"
              % (r["run_id"], r["class"], r["detector"], r["accused"],
                 r["coincident"], r["dt_contact_s"], r["n_contacts_uav"]))
    for r in res["peak_rows"]:
        print("PK  %-46s %-5s t=%7.1f peak=%6.2f coinc=%-5s n_c=%d"
              % (r["run_id"], r["uav"], r["t_rel_s"], r["peak_m"],
                 r["coincident"], r["n_contacts_uav"]))
    print("p0 all=%.3f clean=%.3f" % (res["p0_all"], res["p0_clean"]))
    for k in ("q1_tested", "q1_heartbeat", "q2_peaks"):
        v = res[k]
        print("%-13s %d/%d = %.2f  p0=%.3f  p=%.2g  -> %s"
              % (k, v["k"], v["n"], v["frac"], v["p0"], v["p_binom"], v["verdict"]))
    print("reverse contact->FP %d/%d, contact->peak %d/%d"
          % (*res["reverse_contact_to_fp"], *res["reverse_contact_to_peak"]))
    if a.csv:
        rows = [dict(kind="fp", **r) for r in res["fp_rows"]] + \
               [dict(kind="peak", **r) for r in res["peak_rows"]]
        keys = sorted({k for r in rows for k in r})
        with open(a.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
