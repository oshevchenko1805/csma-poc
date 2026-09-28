"""POST-HOC, exploratory (written 2026-09-28, AFTER the offline map).

Not part of the pre-registered H3 decision or of A1. Question: why does
the map's M3 fail (at sigma >= 1.5 m the L10 alarm comes ~11 s after the
EKF jump, not within 4 s), although |belief - truth| of the victim stays
at 31-48 m after the jump?

Noise-free geometry of the ranging residual, per attack flight of S1 and
per peer p (the peer path):

    rho_p(t) = |b_0(t) - b_p(t)| - |x_0(t) - x_p(t)|

b = belief aligned to the world frame (A1.2), x = Gazebo truth. After the
jump the victim's controller brings its ESTIMATE back to the route, so
its TRUE position leaves it: the implied range shrinks back to normal
while the measured one grows. rho changes sign and passes through 0
although |e| stays large. Reported per theta: the zero crossing, the
time |rho| spends at or below theta after first exceeding it (zero
crossing: the first one after the post-jump peak of rho), and the
first time with 3 consecutive 1 Hz ticks (phase 0) above theta.

theta values: the map calibration at b = 0.2 m (h3_map.json):
sigma 0 / 0.5 / 1.5 / 3 m -> 1.8 / 3.8 / 9.1 / 18.2 m.

    python3 scripts/h3_posthoc_m3_residual.py runs_h3
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from metrics import h3_offline_map as M  # noqa: E402

THETAS_M = (1.8, 3.8, 9.1, 18.2)
SPAN_S = (0.0, 40.0)
DT_S = 0.1
PEERS = ("uav_1", "uav_2")


def first_sustained(ticks: np.ndarray, rho: np.ndarray, theta: float,
                    k: int = M.K) -> Optional[float]:
    run = 0
    for t, r in zip(ticks, rho):
        run = run + 1 if (np.isfinite(r) and abs(r) > theta) else 0
        if run >= k:
            return float(t)
    return None


def zero_crossing(t: np.ndarray, rho: np.ndarray, after: float) -> Optional[float]:
    """First sign change of rho between samples both at or after `after`
    (linear interpolation)."""
    for i in range(1, len(t)):
        a, b = rho[i - 1], rho[i]
        if t[i - 1] < after or not (np.isfinite(a) and np.isfinite(b)):
            continue
        if (a > 0 >= b) or (a < 0 <= b):
            return float(t[i - 1] + (t[i] - t[i - 1]) * a / (a - b))
    return None


def time_below_after_exceed(t: np.ndarray, rho: np.ndarray, theta: float,
                            dt: float = DT_S) -> float:
    """Seconds with |rho| <= theta between the first and the last exceedance."""
    above = np.isfinite(rho) & (np.abs(rho) > theta)
    idx = np.flatnonzero(above)
    if len(idx) == 0:
        return 0.0
    seg = ~above[idx[0]:idx[-1] + 1]
    return float(seg.sum() * dt)


def residual(fl: "M.Flight", peer: str, t_rel: np.ndarray) -> np.ndarray:
    t = fl.t0 + t_rel
    b0 = M.interp_gap(fl.belief["uav_0"], t, M.MAX_GAP_S)
    bp = M.interp_gap(fl.belief[peer], t, M.MAX_GAP_S)
    x0 = M.interp_gap(fl.truth["uav_0"], t, M.MAX_GAP_S)
    xp = M.interp_gap(fl.truth[peer], t, M.MAX_GAP_S)
    return np.linalg.norm(b0 - bp, axis=1) - np.linalg.norm(x0 - xp, axis=1)


def rows(root: str, thetas=THETAS_M) -> list:
    out = []
    t_rel = np.arange(SPAN_S[0], SPAN_S[1] + 1e-9, DT_S)
    ticks = np.arange(SPAN_S[0], SPAN_S[1] + 1e-9, 1.0)
    for fl in M.load_flights(root):
        if fl.level is None:
            continue
        for p in PEERS:
            rho = residual(fl, p, t_rel)
            rho_1hz = residual(fl, p, ticks)
            after = 0.0
            if fl.t_jump is not None:            # first zero after the post-jump peak
                w = (t_rel >= fl.t_jump) & (t_rel <= fl.t_jump + 10.0)
                if np.any(np.isfinite(rho[w])):
                    after = float(t_rel[w][np.nanargmax(rho[w])])
            out.append({
                "run_id": fl.run_id, "level": fl.level, "peer": p, "t_jump_s": fl.t_jump,
                "rho_max_m": float(np.nanmax(rho)), "rho_min_m": float(np.nanmin(rho)),
                "t_zero_s": zero_crossing(t_rel, rho, after),
                "per_theta": {th: {"first_sustained_s": first_sustained(ticks, rho_1hz, th),
                                   "below_after_exceed_s": time_below_after_exceed(t_rel, rho, th)}
                              for th in thetas}})
    return out


def _f(x):
    return "-" if x is None else f"{x:5.1f}"


def main(argv: list) -> int:
    root = argv[1] if len(argv) > 1 else "runs_h3"
    print("POST-HOC (exploratory). Noise-free peer-path residual rho(t), 0-40 s after t0.")
    print("level peer   t_jump  rho max/min    t_zero | first 3x>theta (s) for theta "
          + " / ".join(str(t) for t in THETAS_M) + " | below-theta gap (s)")
    for r in rows(root):
        pt = r["per_theta"]
        print(f"{r['level']:<5} {r['peer']} {_f(r['t_jump_s'])}  "
              f"{r['rho_max_m']:6.1f} / {r['rho_min_m']:6.1f}  {_f(r['t_zero_s'])} | "
              + " ".join(_f(pt[t]["first_sustained_s"]) for t in THETAS_M) + " | "
              + " ".join(_f(pt[t]["below_after_exceed_s"]) for t in THETAS_M)
              + f"  {r['run_id'][-14:]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
