"""
metrics/h3_offline_map.py — offline coverage map "speed x sigma_GNSS" for
the ranging detector (review stage 5, step 4).

Rules: H3_PREREGISTRATION.md, section "Offline coverage map", and
Amendment A1 (2026-09-28, committed before this code and before any map
number). Item numbers below refer to A1.

What is replayed
----------------
Input: the S1 flights of runs_h3 (L1 x 5, L3 / L10 / L30 x 2, no-attack
x 3). The mesh announcements are not logged, so they are rebuilt (A1.2):
each UAV's LOCAL_POSITION_NED (N, E, up) is put in the Gazebo world frame
by a per-UAV offset median(truth - belief) over [t0 - 45, t0 - 1] s,
computed on the logged belief before any noise. Announcements: 1 Hz per
UAV, phase U[0, 1) s per (flight, seed, UAV), over [t0 - 45, t0 + W].
The unchanged RangingConsistencyDetector runs in every monitor; its own
position is its aligned belief at the announcement instant.

Noise (A1.3, A1.4): per-UAV north/east Gauss-Markov error, sigma per axis,
tau = 60 s, 0.1 s grid, added to the UAV's announcements and to its own
position; ranges = truth + b + N(0, 0.1^2) + NLOS (p 0.05, Exp mean
0.5 m), n and NLOS per ordered pair. Common random numbers: the same
unit draws are scaled by sigma and shifted by b in every cell, so cells
differ only by sigma and b.

Calibration (A1.5): theta(sigma, b), theta_ok(sigma, b) on the stage-3
set, exactly the [2b] procedure (window [-45, -1] s, gate, alignment,
s(t) = min of 3 consecutive |rho|, theta = ceil_0.1(max s) + 0.5,
theta_ok = ceil_0.1(max s)), 50 seeds, keys "map-cal|...". Evaluation
keys are "map-eval|...". With prefix "cal", 20 seeds, sigma 0, b 0.2 the
same code reproduces the [2b] calibration (scripts/h3_predict_2b.py uses
the same key scheme and draw order).

Metrics (A1.6): t0 = t_target_set (no-attack: inject_start marker),
W = 120 s; t_rng_peer / t_rng_self / t_rng as in metrics.h3_analysis;
harm_at_alarm_m = B0 nav error of uav_0 on the LOGGED belief at t_rng
(median within +-0.25 s). An alarm's time is the announcement instant
that raised it.

Usage (archives unpacked):
    python3 -m metrics.h3_offline_map --h3 runs_h3 --stage3 runs_stage3 --check
    python3 -m metrics.h3_offline_map --h3 runs_h3 --stage3 runs_stage3 --map
--check prints only the replay check (A1.8) and the [2b] reproduction.
--map runs the check first and stops if it fails (no map is produced).
Output JSON goes to the runs_h3 root (h3_map_check.json / h3_map.json).
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import statistics
import sys
import zlib
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from core.events import PeerPositionAnnounce
from detectors.ranging import _EARTH_RADIUS_M, RangingConsistencyDetector
from metrics import h3_analysis as H
from metrics.derived import load_events, load_trajectory
from metrics.physical_outcomes import JUMP_M
from metrics.spoof_rate_probe import nav_error_series, value_at

# --- fixed by the prereg / A1 ------------------------------------------------

UAVS = ("uav_0", "uav_1", "uav_2")
VICTIM = H.VICTIM
SIGMAS = (0.0, 0.5, 1.5, 3.0)          # GNSS sigma per axis, m
BIASES = (0.0, 0.2, 0.4)               # range bias, m
SEEDS = 50
TAU_S = 60.0
GM_DT_S = 0.1
RANGE_SIGMA_M, P_NLOS, M_NLOS = 0.1, 0.05, 0.5
K = 3
MARGIN_M = 0.5
WINDOW_S = H.WINDOW_S                  # 120 s
PRE_S = 45.0                           # replay / FA window starts at t0 - 45 s
CAL_WINDOW = (45.0, 1.0)
ALIGN_WINDOW = (45.0, 1.0)
COVERAGE_MIN = 0.9
PAIR_TOL_S = 0.5
MAX_GAP_S = 0.5                        # truth and own position: no interpolation across
HARM_HALF_S = H.HARM_HALF_S
JUMP_TOL_S = H.JUMP_TOL_S
CAL_PREFIX, EVAL_PREFIX = "map-cal", "map-eval"

S1_CELLS = ("none@detect_only", "L1@detect_only", "L3@detect_only",
            "L10@detect_only", "L30@detect_only")
V0_MPS = {"L1": 1.0, "L3": 3.0, "L10": 10.0, "L30": 30.0}
SLOW, FAST = ("L1", "L3"), ("L10", "L30")

# replay check (A1.8)
CHECK_SIGMA, CHECK_BIAS = 0.0, 0.2
CHECK_THETA, CHECK_THETA_OK = H.THETA_M, H.THETA_OK_M
CHECK_TOL_S = 1.5
CHECK_MIN_SHARE = 0.95
# map predictions (A1.9)
M1_RATIO = (0.8, 1.25)
M2_TOL_M = 0.1
M3_WINDOW_S = (-0.5, 4.0)
M3_MIN_SHARE = 0.95

REF_GEO = (47.397742, 8.545594, 488.0)   # arbitrary; only distances matter

# --- small pure helpers ---------------------------------------------------------


def seeded(*key) -> np.random.Generator:
    """Same scheme as scripts/h3_predict_2b.py."""
    return np.random.default_rng(zlib.crc32("|".join(map(str, key)).encode()))


def range_draws(rng: np.random.Generator, n: int) -> tuple:
    """(normal, nlos) in the [2b] draw order: normal, uniform, exponential."""
    normal = rng.normal(0.0, RANGE_SIGMA_M, n)
    nlos = (rng.random(n) < P_NLOS) * rng.exponential(M_NLOS, n)
    return normal, nlos


def range_noise(draws: tuple, bias: float) -> np.ndarray:
    """b + n + nlos, summed in the [2b] order."""
    normal, nlos = draws
    return (bias + normal) + nlos


def gm_unit(rng: np.random.Generator, n: int, dt: float = GM_DT_S,
            tau: float = TAU_S) -> np.ndarray:
    """(n, 2) first-order Gauss-Markov, unit stationary variance per axis,
    started from the stationary distribution."""
    a = math.exp(-dt / tau)
    c = math.sqrt(1.0 - a * a)
    w = rng.standard_normal((n, 2)).tolist()
    out = np.empty((n, 2))
    xn, xe = w[0]
    out[0] = (xn, xe)
    for k in range(1, n):
        xn = a * xn + c * w[k][0]
        xe = a * xe + c * w[k][1]
        out[k, 0] = xn
        out[k, 1] = xe
    return out


@dataclass
class GmTrack:
    t: np.ndarray
    unit: np.ndarray

    def at(self, t: np.ndarray) -> np.ndarray:
        t = np.asarray(t, dtype=float)
        return np.stack([np.interp(t, self.t, self.unit[:, 0]),
                         np.interp(t, self.t, self.unit[:, 1])], axis=-1)


def gm_track(rng: np.random.Generator, t_start: float, t_end: float,
             dt: float = GM_DT_S, tau: float = TAU_S) -> GmTrack:
    n = int(math.ceil((t_end - t_start) / dt)) + 2
    return GmTrack(t_start + dt * np.arange(n), gm_unit(rng, n, dt, tau))


def interp_gap(a: np.ndarray, t: np.ndarray, max_gap: float) -> np.ndarray:
    """Rows (t, c1..ck) sorted by t -> values at t, NaN where unavailable.
    Same rule as detectors.ranging.interpolate_position: linear if t is
    bracketed by samples at most max_gap apart, else the nearest sample if
    within max_gap, else NaN."""
    t = np.atleast_1d(np.asarray(t, dtype=float))
    k = a.shape[1] - 1
    out = np.full((len(t), k), np.nan)
    if len(a) == 0:
        return out
    ts = a[:, 0]
    hi = np.searchsorted(ts, t, side="left")
    lo = hi - 1
    n = len(ts)
    for q in range(len(t)):
        h, l_ = hi[q], lo[q]
        if h < n and ts[h] == t[q]:
            out[q] = a[h, 1:]
            continue
        if 0 <= l_ and h < n and ts[h] - ts[l_] <= max_gap:
            w = (t[q] - ts[l_]) / (ts[h] - ts[l_])
            out[q] = a[l_, 1:] + w * (a[h, 1:] - a[l_, 1:])
            continue
        near = [i for i in (l_, h) if 0 <= i < n]
        best = min(near, key=lambda i: abs(ts[i] - t[q]))
        if abs(ts[best] - t[q]) <= max_gap:
            out[q] = a[best, 1:]
    return out


def to_geodetic(n: float, e: float, u: float) -> tuple:
    """Local (N, E, up) metres -> (lat, lon, alt) around REF_GEO."""
    lat0, lon0, alt0 = REF_GEO
    lat = lat0 + math.degrees(n / _EARTH_RADIUS_M)
    lon = lon0 + math.degrees(e / (_EARTH_RADIUS_M * math.cos(math.radians(lat0))))
    return lat, lon, alt0 + u


def sustained_min(a: np.ndarray, k: int = K) -> np.ndarray:
    if len(a) < k:
        return np.array([])
    return np.min(np.stack([a[i:len(a) - k + 1 + i] for i in range(k)]), axis=0)


def thresholds_from_max(max_sustained_m: float) -> tuple:
    """(theta, theta_ok) by the [2b] / [2c] rule."""
    base = math.ceil(max_sustained_m * 10 - 1e-9) / 10
    return round(base + MARGIN_M, 1), round(base, 1)


def _q(v: list) -> dict:
    v = [x for x in v if x is not None]
    if not v:
        return {"n": 0, "median": None, "p5": None, "p95": None}
    a = np.asarray(v, dtype=float)
    return {"n": len(v), "median": float(np.median(a)),
            "p5": float(np.percentile(a, 5)), "p95": float(np.percentile(a, 95))}


# --- data ------------------------------------------------------------------------


def _read_jsonl(path: str) -> list:
    out = []
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out


def load_world(run_dir: str) -> tuple:
    """truth {uav: (t, N, E, U)} from Gazebo (x = east, y = north),
    belief {uav: (t, N, E, U)} from LOCAL_POSITION_NED (x = N, y = E, z = down)."""
    tr = {u: [] for u in UAVS}
    for r in _read_jsonl(os.path.join(run_dir, "trajectory.jsonl")):
        if r.get("uav_id") in tr:
            tr[r["uav_id"]].append((r["t_wall"], r["y"], r["x"], r["z"]))
    bel = {}
    for u in UAVS:
        bel[u] = [(r["timestamp"], r["data"]["x"], r["data"]["y"], -r["data"]["z"])
                  for r in _read_jsonl(os.path.join(run_dir, f"telemetry_monitor_{u}.jsonl"))
                  if r.get("msg_type") == "LOCAL_POSITION_NED"]
    as_arr = lambda v: np.array(sorted(v), dtype=float).reshape(-1, 4)
    return ({u: as_arr(tr[u]) for u in UAVS}, {u: as_arr(bel[u]) for u in UAVS})


def coverage_ok(tr: dict, bel: dict, ticks: np.ndarray) -> bool:
    """[2b] gate: truth AND belief within 0.5 s of >= 90 % of the ticks."""
    for u in UAVS:
        for a in (tr[u], bel[u]):
            if len(a) < 2:
                return False
            idx = np.clip(np.searchsorted(a[:, 0], ticks), 1, len(a) - 1)
            near = np.minimum(np.abs(a[idx, 0] - ticks), np.abs(a[idx - 1, 0] - ticks))
            if np.mean(near <= PAIR_TOL_S) < COVERAGE_MIN:
                return False
    return True


def _interp3(a: np.ndarray, t: np.ndarray) -> np.ndarray:
    return np.stack([np.interp(t, a[:, 0], a[:, k]) for k in (1, 2, 3)], axis=-1)


def frame_offset(truth: np.ndarray, belief: np.ndarray, t_from: float,
                 t_to: float) -> Optional[np.ndarray]:
    """median(truth - belief) over the belief samples in [t_from, t_to]."""
    m = (belief[:, 0] >= t_from) & (belief[:, 0] <= t_to)
    if not m.any() or len(truth) < 2:
        return None
    return np.median(_interp3(truth, belief[m, 0]) - belief[m, 1:], axis=0)


@dataclass
class Scene:
    """One calibration flight (stage 3) on 1 Hz ticks."""
    name: str
    ticks: np.ndarray
    b: dict           # aligned belief at ticks, (n, 3) N E U
    x: dict           # truth at ticks


def calibration_scene(run_dir: str):
    """Scene, 'gated', or None (no flight_at_attack / run error)."""
    with open(os.path.join(run_dir, "run_summary.json")) as fh:
        s = json.load(fh)
    if not s.get("flight_at_attack") or s.get("error"):
        return None
    t_inj = s["flight_at_attack"]["t_wall"]
    tr, bel = load_world(run_dir)
    ticks = np.arange(t_inj - CAL_WINDOW[0], t_inj - CAL_WINDOW[1], 1.0)
    if not coverage_ok(tr, bel, ticks):
        return "gated"
    b, x = {}, {}
    for u in UAVS:
        off = frame_offset(tr[u], bel[u], ticks[0], ticks[-1])
        b[u] = _interp3(bel[u], ticks) + off
        x[u] = _interp3(tr[u], ticks)
    return Scene(os.path.basename(run_dir.rstrip("/")), ticks, b, x)


def load_scenes(stage3_root: str) -> tuple:
    runs = sorted(r for r in glob.glob(os.path.join(os.path.expanduser(stage3_root), "run_C_*"))
                  if os.path.exists(os.path.join(r, "trajectory.jsonl")))
    scenes, gated = [], []
    for r in runs:
        sc = calibration_scene(r)
        if sc == "gated":
            gated.append(os.path.basename(r))
        elif sc is not None:
            scenes.append(sc)
    return scenes, gated


@dataclass
class Flight:
    """One S1 flight, ready for replay."""
    run_id: str
    cell: str
    level: Optional[str]          # None for no-attack
    t0: float
    truth: dict                   # {uav: (t, N, E, U)} world frame
    belief: dict                  # {uav: (t, N, E, U)} aligned to world
    navw: list = field(default_factory=list)   # [(t_rel, |e|)] uav_0, B0 def
    t_jump: Optional[float] = None
    live: dict = field(default_factory=dict)


def load_flight(run_dir: str) -> Optional[Flight]:
    """An included S1 flight, or None."""
    with open(os.path.join(run_dir, "run_summary.json")) as fh:
        s = json.load(fh)
    cell = H.cell_of(s)
    if cell not in S1_CELLS:
        return None
    live = H.run_row(run_dir)
    if not live.get("included"):
        return None
    events = load_events(run_dir)
    is_attack = not cell.startswith("none@")
    t0 = (H.gps_evidence(s).get("t_target_set") if is_attack
          else H._marker(events, "inject_start"))
    if t0 is None:
        return None
    tr, bel = load_world(run_dir)
    aligned = {}
    for u in UAVS:
        off = frame_offset(tr[u], bel[u], t0 - ALIGN_WINDOW[0], t0 - ALIGN_WINDOW[1])
        if off is None:
            return None
        a = bel[u].copy()
        a[:, 1:] += off
        aligned[u] = a
    navw, t_jump = [], None
    if is_attack:
        tel = H.load_telemetry(run_dir, VICTIM)
        truth2 = load_trajectory(run_dir).get(VICTIM) or []
        navw = [(t, e) for t, e in nav_error_series(truth2, tel["belief"], t0)
                if 0.0 <= t <= WINDOW_S]
        t_jump = next((t for t, e in navw if e > JUMP_M), None)
    return Flight(live.get("run_id") or os.path.basename(run_dir), cell,
                  cell.split("@")[0] if is_attack else None, float(t0),
                  tr, aligned, navw, t_jump, live)


def load_flights(h3_root: str) -> list:
    dirs = sorted(os.path.join(h3_root, d) for d in os.listdir(h3_root)
                  if d.startswith("run_"))
    return [f for f in (load_flight(d) for d in dirs) if f is not None]


# --- calibration ------------------------------------------------------------------


def calibrate_cells(scenes: list, sigmas=SIGMAS, biases=BIASES, seeds: int = SEEDS,
                    prefix: str = CAL_PREFIX) -> dict:
    """{(sigma, b): max sustained |rho|} over scenes x ordered pairs x seeds."""
    worst = {(s, b): 0.0 for s in sigmas for b in biases}
    noisy = any(s > 0 for s in sigmas)
    for sc in scenes:
        n = len(sc.ticks)
        for sd in range(seeds):
            g = {}
            if noisy:
                for u in UAVS:
                    trk = gm_track(seeded(prefix, sc.name, "gnss", u, sd),
                                   sc.ticks[0] - 1.0, sc.ticks[-1] + 1.0)
                    g[u] = trk.at(sc.ticks)
            for i in UAVS:
                for j in UAVS:
                    if i == j:
                        continue
                    true_r = np.linalg.norm(sc.x[j] - sc.x[i], axis=1)
                    draws = range_draws(seeded(prefix, sc.name, i, j, sd), n)
                    for s in sigmas:
                        bi, bj = sc.b[i], sc.b[j]
                        if s > 0:
                            bi = bi.copy(); bj = bj.copy()
                            bi[:, :2] += s * g[i]
                            bj[:, :2] += s * g[j]
                        implied = np.linalg.norm(bj - bi, axis=1)
                        for b in biases:
                            r = true_r + range_noise(draws, b)
                            m = sustained_min(np.abs(implied - r))
                            if len(m):
                                worst[(s, b)] = max(worst[(s, b)], float(m.max()))
    return worst


def calibration_table(worst: dict) -> dict:
    out = {}
    for (s, b), w in worst.items():
        th, ok = thresholds_from_max(w)
        out[(s, b)] = {"max_sustained_m": w, "theta_m": th, "theta_ok_m": ok}
    return out


# --- replay ---------------------------------------------------------------------------


def announcement_times(t_lo: float, t_hi: float, phase: float) -> np.ndarray:
    ts = t_lo + phase + np.arange(0.0, math.floor(t_hi - t_lo - phase) + 1.0)
    return ts[ts <= t_hi]


def replay(fl: Flight, sigma: float, bias: float, seed: int, theta: float,
           theta_ok: float, prefix: str = EVAL_PREFIX) -> list:
    """Alarms [(t_wall, monitor, target, path)] of one replay."""
    t_lo, t_hi = fl.t0 - PRE_S, fl.t0 + WINDOW_S
    phases = seeded(prefix, fl.run_id, "phase", seed).random(len(UAVS))
    sched = {u: announcement_times(t_lo, t_hi, float(phases[k]))
             for k, u in enumerate(UAVS)}
    gm = {u: gm_track(seeded(prefix, fl.run_id, "gnss", u, seed), t_lo - 1.0, t_hi + 1.0)
          for u in UAVS} if sigma > 0 else {}

    def noisy_pos(u: str, t: np.ndarray) -> np.ndarray:
        p = interp_gap(fl.belief[u], t, MAX_GAP_S)
        if sigma > 0:
            p[:, :2] += sigma * gm[u].at(t)
        return p

    ann = {u: noisy_pos(u, sched[u]) for u in UAVS}
    own, meas = {}, {}
    truth_at = {u: {j: interp_gap(fl.truth[u], sched[j], MAX_GAP_S) for j in UAVS}
                for u in UAVS}
    for i in UAVS:
        for j in UAVS:
            if i == j:
                continue
            own[(i, j)] = noisy_pos(i, sched[j])
            d = np.linalg.norm(truth_at[j][j] - truth_at[i][j], axis=1)
            draws = range_draws(seeded(prefix, fl.run_id, i, j, seed), len(sched[j]))
            meas[(i, j)] = np.maximum(0.0, d + range_noise(draws, bias))  # NaN stays NaN

    current: dict = {}
    dets = {}
    for i in UAVS:
        def fn(peer: str, _t: float, _i: str = i):
            return current.get((_i, peer))
        dets[i] = RangingConsistencyDetector(i, f"monitor_{i}", fn,
                                             theta_m=theta, theta_ok_m=theta_ok)
    order = sorted((float(t), j, k) for j in UAVS for k, t in enumerate(sched[j]))
    alarms = []
    for t, j, k in order:
        p = ann[j][k]
        if not np.all(np.isfinite(p)):
            continue                      # no position -> nothing announced
        lat, lon, alt = to_geodetic(*p)
        msg = PeerPositionAnnounce(source=f"monitor_{j}", uav_id=j, lat=lat,
                                   lon=lon, alt=alt, sample_timestamp=t)
        for i in UAVS:
            if i == j:
                continue
            o = own[(i, j)][k]
            if np.all(np.isfinite(o)):
                dets[i].feed_own_position(*to_geodetic(*o), t)
            r = meas[(i, j)][k]
            current[(i, j)] = float(r) if math.isfinite(r) else None
            for ev in dets[i].feed_peer_position(msg):
                alarms.append((t, i, ev.target_uav, ev.evidence.get("path")))
    return alarms


def replay_metrics(fl: Flight, alarms: list) -> dict:
    rel = [(t - fl.t0, m, tg, p) for t, m, tg, p in alarms]
    if fl.level is None:
        return {"false_alarms": sum(1 for r, *_ in rel if -PRE_S <= r <= WINDOW_S)}
    inw = [a for a in rel if 0.0 <= a[0] <= WINDOW_S]
    peer = min((r for r, m, tg, _ in inw if tg == VICTIM and m != VICTIM), default=None)
    self_ = min((r for r, m, tg, _ in inw if tg == VICTIM and m == VICTIM), default=None)
    got = [x for x in (peer, self_) if x is not None]
    t_rng = min(got) if got else None
    harm = value_at(fl.navw, t_rng, HARM_HALF_S) if t_rng is not None else None
    dj = (t_rng - fl.t_jump) if (t_rng is not None and fl.t_jump is not None) else None
    return {"t_rng_peer_s": peer, "t_rng_self_s": self_, "t_rng_s": t_rng,
            "harm_at_alarm_m": harm,
            "harm_at_peer_alarm_m": (value_at(fl.navw, peer, HARM_HALF_S)
                                     if peer is not None else None),
            "misattributions": sum(1 for _, _, tg, _ in inw if tg != VICTIM),
            "misattr_by_victim_monitor": sum(1 for _, m, tg, _ in inw
                                             if tg != VICTIM and m == VICTIM),
            "alarms_before_t0": sum(1 for r, *_ in rel if r < 0.0),
            "t_rng_minus_jump_s": dj}


def run_cell(flights: list, sigma: float, bias: float, theta: float,
             theta_ok: float, seeds: int = SEEDS) -> list:
    out = []
    for fl in flights:
        for sd in range(seeds):
            m = replay_metrics(fl, replay(fl, sigma, bias, sd, theta, theta_ok))
            m.update(run_id=fl.run_id, level=fl.level, seed=sd)
            out.append(m)
    return out


# --- summaries ----------------------------------------------------------------------


def summarize_level(rows: list, level: str) -> dict:
    rr = [r for r in rows if r["level"] == level]
    n = len(rr)
    out = {"v0_mps": V0_MPS.get(level), "n_flights": len({r["run_id"] for r in rr}),
           "n_replays": n,
           "peer_detect_share": (sum(r["t_rng_peer_s"] is not None for r in rr) / n) if n else None,
           "t_rng_s": _q([r["t_rng_s"] for r in rr]),
           "t_rng_peer_s": _q([r["t_rng_peer_s"] for r in rr]),
           "harm_at_alarm_m": _q([r["harm_at_alarm_m"] for r in rr]),
           "misattributions": sum(r["misattributions"] for r in rr),
           "misattr_by_victim_monitor": sum(r["misattr_by_victim_monitor"] for r in rr),
           "alarms_before_t0": sum(r["alarms_before_t0"] for r in rr)}
    dj = [r["t_rng_minus_jump_s"] for r in rr]
    out["n_before_jump"] = sum(1 for d in dj if d is not None and d < -JUMP_TOL_S)
    out["share_in_jump_window"] = (sum(1 for d in dj if d is not None
                                       and M3_WINDOW_S[0] <= d <= M3_WINDOW_S[1]) / n) if n else None
    return out


def false_alarm_rate(rows: list) -> dict:
    rr = [r for r in rows if r["level"] is None]
    count = sum(r["false_alarms"] for r in rr)
    hours = len(rr) * (PRE_S + WINDOW_S) / 3600.0
    return {"replays": len(rr), "alarms": count, "exposure_h": hours,
            "per_flight_hour": (count / hours) if hours else None,
            "upper95_per_flight_hour": (3.0 / hours) if (hours and count == 0) else None}


def summarize_cell(rows: list) -> dict:
    return {"levels": {lv: summarize_level(rows, lv) for lv in V0_MPS},
            "false_alarms": false_alarm_rate(rows)}


# --- replay check (A1.8) -------------------------------------------------------------


def check_verdict(per_flight: list, false_alarms: int) -> str:
    """per_flight: [{'share': .., 'median_t_peer': .., 'live_t_peer': ..}] of attack flights."""
    if false_alarms > 0:
        return "FAIL"
    for f in per_flight:
        if f["share"] is None or f["share"] < CHECK_MIN_SHARE:
            return "FAIL"
        if f["median_t_peer"] is None or f["live_t_peer"] is None:
            return "FAIL"
        if abs(f["median_t_peer"] - f["live_t_peer"]) > CHECK_TOL_S:
            return "FAIL"
    return "PASS"


def replay_check(flights: list, seeds: int = SEEDS) -> dict:
    rows = run_cell(flights, CHECK_SIGMA, CHECK_BIAS, CHECK_THETA, CHECK_THETA_OK, seeds)
    per = []
    for fl in flights:
        if fl.level is None:
            continue
        rr = [r for r in rows if r["run_id"] == fl.run_id]
        tp = [r["t_rng_peer_s"] for r in rr if r["t_rng_peer_s"] is not None]
        ts = [r["t_rng_self_s"] for r in rr if r["t_rng_self_s"] is not None]
        per.append({"run_id": fl.run_id, "level": fl.level,
                    "share": len(tp) / len(rr) if rr else None,
                    "median_t_peer": statistics.median(tp) if tp else None,
                    "live_t_peer": fl.live.get("t_rng_peer_s"),
                    "median_t_self": statistics.median(ts) if ts else None,
                    "live_t_self": fl.live.get("t_rng_self_s"),
                    "misattributions": sum(r["misattributions"] for r in rr)})
    fa = false_alarm_rate(rows)
    return {"verdict": check_verdict(per, fa["alarms"]), "flights": per,
            "false_alarms": fa, "sigma": CHECK_SIGMA, "bias": CHECK_BIAS,
            "theta_m": CHECK_THETA, "theta_ok_m": CHECK_THETA_OK, "seeds": seeds,
            "n_flights": len(flights)}


# --- map predictions (A1.9) ------------------------------------------------------------


def _harm_med(cells: dict, s: float, b: float, lv: str) -> Optional[float]:
    return cells[(s, b)]["levels"][lv]["harm_at_alarm_m"]["median"]


def eval_m1(cells: dict) -> dict:
    per = {}
    for (s, b) in cells:
        h1, h3 = _harm_med(cells, s, b, "L1"), _harm_med(cells, s, b, "L3")
        ratio = (h3 / h1) if (h1 and h3 is not None) else None
        per[f"{s}|{b}"] = {"ratio_L3_L1": ratio,
                           "holds": ratio is not None and M1_RATIO[0] <= ratio <= M1_RATIO[1]}
    return {"holds": all(v["holds"] for v in per.values()), "cells": per}


def eval_m2(cells: dict) -> dict:
    sig = sorted({s for s, _ in cells})
    per = {}
    for lv in SLOW:
        for b in sorted({b for _, b in cells}):
            seq = [_harm_med(cells, s, b, lv) for s in sig]
            ok = all(x is not None for x in seq) and all(
                seq[k + 1] >= seq[k] - M2_TOL_M for k in range(len(seq) - 1))
            per[f"{lv}|{b}"] = {"harm_by_sigma": seq, "holds": ok}
    return {"holds": all(v["holds"] for v in per.values()), "sigmas": sig, "cells": per}


def eval_m3(cells: dict) -> dict:
    per = {}
    for (s, b), c in cells.items():
        for lv in FAST:
            L = c["levels"][lv]
            ok = (L["n_before_jump"] == 0 and L["share_in_jump_window"] is not None
                  and L["share_in_jump_window"] >= M3_MIN_SHARE)
            per[f"{s}|{b}|{lv}"] = {"n_before_jump": L["n_before_jump"],
                                    "share_in_window": L["share_in_jump_window"],
                                    "holds": ok}
    return {"holds": all(v["holds"] for v in per.values()), "cells": per}


# --- CLI ------------------------------------------------------------------------------------


def _fmt(x, nd=2):
    return "-" if x is None else f"{x:.{nd}f}"


def _print_check(chk: dict) -> None:
    print(f"REPLAY CHECK (A1.8): {chk['verdict']}  sigma {chk['sigma']}, b {chk['bias']}, "
          f"theta {chk['theta_m']} / {chk['theta_ok_m']}, seeds {chk['seeds']}")
    print("  flight                                   share  t_peer(off/live)  t_self(off/live)  misattr")
    for f in chk["flights"]:
        print(f"  {f['run_id'][:40]:40s} {_fmt(f['share'])}  {_fmt(f['median_t_peer'])} / "
              f"{_fmt(f['live_t_peer'])}      {_fmt(f['median_t_self'])} / {_fmt(f['live_t_self'])}"
              f"      {f['misattributions']}")
    fa = chk["false_alarms"]
    print(f"  no-attack: {fa['alarms']} alarms in {fa['replays']} replays ({fa['exposure_h']:.1f} h)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h3", required=True, help="runs_h3 root")
    ap.add_argument("--stage3", required=True, help="runs_stage3 root")
    ap.add_argument("--seeds", type=int, default=SEEDS)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--map", action="store_true")
    a = ap.parse_args(argv)

    flights = load_flights(a.h3)
    cells_found = sorted({f.cell for f in flights})
    print(f"S1 flights: {len(flights)} ({', '.join(cells_found)})", file=sys.stderr)
    chk = replay_check(flights, a.seeds)
    scenes, gated = load_scenes(a.stage3)
    repro = calibration_table(calibrate_cells(scenes, (0.0,), (0.2,), 20, prefix="cal"))[(0.0, 0.2)]
    chk["repro_2b"] = {"runs": len(scenes), "gated": gated, **repro}
    _print_check(chk)
    print(f"[2b] reproduction (implementation check, not an A1 criterion): runs {len(scenes)}, "
          f"gated {len(gated)}, max sustained {repro['max_sustained_m']:.3f} m -> "
          f"theta {repro['theta_m']} / theta_ok {repro['theta_ok_m']} (frozen: 1.8 / 1.3)")
    if a.check:
        with open(os.path.join(a.h3, "h3_map_check.json"), "w") as fh:
            json.dump(chk, fh, indent=1, default=str)
        return 0
    if chk["verdict"] != "PASS":
        print("Replay check FAILED: no map is produced (A1.8).")
        return 1

    cal = calibration_table(calibrate_cells(scenes, SIGMAS, BIASES, a.seeds))
    cells = {}
    for (s, b), c in sorted(cal.items()):
        print(f"cell sigma {s}, b {b}: theta {c['theta_m']} / {c['theta_ok_m']} ...", file=sys.stderr)
        rows = run_cell(flights, s, b, c["theta_m"], c["theta_ok_m"], a.seeds)
        cells[(s, b)] = {**summarize_cell(rows), "calibration": c}
    res = {"check": chk, "cells": {f"{s}|{b}": v for (s, b), v in cells.items()},
           "M1": eval_m1(cells), "M2": eval_m2(cells), "M3": eval_m3(cells),
           "constants": {"sigmas": SIGMAS, "biases": BIASES, "seeds": a.seeds,
                         "tau_s": TAU_S, "window_s": WINDOW_S, "pre_s": PRE_S}}
    with open(os.path.join(a.h3, "h3_map.json"), "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    print("sigma  b    theta | v0  detect  t_rng med  harm med (p5-p95)  misattr | FA/h")
    for (s, b), c in sorted(cells.items()):
        fa = c["false_alarms"]
        for lv in V0_MPS:
            L = c["levels"][lv]
            h = L["harm_at_alarm_m"]
            print(f"{s:4.1f} {b:4.1f}  {c['calibration']['theta_m']:4.1f} | {L['v0_mps']:4.0f}  "
                  f"{_fmt(L['peer_detect_share'])}   {_fmt(L['t_rng_s']['median'], 1):>6s}   "
                  f"{_fmt(h['median'])} ({_fmt(h['p5'])}-{_fmt(h['p95'])})  {L['misattributions']:4d} | "
                  f"{_fmt(fa['per_flight_hour'])}")
    for m in ("M1", "M2", "M3"):
        print(f"{m}: {'HOLDS' if res[m]['holds'] else 'NOT MET'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
