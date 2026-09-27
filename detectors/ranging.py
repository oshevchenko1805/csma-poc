"""
RangingConsistencyDetector — inter-UAV range vs the range implied by the
mesh position announcements (B1; H3_PREREGISTRATION.md).

Per monitor i, on each announcement of peer j (the existing 1 Hz mesh
cadence, no new messages):

    rho_ij = | p_j - p_i |  -  r_ij          (3D, metres)

  p_j   position announced by j (its EKF estimate, GLOBAL_POSITION_INT)
  p_i   i's own EKF position, interpolated to the announcement's
        sample_timestamp (no interpolation across gaps)
  r_ij  range measured by i at the same timestamp (range function,
        injected; the simulated UWB source is a separate seam)

Pair states (K = 3 consecutive announcements of that pair):
  bad_ij    |rho_ij| >  theta      K times in a row   (theta    = 1.8 m, [2b])
  fine_ij   |rho_ij| <= theta_ok   K times in a row   (theta_ok = 1.3 m, [2c])

Attribution over the pairs heard recently (the residual is symmetric: it
cannot say which end is wrong):
  every heard pair bad (>= 2 peers)   -> flag i itself   (self path)
  pair ij bad and some pair ik fine   -> flag j          (peer path)
  a single heard pair                 -> no flag (ambiguous)
  latch: once i has flagged itself, it flags no peer until reset(),
         because every peer judgement it could make uses its own,
         now known-tainted, position.

Like CrossCheckDetector, this does not inherit from Detector: it consumes
PeerPositionAnnounce from the mesh plus the host monitor's own position,
not TelemetryEvent. Enabled by configuration only; v1 never builds it.

Known limit (stated in H3 [2c]): before its self flag, the victim's own
monitor may still see "bad with one peer, fine with the other" when its
error is perpendicular to the second line of sight, and then flags an
honest peer. The rule reduces this; it cannot remove it with 3 UAVs.

Hysteresis: one SecurityEvent per target per detection cycle; the flag
for a target clears when an evaluation no longer flags it.

Data gaps: if p_i or r_ij is unavailable for an announcement, that
pair's streaks are reset and the pair counts as not heard until its next
evaluated announcement (no evidence from non-consecutive samples); no
attribution is evaluated on that announcement.

Health counters (stats; setup diagnostics, not outcomes): per peer
announcement from another UAV, `evaluated` if a residual was computed;
otherwise `no_own_position` if p_i was unavailable and/or `no_range` if
r_ij was None or not finite (independent: one skipped announcement can
count in both). Cumulative over the detector's life; reset() keeps them.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Sequence

from core.events import PeerPositionAnnounce, SecurityEvent

# (lat_deg, lon_deg, alt_m)
Geodetic = tuple[float, float, float]
# (sample_ts, lat_deg, lon_deg, alt_m)
PositionSample = tuple[float, float, float, float]
# (peer_uav_id, t) -> range measured by this monitor, metres, or None
RangeFn = Callable[[str, float], Optional[float]]

_EARTH_RADIUS_M: float = 6_371_000.0


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def local_offset_m(ref: Geodetic, p: Geodetic) -> tuple[float, float, float]:
    """(east, north, up) of p relative to ref, metres.

    Local tangent-plane (equirectangular) approximation; the error is
    negligible at inter-UAV scales (tens of metres).
    """
    lat0, lon0, alt0 = ref
    lat, lon, alt = p
    north = math.radians(lat - lat0) * _EARTH_RADIUS_M
    east = (math.radians(lon - lon0) * _EARTH_RADIUS_M
            * math.cos(math.radians((lat + lat0) / 2.0)))
    return east, north, alt - alt0


def distance_3d_m(a: Geodetic, b: Geodetic) -> float:
    """3D distance between two geodetic points, metres."""
    e, n, u = local_offset_m(a, b)
    return math.sqrt(e * e + n * n + u * u)


def interpolate_position(
    samples: Sequence[PositionSample], t: float, max_gap_s: float
) -> Optional[Geodetic]:
    """Own position at time t from time-sorted samples.

    Linear interpolation if t is bracketed by two samples at most
    max_gap_s apart; otherwise the nearest sample if it is within
    max_gap_s of t; otherwise None. Never interpolates across a gap.
    """
    if not samples:
        return None
    times = [s[0] for s in samples]
    hi = bisect.bisect_left(times, t)
    if hi < len(samples) and times[hi] == t:
        return samples[hi][1:]
    lo = hi - 1
    if 0 <= lo and hi < len(samples) and times[hi] - times[lo] <= max_gap_s:
        w = (t - times[lo]) / (times[hi] - times[lo])
        a, b = samples[lo], samples[hi]
        return (a[1] + w * (b[1] - a[1]),
                a[2] + w * (b[2] - a[2]),
                a[3] + w * (b[3] - a[3]))
    near = [i for i in (lo, hi) if 0 <= i < len(samples)]
    best = min(near, key=lambda i: abs(times[i] - t))
    if abs(times[best] - t) <= max_gap_s:
        return samples[best][1:]
    return None


def residual_m(implied_m: float, measured_m: float) -> float:
    """rho = implied range - measured range (signed, metres)."""
    return implied_m - measured_m


def next_streaks(
    bad_streak: int, fine_streak: int, abs_rho: float,
    theta_m: float, theta_ok_m: float,
) -> tuple[int, int]:
    """Update the (bad, fine) consecutive counts with one |rho|."""
    bad = bad_streak + 1 if abs_rho > theta_m else 0
    fine = fine_streak + 1 if abs_rho <= theta_ok_m else 0
    return bad, fine


@dataclass(frozen=True)
class PairStatus:
    bad: bool
    fine: bool


def attribute(
    monitor_uav_id: str,
    heard: Mapping[str, PairStatus],
    self_latched: bool = False,
) -> frozenset[str]:
    """Which UAVs monitor i flags, given the status of every heard pair.

    Self path: every heard pair bad, at least 2 peers -> {monitor}.
    Peer path: pair ij bad and some other pair ik fine -> j.
    Latch: after a self flag, no peer is flagged.
    """
    if len(heard) >= 2 and all(s.bad for s in heard.values()):
        return frozenset({monitor_uav_id})
    if self_latched:
        return frozenset()
    flagged = set()
    for j, sj in heard.items():
        if sj.bad and any(sk.fine for k, sk in heard.items() if k != j):
            flagged.add(j)
    return frozenset(flagged)


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


@dataclass
class _PairState:
    bad_streak: int = 0
    fine_streak: int = 0
    last_eval_ts: Optional[float] = None
    last_rho_m: Optional[float] = None
    last_implied_m: Optional[float] = None
    last_measured_m: Optional[float] = None

    def drop(self) -> None:
        self.bad_streak = 0
        self.fine_streak = 0
        self.last_eval_ts = None


@dataclass
class _OwnTrack:
    samples: list[PositionSample] = field(default_factory=list)


class RangingConsistencyDetector:
    """Range-consistency check between this monitor's UAV and its peers."""

    DEFAULT_THETA_M: float = 1.8        # H3 [2b]
    DEFAULT_THETA_OK_M: float = 1.3     # H3 [2c]
    DEFAULT_SUSTAIN: int = 3            # H3: k = 3 consecutive announcements
    DEFAULT_OWN_MAX_GAP_S: float = 0.5  # H3 data-quality gate
    DEFAULT_OWN_HISTORY_S: float = 5.0
    DEFAULT_STALE_AFTER_S: float = 2.5  # 2.5 announcement periods at 1 Hz
    DEFAULT_SEVERITY: str = "high"

    def __init__(
        self,
        monitor_uav_id: str,
        source: str,
        range_fn: RangeFn,
        *,
        theta_m: float = DEFAULT_THETA_M,
        theta_ok_m: float = DEFAULT_THETA_OK_M,
        sustain: int = DEFAULT_SUSTAIN,
        own_max_gap_s: float = DEFAULT_OWN_MAX_GAP_S,
        own_history_s: float = DEFAULT_OWN_HISTORY_S,
        stale_after_s: float = DEFAULT_STALE_AFTER_S,
        severity: str = DEFAULT_SEVERITY,
    ) -> None:
        if not monitor_uav_id:
            raise ValueError("monitor_uav_id must be non-empty")
        if not callable(range_fn):
            raise ValueError("range_fn must be callable")
        if theta_m <= 0:
            raise ValueError("theta_m must be positive")
        if not 0 < theta_ok_m <= theta_m:
            raise ValueError("theta_ok_m must be in (0, theta_m]")
        if sustain < 1:
            raise ValueError("sustain must be >= 1")
        for nm, v in (("own_max_gap_s", own_max_gap_s),
                      ("own_history_s", own_history_s),
                      ("stale_after_s", stale_after_s)):
            if v <= 0:
                raise ValueError(f"{nm} must be positive")

        self._monitor_uav_id = monitor_uav_id
        self._source = source
        self._range_fn = range_fn
        self._theta_m = float(theta_m)
        self._theta_ok_m = float(theta_ok_m)
        self._sustain = int(sustain)
        self._own_max_gap_s = float(own_max_gap_s)
        self._own_history_s = float(own_history_s)
        self._stale_after_s = float(stale_after_s)
        self._severity = severity

        self._own = _OwnTrack()
        self._pairs: dict[str, _PairState] = {}
        self._alerted: set[str] = set()
        self._self_latched = False

        # Health counters (not outcomes; see module docstring).
        self._n_evaluated: int = 0
        self._n_no_own_position: int = 0
        self._n_no_range: int = 0

    # ----- diagnostics -----

    @property
    def stats(self) -> dict[str, int]:
        return {
            "evaluated": self._n_evaluated,
            "no_own_position": self._n_no_own_position,
            "no_range": self._n_no_range,
        }

    @property
    def name(self) -> str:
        return "ranging"

    @property
    def monitor_uav_id(self) -> str:
        return self._monitor_uav_id

    @property
    def self_latched(self) -> bool:
        return self._self_latched

    def is_alerted(self, uav_id: str) -> bool:
        return uav_id in self._alerted

    # ----- inputs -----

    def feed_own_position(
        self, lat: float, lon: float, alt: float, sample_ts: float
    ) -> None:
        """Record one own EKF position sample (GLOBAL_POSITION_INT)."""
        s = self._own.samples
        rec = (float(sample_ts), float(lat), float(lon), float(alt))
        if not s or rec[0] >= s[-1][0]:
            s.append(rec)
        else:
            bisect.insort(s, rec)
        cutoff = s[-1][0] - self._own_history_s
        drop = bisect.bisect_left([x[0] for x in s], cutoff)
        if drop:
            del s[:drop]

    def feed_peer_position(
        self, ann: PeerPositionAnnounce
    ) -> list[SecurityEvent]:
        """Consume a peer announcement; return the SecurityEvents raised."""
        if not ann.uav_id or ann.uav_id == self._monitor_uav_id:
            return []
        t = ann.sample_timestamp
        pair = self._pairs.setdefault(ann.uav_id, _PairState())

        own = interpolate_position(self._own.samples, t, self._own_max_gap_s)
        measured = self._range_fn(ann.uav_id, t)
        range_missing = measured is None or not math.isfinite(measured)
        if own is None:
            self._n_no_own_position += 1
        if range_missing:
            self._n_no_range += 1
        if own is None or range_missing:
            pair.drop()
            return []
        self._n_evaluated += 1

        implied = distance_3d_m(own, (ann.lat, ann.lon, ann.alt))
        rho = residual_m(implied, float(measured))
        pair.bad_streak, pair.fine_streak = next_streaks(
            pair.bad_streak, pair.fine_streak, abs(rho),
            self._theta_m, self._theta_ok_m)
        pair.last_eval_ts = t
        pair.last_rho_m = rho
        pair.last_implied_m = implied
        pair.last_measured_m = float(measured)

        heard = {
            j: PairStatus(bad=p.bad_streak >= self._sustain,
                          fine=p.fine_streak >= self._sustain)
            for j, p in self._pairs.items()
            if p.last_eval_ts is not None
            and t - p.last_eval_ts <= self._stale_after_s
        }
        flagged = attribute(self._monitor_uav_id, heard, self._self_latched)
        if self._monitor_uav_id in flagged:
            self._self_latched = True

        events = [self._event(target, ann.uav_id, heard)
                  for target in sorted(flagged - self._alerted)]
        self._alerted = set(flagged)
        return events

    def reset(self) -> None:
        """Clear all state, including the self latch."""
        self._own = _OwnTrack()
        self._pairs.clear()
        self._alerted.clear()
        self._self_latched = False

    # ----- internals -----

    def _event(
        self, target: str, trigger_peer: str, heard: Mapping[str, PairStatus]
    ) -> SecurityEvent:
        path = "self" if target == self._monitor_uav_id else "peer"
        pairs = {
            j: {
                "rho_m": self._pairs[j].last_rho_m,
                "implied_m": self._pairs[j].last_implied_m,
                "measured_m": self._pairs[j].last_measured_m,
                "bad_streak": self._pairs[j].bad_streak,
                "fine_streak": self._pairs[j].fine_streak,
                "bad": heard[j].bad,
                "fine": heard[j].fine,
            }
            for j in sorted(heard)
        }
        return SecurityEvent(
            source=self._source,
            detector=self.name,
            target_uav=target,
            severity=self._severity,
            evidence={
                "path": path,
                "monitor_uav": self._monitor_uav_id,
                "trigger_peer": trigger_peer,
                "theta_m": self._theta_m,
                "theta_ok_m": self._theta_ok_m,
                "sustain": self._sustain,
                "pairs": pairs,
            },
        )
