"""
HeartbeatDetector — communication disruption detection.

Signature: a UAV stops emitting HEARTBEAT for longer than a configured
timeout. PX4 sends HEARTBEAT at 1 Hz (confirmed empirically), so the
default 3 s timeout corresponds to three missed beats — the standard
choice in MAVLink-based liveness checks.

Behaviour:
    * Until the first HEARTBEAT is observed, no alarm is raised. This
      avoids spurious alerts during startup before the UAV has come up.
    * Once seen, every tick checks `now - last_heartbeat`. If above
      threshold and not already alerted, emit one SecurityEvent and set
      the hysteresis flag.
    * When HEARTBEAT resumes, the flag clears, so a *subsequent* loss
      will fire a fresh SecurityEvent. This matters for runs that span
      multiple disruption-recovery cycles.

Operational model:
    A detector instance observes ONE UAV (target_uav). The host monitor
    routes telemetry to detectors that match the event's uav_id; the
    detector additionally checks defensively. Architecture A places
    three HeartbeatDetector instances on the GS process (one per UAV);
    Architectures B and C place one on each UAV monitor.

Output evidence fields:
    last_heartbeat_ts        wall-clock timestamp of the last HEARTBEAT
    time_since_heartbeat     seconds elapsed at detection time
    timeout_threshold        configured threshold (for reproducibility)
"""

from __future__ import annotations

from typing import Optional

from core.events import SecurityEvent, TelemetryEvent
from detectors.base import Detector


class HeartbeatDetector(Detector):
    """Detect communication disruption via HEARTBEAT timeout."""

    DEFAULT_TIMEOUT_SEC = 3.0
    DEFAULT_SEVERITY = "high"

    def __init__(
        self,
        target_uav: str,
        source: str,
        *,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        severity: str = DEFAULT_SEVERITY,
    ) -> None:
        if timeout_sec <= 0:
            raise ValueError("timeout_sec must be positive")
        self._target_uav = target_uav
        self._source = source
        self._timeout_sec = timeout_sec
        self._severity = severity

        self._last_heartbeat: Optional[float] = None
        self._alerted: bool = False

    # ----- Detector API -----

    @property
    def name(self) -> str:
        return "heartbeat"

    @property
    def target_uav(self) -> str:
        return self._target_uav

    def feed(self, event: TelemetryEvent) -> Optional[SecurityEvent]:
        # Defensive routing check. Monitors should already do this.
        if event.uav_id != self._target_uav:
            return None
        if event.msg_type != "HEARTBEAT":
            return None

        # Update last-seen timestamp from the event's own wall-clock time.
        # Using event.timestamp (rather than time.time()) makes the
        # detector deterministic in tests and robust to monitor scheduling
        # jitter.
        self._last_heartbeat = event.timestamp

        # Recovery path: heartbeat resumed after an alarm. Clear the
        # hysteresis flag so the next disruption fires fresh.
        if self._alerted:
            self._alerted = False

        return None

    def tick(self, now: float) -> Optional[SecurityEvent]:
        if self._last_heartbeat is None:
            return None  # grace period: no heartbeat seen yet
        if self._alerted:
            return None  # hysteresis: already alarmed for this disruption

        elapsed = now - self._last_heartbeat
        if elapsed <= self._timeout_sec:
            return None

        self._alerted = True
        return SecurityEvent(
            source=self._source,
            detector=self.name,
            target_uav=self._target_uav,
            severity=self._severity,
            evidence={
                "last_heartbeat_ts": self._last_heartbeat,
                "time_since_heartbeat": elapsed,
                "timeout_threshold": self._timeout_sec,
            },
        )

    def reset(self) -> None:
        self._last_heartbeat = None
        self._alerted = False

    # ----- Diagnostics -----

    @property
    def last_heartbeat(self) -> Optional[float]:
        return self._last_heartbeat

    @property
    def is_alerted(self) -> bool:
        return self._alerted
