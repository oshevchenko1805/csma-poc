"""
ModeLoiterHandler — switch a UAV to LOITER (MAVSDK 'hold') mode.

Used as the recovery action for GPS spoofing detection. PX4's LOITER
mode (called 'hold' in MAVSDK) commands the autopilot to hold position
at the current location using its existing state estimate. In a real
deployment this would be one part of a defence: after switching to
LOITER, the pilot or a higher-level recovery routine would reconfigure
the EKF (e.g. disable GPS fusion, fall back to optical-flow / vision-
based positioning) before resuming the mission. The PoC stops at the
LOITER step because that is the mode-change recovery action — anything
beyond it is a separate research question.

Design
------
- Per-UAV MAVSDK endpoint (e.g. 'udp://:14541') in a dict.
- MavsdkRunner is a DI seam. The default implementation creates a
  short-lived MAVSDK System per call: connect -> wait connected ->
  action.hold() -> done. This avoids leaking gRPC connections across
  the long lifetime of a Coordinator. Tests inject a FakeMavsdkRunner
  recording calls.

PoC simplification (Chapter 4)
------------------------------
Connection-per-call adds ~1 second of overhead per recovery. For the
MTTR measurement this is acceptable and explicitly attributed in the
decomposition (action time vs gRPC connect time vs PX4 mode
acceptance). Sharing one persistent connection per UAV is a future
optimisation; it would also require restructuring the asyncio loop
ownership in the coordinator (see runners/coordinator.py module
docstring).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from core.events import RecoveryRequest
from enforcement.recovery import ActionHandler


# ---------------------------------------------------------------------------
# MAVSDK runner — DI seam
# ---------------------------------------------------------------------------


class MavsdkRunner(ABC):
    """Abstract interface for issuing MAVSDK actions."""

    @abstractmethod
    async def set_loiter(self, endpoint: str, *, timeout_sec: float) -> None:
        """Connect, switch to HOLD/LOITER mode, disconnect.

        Raises on any failure (connection, command rejected, timeout).
        """


class DefaultMavsdkRunner(MavsdkRunner):
    """
    Real MAVSDK-driven implementation. Used in production runs.

    The lazy import keeps mavsdk off the dependency path of unit tests
    that inject a FakeMavsdkRunner — pytest doesn't have to install
    mavsdk just to test handler logic.
    """

    async def set_loiter(self, endpoint: str, *, timeout_sec: float) -> None:
        import asyncio

        from mavsdk import System

        drone = System()
        await asyncio.wait_for(
            drone.connect(system_address=endpoint), timeout=timeout_sec
        )
        # Wait until the connection state reports connected.
        async for state in drone.core.connection_state():
            if state.is_connected:
                break
        # MAVSDK's action.hold() == PX4 LOITER mode.
        await asyncio.wait_for(drone.action.hold(), timeout=timeout_sec)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class ModeLoiterHandler(ActionHandler):
    """Recovery action handler: command target UAV into LOITER (HOLD)."""

    DEFAULT_TIMEOUT_SEC: float = 5.0

    def __init__(
        self,
        endpoints: dict[str, str],
        *,
        runner: Optional[MavsdkRunner] = None,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        if timeout_sec <= 0:
            raise ValueError("timeout_sec must be positive")
        self._endpoints: dict[str, str] = dict(endpoints)
        self._runner: MavsdkRunner = runner or DefaultMavsdkRunner()
        self._timeout = timeout_sec

    @property
    def runner(self) -> MavsdkRunner:
        return self._runner

    @property
    def supported_uavs(self) -> frozenset[str]:
        return frozenset(self._endpoints.keys())

    async def execute(
        self, request: RecoveryRequest
    ) -> tuple[bool, Optional[str]]:
        endpoint = self._endpoints.get(request.target_uav)
        if endpoint is None:
            return False, f"no MAVSDK endpoint for {request.target_uav!r}"

        try:
            await self._runner.set_loiter(endpoint, timeout_sec=self._timeout)
        except Exception as exc:
            return False, f"loiter failed: {exc}"

        return True, None
