"""
Inter-UAV range source for the ranging detector (B1; H3_PREREGISTRATION.md,
"Range source").

Seam
----
`RangeSource.range_m(from_uav, to_uav, t)` returns the range that
`from_uav` measures to `to_uav` at wall-clock time t, in metres, or None
when no measurement is available. The detector sees it through
`range_fn_for(source, monitor_uav_id)`, which binds the measuring UAV.
A real radio (UWB) would implement the same method.

Simulated UWB (live flights)
----------------------------
    r_ij = |x_i - x_j|_truth + b + n + nlos

  x      Gazebo ground truth (TrajectoryRecorder's feed, `on_sample`),
         interpolated to t; no interpolation across gaps > max_gap_s
  b      fixed bias per flight, default 0.2 m
  n      N(0, sigma^2), sigma = 0.1 m
  nlos   with probability p_nlos = 0.05, an Exp(mean m_nlos = 0.5 m)
         positive excess

The noise is a pure function of (seed, from_uav, to_uav, t in ms): it
does not depend on call order or threads, and it can be recomputed
offline from the logged seed and timestamps. Each ordered pair has its
own noise (each monitor measures for itself), as in scripts/h3_predict_2c.py.
The attacker does not control r (adversary model).

Frames: Gazebo world coordinates, metres; a distance does not depend on
the axis convention.
"""

from __future__ import annotations

import math
import random
import threading
from typing import Optional, Protocol

from detectors.ranging import PositionSample, RangeFn, interpolate_position


class RangeSource(Protocol):
    def range_m(self, from_uav: str, to_uav: str, t: float) -> Optional[float]:
        """Range measured by from_uav to to_uav at time t, or None."""


def range_fn_for(source: RangeSource, monitor_uav_id: str) -> RangeFn:
    """Bind the measuring UAV: (peer, t) -> range, for the detector."""
    def fn(peer_uav_id: str, t: float) -> Optional[float]:
        return source.range_m(monitor_uav_id, peer_uav_id, t)
    return fn


def uwb_noise_m(
    seed: int, from_uav: str, to_uav: str, t: float, *,
    sigma_m: float, bias_m: float, p_nlos: float, m_nlos: float,
) -> float:
    """Deterministic noise b + n + nlos for one measurement (metres)."""
    rng = random.Random(f"{seed}|{from_uav}|{to_uav}|{int(round(t * 1000))}")
    n = rng.gauss(0.0, sigma_m) if sigma_m > 0 else 0.0
    nlos = 0.0
    if rng.random() < p_nlos and m_nlos > 0:
        nlos = rng.expovariate(1.0 / m_nlos)
    return bias_m + n + nlos


class TruthBuffer:
    """Thread-safe recent ground-truth positions per UAV (world frame, m).

    Fed by TrajectoryRecorder(on_sample=buffer.add); read by the range
    source from the monitors' threads.
    """

    DEFAULT_HISTORY_S: float = 10.0

    def __init__(self, history_s: float = DEFAULT_HISTORY_S) -> None:
        if history_s <= 0:
            raise ValueError("history_s must be positive")
        self._history_s = float(history_s)
        self._lock = threading.Lock()
        self._tracks: dict[str, list[PositionSample]] = {}

    def add(self, uav_id: str, t: float, x: float, y: float, z: float) -> None:
        rec = (float(t), float(x), float(y), float(z))
        with self._lock:
            s = self._tracks.setdefault(uav_id, [])
            if not s or rec[0] >= s[-1][0]:
                s.append(rec)
            else:
                s.append(rec)
                s.sort(key=lambda r: r[0])
            cutoff = s[-1][0] - self._history_s
            i = 0
            while i < len(s) and s[i][0] < cutoff:
                i += 1
            if i:
                del s[:i]

    def position_at(
        self, uav_id: str, t: float, max_gap_s: float
    ) -> Optional[tuple[float, float, float]]:
        with self._lock:
            s = list(self._tracks.get(uav_id, ()))
        return interpolate_position(s, t, max_gap_s)


class SimulatedUwbRangeSource:
    """Gazebo truth + UWB error model (H3 "Range source")."""

    DEFAULT_SIGMA_M: float = 0.1
    DEFAULT_BIAS_M: float = 0.2
    DEFAULT_P_NLOS: float = 0.05
    DEFAULT_M_NLOS: float = 0.5
    DEFAULT_MAX_GAP_S: float = 0.5

    def __init__(
        self,
        truth: TruthBuffer,
        seed: int,
        *,
        sigma_m: float = DEFAULT_SIGMA_M,
        bias_m: float = DEFAULT_BIAS_M,
        p_nlos: float = DEFAULT_P_NLOS,
        m_nlos: float = DEFAULT_M_NLOS,
        max_gap_s: float = DEFAULT_MAX_GAP_S,
    ) -> None:
        if sigma_m < 0 or m_nlos < 0:
            raise ValueError("sigma_m and m_nlos must be non-negative")
        if not 0.0 <= p_nlos <= 1.0:
            raise ValueError("p_nlos must be in [0, 1]")
        if max_gap_s <= 0:
            raise ValueError("max_gap_s must be positive")
        self._truth = truth
        self._seed = int(seed)
        self._sigma_m = float(sigma_m)
        self._bias_m = float(bias_m)
        self._p_nlos = float(p_nlos)
        self._m_nlos = float(m_nlos)
        self._max_gap_s = float(max_gap_s)

    def describe(self) -> dict:
        """Parameters and seed, for run_summary.json."""
        return {"model": "simulated_uwb", "seed": self._seed,
                "sigma_m": self._sigma_m, "bias_m": self._bias_m,
                "p_nlos": self._p_nlos, "m_nlos": self._m_nlos,
                "max_gap_s": self._max_gap_s}

    def true_range_m(self, a: str, b: str, t: float) -> Optional[float]:
        pa = self._truth.position_at(a, t, self._max_gap_s)
        pb = self._truth.position_at(b, t, self._max_gap_s)
        if pa is None or pb is None:
            return None
        return math.dist(pa, pb)

    def range_m(self, from_uav: str, to_uav: str, t: float) -> Optional[float]:
        if from_uav == to_uav:
            return None
        true_r = self.true_range_m(from_uav, to_uav, t)
        if true_r is None:
            return None
        r = true_r + uwb_noise_m(
            self._seed, from_uav, to_uav, t, sigma_m=self._sigma_m,
            bias_m=self._bias_m, p_nlos=self._p_nlos, m_nlos=self._m_nlos)
        return max(0.0, r)
