"""
ZeroVelocityHoldHandler — stop the UAV by commanding zero velocity.

Recovery action of the `trust_aware` policy for position anomalies
(gps_anomaly, cross_check_anomaly; ranging_anomaly in B1). Review
stage 3, 2026-09-26.

Why not LOITER
--------------
LOITER holds the *estimated* position. Under the GZBridge GPS-offset
spoof the estimate jumps by the injected 50 m ~7.5 s after injection,
and a UAV already in LOITER is flown ~50 m to "return" to its hold
point (campaign median post_response_drift 50.0 m, review P1). OFFBOARD
body velocity (0, 0, 0), yawspeed 0 does not use the position estimate:
the attack falsifies GPS lat/lon only; GPS velocity stays true.
Stage-2 SITL probe (hover, n=1 per arm, commit acfe338): LOITER 49.8 m,
zero-velocity hold 0.18 m, OFFBOARD held for the whole 60 s window.

What this action is NOT
-----------------------
- It does not repair navigation: the position error stays ~50 m.
- It is damage limitation, not mission recovery: the UAV stops.
- A spoofer that also falsifies GNSS velocity consistently defeats it
  (by construction of this attack model; stated in Ch. 3/4).

Design
------
One handler per UAV (like FilterCommandsHandler). OFFBOARD needs a
continuous setpoint stream; MAVSDK keeps streaming only while its
System lives. A short-lived per-call connection (the loiter default)
would therefore drop the UAV out of OFFBOARD as soon as it closed, so
there is deliberately NO default runner: ExperimentRunner injects one
backed by the live mission connection (set_runner). Without it the
handler reports failure instead of pretending to act.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Optional

from core.events import RecoveryRequest
from enforcement.recovery import ActionHandler


class VelocityHoldRunner(ABC):
    """DI seam: command the UAV to hold zero body velocity."""

    @abstractmethod
    async def hold_zero_velocity(self) -> None:
        """Start OFFBOARD with velocity (0, 0, 0), yawspeed 0.

        Raises on any failure (no connection, OFFBOARD rejected).
        """


class ZeroVelocityHoldHandler(ActionHandler):
    """Recovery action handler: hold zero velocity in OFFBOARD."""

    DEFAULT_TIMEOUT_SEC: float = 10.0

    def __init__(
        self,
        uav_id: str,
        *,
        runner: Optional[VelocityHoldRunner] = None,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        if not uav_id:
            raise ValueError("uav_id must be non-empty")
        if timeout_sec <= 0:
            raise ValueError("timeout_sec must be positive")
        self._uav_id = uav_id
        self._runner = runner
        self._timeout = timeout_sec

    @property
    def target_uav(self) -> str:
        return self._uav_id

    @property
    def supported_uavs(self) -> frozenset[str]:
        return frozenset({self._uav_id})

    @property
    def runner(self) -> Optional[VelocityHoldRunner]:
        return self._runner

    def set_runner(self, runner: VelocityHoldRunner) -> None:
        """Inject the mission-backed runner (ExperimentRunner, at start)."""
        self._runner = runner

    async def execute(
        self, request: RecoveryRequest
    ) -> tuple[bool, Optional[str]]:
        if request.target_uav != self._uav_id:
            return False, (
                f"velocity-hold handler for {self._uav_id!r} "
                f"got request for {request.target_uav!r}"
            )
        if self._runner is None:
            return False, (
                "no velocity-hold runner: needs the live mission connection"
            )
        try:
            await asyncio.wait_for(
                self._runner.hold_zero_velocity(), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            return False, f"zero-velocity hold timed out after {self._timeout} s"
        except Exception as exc:
            return False, f"zero-velocity hold failed: {exc}"
        return True, None
