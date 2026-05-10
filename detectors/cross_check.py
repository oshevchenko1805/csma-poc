"""
CrossCheckDetector — kinematic feasibility check on peer position
announcements.

This is the architecture-C-only detector and the value-add that makes
CSMA different from the segmented baseline. The story is:

    UAV-2's GPS is being slowly spoofed. The drift is below the
    threshold of UAV-2's local EKF residual detector (or has not yet
    accumulated to it). UAV-2 announces its (spoofed) position on the
    mesh. UAV-0 has UAV-2's previous announcement from N seconds ago
    and computes the great-circle distance: 80 metres in 4 seconds.
    No multirotor in this fleet can do 20 m/s. UAV-0 raises a
    SecurityEvent against UAV-2 — independently of UAV-2's own
    detectors.

Approach
--------
Per-peer kinematic check using haversine distance and a configurable
maximum velocity. Architecture-only — relies on the mesh transport.

This detector deliberately does NOT inherit from Detector. The base
class contract is "consume TelemetryEvent". Cross-check consumes
PeerPositionAnnounce from the mesh, which is a different semantic
channel. Forcing both into one interface would obscure the real
distinction. Architecture C's monitor instantiates a CrossCheckDetector
in addition to its TelemetryEvent-driven Detectors and routes mesh
messages to it explicitly.

Operational notes (Chapter 4)
-----------------------------
- max_velocity_mps must be set above the actual fleet maximum (with a
  margin) to avoid baseline false positives. For PX4 X500 multirotor
  in SITL, 25 m/s is generous (cruise is ~12 m/s).
- position_error_margin_m absorbs one-shot GPS jitter. SITL GPS noise
  is typically <5 m; we use 10 m as a safe baseline.
- The detector only fires when at least *two* announcements from a peer
  have been observed (it needs a baseline to compute Δposition). A
  spoofer who flips coordinates on the very first announcement is not
  caught by this detector — it would be caught by the peer's own EKF
  residual detector (rapid jump fails PX4's outlier rejection).
- Every announcement updates the stored last-known position regardless
  of whether the kinematic check passed. Otherwise a slow drift would
  evade detection by always being compared against the very first
  observation. This is the standard and correct approach.

Hysteresis
----------
Per-peer alarmed flag: one SecurityEvent per detection cycle per peer.
When a subsequent announcement is kinematically consistent again, the
flag clears for that peer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from core.events import PeerPositionAnnounce, SecurityEvent


@dataclass
class _PeerState:
    """Last-known position and hysteresis flag for one peer."""
    lat: float
    lon: float
    alt: float
    sample_timestamp: float
    alerted: bool = False


# Earth's mean radius in metres. Standard value for haversine distance.
_EARTH_RADIUS_M: float = 6_371_000.0


def haversine_distance_m(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """
    Great-circle distance between two GPS coordinates, in metres.

    Pure function so it can be unit-tested independently of the detector.
    Accuracy is sub-metre over multi-kilometre distances on Earth — more
    than enough for our purposes.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


class CrossCheckDetector:
    """Kinematic feasibility check on peer-position mesh announcements."""

    DEFAULT_MAX_VELOCITY_MPS: float = 25.0
    DEFAULT_POSITION_ERROR_MARGIN_M: float = 10.0
    DEFAULT_MIN_DT_SEC: float = 0.1
    DEFAULT_SEVERITY: str = "high"

    def __init__(
        self,
        monitor_uav_id: str,
        source: str,
        *,
        max_velocity_mps: float = DEFAULT_MAX_VELOCITY_MPS,
        position_error_margin_m: float = DEFAULT_POSITION_ERROR_MARGIN_M,
        min_dt_sec: float = DEFAULT_MIN_DT_SEC,
        severity: str = DEFAULT_SEVERITY,
    ) -> None:
        if max_velocity_mps <= 0:
            raise ValueError("max_velocity_mps must be positive")
        if position_error_margin_m < 0:
            raise ValueError("position_error_margin_m must be non-negative")
        if min_dt_sec <= 0:
            raise ValueError("min_dt_sec must be positive")

        self._monitor_uav_id = monitor_uav_id
        self._source = source
        self._max_velocity_mps = float(max_velocity_mps)
        self._position_error_margin_m = float(position_error_margin_m)
        self._min_dt_sec = float(min_dt_sec)
        self._severity = severity

        self._peers: dict[str, _PeerState] = {}

    # ----- diagnostics -----

    @property
    def name(self) -> str:
        return "cross_check"

    @property
    def monitor_uav_id(self) -> str:
        return self._monitor_uav_id

    def is_alerted(self, peer_uav_id: str) -> bool:
        state = self._peers.get(peer_uav_id)
        return state.alerted if state else False

    # ----- main entry point -----

    def feed_peer_position(
        self, ann: PeerPositionAnnounce
    ) -> Optional[SecurityEvent]:
        """Consume a peer-position announcement and possibly alarm."""

        # Skip self-announcements: a monitor publishes its own UAV's
        # position and also receives it back via the mesh broadcast.
        if ann.uav_id == self._monitor_uav_id:
            return None
        if not ann.uav_id:
            return None

        prev = self._peers.get(ann.uav_id)

        # First time we hear from this peer — store baseline, no check yet.
        if prev is None:
            self._peers[ann.uav_id] = _PeerState(
                lat=ann.lat,
                lon=ann.lon,
                alt=ann.alt,
                sample_timestamp=ann.sample_timestamp,
            )
            return None

        dt = ann.sample_timestamp - prev.sample_timestamp

        # Stale or out-of-order announcement: don't crash, don't alarm,
        # but also don't update state — we want to compare against the
        # most recent good baseline.
        if dt < self._min_dt_sec:
            return None

        distance_m = haversine_distance_m(
            prev.lat, prev.lon, ann.lat, ann.lon
        )
        max_allowed_m = self._max_velocity_mps * dt + self._position_error_margin_m

        # Snapshot baseline BEFORE updating, so the evidence dict reflects
        # the actual jump.
        previous_lat = prev.lat
        previous_lon = prev.lon

        # Always update last-known *before* deciding hysteresis, so a
        # gradual drift that stays within budget still updates the
        # baseline rather than locking us to a stale starting point.
        prev_alerted = prev.alerted
        prev.lat = ann.lat
        prev.lon = ann.lon
        prev.alt = ann.alt
        prev.sample_timestamp = ann.sample_timestamp

        if distance_m > max_allowed_m:
            if prev_alerted:
                return None  # hysteresis
            prev.alerted = True
            return SecurityEvent(
                source=self._source,
                detector=self.name,
                target_uav=ann.uav_id,
                severity=self._severity,
                evidence={
                    "distance_m": distance_m,
                    "max_allowed_m": max_allowed_m,
                    "dt_sec": dt,
                    "max_velocity_mps": self._max_velocity_mps,
                    "position_error_margin_m": self._position_error_margin_m,
                    "previous_lat": previous_lat,
                    "previous_lon": previous_lon,
                    "current_lat": ann.lat,
                    "current_lon": ann.lon,
                },
            )

        # Movement plausible — clear hysteresis if it was set.
        if prev_alerted:
            prev.alerted = False
        return None

    def reset(self) -> None:
        """Clear all per-peer state. Called between experiment runs."""
        self._peers.clear()
