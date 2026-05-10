"""
Detector abstraction.

A Detector is a stateful observer that consumes TelemetryEvents from one
UAV and emits a SecurityEvent when its specific anomaly signature fires.

Design contract:
  * `feed(event)` is reactive: invoked once per inbound telemetry event
    by the host monitor. The detector decides whether the event is
    relevant (e.g. HeartbeatDetector ignores anything that isn't a
    HEARTBEAT message). Returns a SecurityEvent or None.
  * `tick(now)` is proactive: invoked on a fixed cadence by the host
    monitor (typically once per second). Used by detectors that need
    to detect *absence* of events — heartbeat timeout being the classic
    case. Default implementation returns None; reactive-only detectors
    can ignore it.
  * `reset()` clears internal state between experiment runs.
  * The detector never reaches outside itself: it does not log, publish
    on the mesh, or trigger isolation. Those are the monitor's and the
    decision module's jobs. Keeping detectors pure means each one is
    trivially unit-testable.

Hysteresis:
    Most detectors should not re-fire a SecurityEvent every tick while an
    anomaly is ongoing. The recommended pattern (used by HeartbeatDetector)
    is a `_alerted` flag that is set when the alarm raises and cleared
    when normal conditions resume. This is the detector's responsibility,
    not the monitor's.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from core.events import SecurityEvent, TelemetryEvent


class Detector(ABC):
    """Base class for all detectors."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Detector name used as SecurityEvent.detector."""

    @property
    @abstractmethod
    def target_uav(self) -> str:
        """UAV being observed by this detector instance."""

    @abstractmethod
    def feed(self, event: TelemetryEvent) -> Optional[SecurityEvent]:
        """Process a telemetry event. Return SecurityEvent if anomalous."""

    def tick(self, now: float) -> Optional[SecurityEvent]:
        """
        Periodic check, called by the host monitor at a fixed cadence.

        Override only if the detector needs to detect *absence* of events.
        Default: no-op.
        """
        return None

    @abstractmethod
    def reset(self) -> None:
        """Reset internal state. Called between experiment runs."""

