"""
MissionRunner contract.

A MissionRunner is what makes the UAVs fly during an experiment. In
production this drives MAVSDK across 3 UAVs through coordinated
waypoints. In CI / unit tests it's just a sleep.

We keep mission separate from attack: a baseline run has a real
mission but no attack; an attack run has both; some validation runs
have neither.

Lifecycle
---------
- start()  → begin flying (returns immediately, runs in background)
- wait_until_complete(timeout) → block until landing or timeout
- abort()  → emergency stop, called on errors / shutdown

NullMissionRunner just sleeps for the configured mission.duration_sec
so unit tests don't need PX4. A real MAVSDK runner is added in step 10.

param_writer_for (step 10e)
---------------------------
Optional capability: a mission that holds a live connection to each UAV
can lend it to a param-writing attack. Default returns None (no param
channel); MavsdkMissionRunner overrides it. NullMissionRunner keeps the
None default, so baseline / test runs simply have no ParamWriter.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Optional

from attacks.base import ParamWriter


class MissionRunner(ABC):
    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def wait_until_complete(self, timeout_sec: float) -> bool:
        """Returns True if the mission completed within timeout."""

    @abstractmethod
    async def abort(self) -> None: ...

    def param_writer_for(self, uav_id: str) -> Optional[ParamWriter]:
        """Return a ParamWriter targeting `uav_id`, or None if this
        runner provides no param channel. Non-abstract with a None
        default so only param-capable runners override it."""
        return None


class NullMissionRunner(MissionRunner):
    """Just sleeps for `duration_sec`. Used for tests + baseline-only runs."""

    def __init__(self, duration_sec: float) -> None:
        if duration_sec <= 0:
            raise ValueError("duration_sec must be positive")
        self._duration = duration_sec
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._fly())

    async def _fly(self) -> None:
        await asyncio.sleep(self._duration)

    async def wait_until_complete(self, timeout_sec: float) -> bool:
        if self._task is None:
            return True
        try:
            await asyncio.wait_for(self._task, timeout=timeout_sec)
            return True
        except asyncio.TimeoutError:
            return False

    async def abort(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
