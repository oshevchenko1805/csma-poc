"""
RestartProcessHandler — PX4 SITL instance restart for node-failure recovery.

Used when a UAV's MAVLink heartbeat has been lost (the
'comm_disruption' attack class in the PoC). The recovery action is to
ensure any lingering PX4 process for that instance is terminated and
launch a fresh one.

Operational notes (Chapter 4)
-----------------------------
Restarting the PX4 process is a coarse simulation of recovery. A real
deployment with a hardened companion computer would have far more
options: hot-failover to a secondary autopilot, sensor replay,
on-board mission resume from a checkpoint. The PoC restart serves the
methodology — it lets us measure MTTR end-to-end with a deterministic
recovery action that actually re-establishes MAVLink — but the
specific *value* of MTTR-restart should be read as "PX4 cold-start
latency", not "fundamental recovery latency". This is documented
explicitly in Chapter 5's MTTR decomposition (detection -> isolation
-> action -> stable).

Design
------
- Per-UAV ProcessSpec dictates command, env, cwd, and ready-wait time.
- ProcessRunner is a DI seam. The default implementation uses
  subprocess.Popen and tracks handles per uav_id. Tests inject a
  FakeProcessRunner with the same interface.
- "Ready" is approximated by a fixed sleep after Popen. PX4 SITL
  cold start is ~3-6 seconds before HEARTBEAT begins; the spec's
  start_timeout_sec absorbs that. Smarter readiness detection
  (heartbeat-watching, log-line scraping) is a future improvement
  not required for the MTTR measurement methodology.
"""

from __future__ import annotations

import asyncio
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.events import RecoveryRequest
from enforcement.recovery import ActionHandler


@dataclass(frozen=True)
class ProcessSpec:
    """How to (re)start the PX4 process for one UAV."""

    command: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)
    cwd: Optional[Path] = None
    start_timeout_sec: float = 5.0
    """Wait this long after Popen for the process to become ready."""


# ---------------------------------------------------------------------------
# Process runner — DI seam
# ---------------------------------------------------------------------------


class ProcessRunner(ABC):
    """Abstract interface for spawning and killing OS processes."""

    @abstractmethod
    def kill(self, uav_id: str) -> None:
        """Terminate any tracked process for this UAV. Idempotent."""

    @abstractmethod
    def start(self, uav_id: str, spec: ProcessSpec) -> None:
        """Spawn a fresh process for this UAV. Replaces any prior tracked
        handle for the same uav_id."""


class DefaultProcessRunner(ProcessRunner):
    """subprocess-based runner. Tracks Popen handles per uav_id so we
    can kill exactly the process we started — never relying on pkill
    pattern matching that could hit unrelated processes."""

    def __init__(
        self,
        *,
        terminate_grace_sec: float = 2.0,
        kill_grace_sec: float = 1.0,
    ) -> None:
        self._handles: dict[str, subprocess.Popen] = {}
        self._terminate_grace = terminate_grace_sec
        self._kill_grace = kill_grace_sec

    def kill(self, uav_id: str) -> None:
        proc = self._handles.pop(uav_id, None)
        if proc is None:
            return
        if proc.poll() is not None:
            return  # already dead
        try:
            proc.terminate()
            proc.wait(timeout=self._terminate_grace)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=self._kill_grace)
            except Exception:
                pass
        except Exception:
            pass

    def start(self, uav_id: str, spec: ProcessSpec) -> None:
        # If a previous handle is still tracked for this uav, drop it
        # silently. A correct caller has already kill()ed it.
        self._handles.pop(uav_id, None)
        proc = subprocess.Popen(
            list(spec.command),
            env={**spec.env} if spec.env else None,
            cwd=str(spec.cwd) if spec.cwd else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._handles[uav_id] = proc

    def is_alive(self, uav_id: str) -> bool:
        proc = self._handles.get(uav_id)
        if proc is None:
            return False
        return proc.poll() is None


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class RestartProcessHandler(ActionHandler):
    """Recovery action handler: kill + restart the PX4 process."""

    def __init__(
        self,
        specs: dict[str, ProcessSpec],
        *,
        runner: Optional[ProcessRunner] = None,
    ) -> None:
        self._specs: dict[str, ProcessSpec] = dict(specs)
        self._runner: ProcessRunner = runner or DefaultProcessRunner()

    @property
    def runner(self) -> ProcessRunner:
        return self._runner

    @property
    def supported_uavs(self) -> frozenset[str]:
        return frozenset(self._specs.keys())

    async def execute(
        self, request: RecoveryRequest
    ) -> tuple[bool, Optional[str]]:
        spec = self._specs.get(request.target_uav)
        if spec is None:
            return False, f"no process spec for {request.target_uav!r}"

        # Kill any existing process. Idempotent.
        try:
            self._runner.kill(request.target_uav)
        except Exception as exc:
            return False, f"kill failed: {exc}"

        # Start fresh.
        try:
            self._runner.start(request.target_uav, spec)
        except Exception as exc:
            return False, f"start failed: {exc}"

        # Crude readiness wait. See module docstring.
        await asyncio.sleep(spec.start_timeout_sec)

        return True, None
