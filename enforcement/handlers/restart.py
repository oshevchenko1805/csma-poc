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

Externally-launched processes (Gap 2)
-------------------------------------
The default runner only knows about processes it spawned itself. In
the live PoC pipeline PX4 is typically launched out-of-band by
`scripts/launch_px4.sh` so the dissertation author can poke it
manually before running an experiment. To let the recovery handler
actually restart THOSE processes (rather than spawning a useless
second PX4 that immediately collides on the MAVLink port), we provide
`ExternalAwareProcessRunner`: it takes an initial uav_id->PID map at
construction. The first kill() for a UAV signals that external PID;
all subsequent kill()s use our tracked Popen as usual.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
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


class ExternalAwareProcessRunner(ProcessRunner):
    """ProcessRunner that knows about externally-launched processes.

    Pass `uav_to_initial_pid` mapping at construction. On the FIRST
    kill() for each UAV, this runner sends signals (SIGTERM then
    SIGKILL) directly to that PID. After start() spawns a fresh
    process for the UAV, subsequent kill()s use our tracked Popen
    handle just like DefaultProcessRunner.

    Use case: the dissertation author launches PX4 instances out of
    band via scripts/launch_px4.sh, writing PIDs to a file. The
    experiment driver reads that file and passes the map here so the
    recovery handler can actually kill the right PX4 instance instead
    of wasting time spawning a useless second one.

    Behaviour notes
    ---------------
    - If a given UAV has neither a tracked Popen nor an initial PID,
      kill() is a silent no-op (matches DefaultProcessRunner).
    - If the initial PID points to a process that has already exited,
      kill() is silent — we check liveness with `os.kill(pid, 0)` before
      signalling.
    - start() uses the same semantics as DefaultProcessRunner; any
      prior handle for the uav is dropped silently (the caller should
      have kill()ed it first).
    - Initial PIDs are CONSUMED on first kill(): they are removed
      from the map so a subsequent kill() falls back to the (now
      tracked) Popen path. This prevents accidentally signalling a
      stale PID that the OS may have re-assigned to an unrelated
      process.
    """

    def __init__(
        self,
        *,
        uav_to_initial_pid: dict[str, int],
        terminate_grace_sec: float = 2.0,
        kill_grace_sec: float = 1.0,
        poll_interval_sec: float = 0.05,
    ) -> None:
        self._initial_pids: dict[str, int] = dict(uav_to_initial_pid)
        self._handles: dict[str, subprocess.Popen] = {}
        self._terminate_grace = terminate_grace_sec
        self._kill_grace = kill_grace_sec
        self._poll_interval = poll_interval_sec

    def kill(self, uav_id: str) -> None:
        # Tracked Popen takes priority — that's a process WE spawned,
        # so we know it's the right one.
        proc = self._handles.pop(uav_id, None)
        if proc is not None:
            self._kill_popen(proc)
            return
        # Fall back to externally-launched PID. Pop it: the next
        # kill() must not reuse it (PID may have been recycled).
        pid = self._initial_pids.pop(uav_id, None)
        if pid is None:
            return
        self._kill_pid(pid)

    def start(self, uav_id: str, spec: ProcessSpec) -> None:
        # A correct caller has already kill()ed any prior process for
        # this uav, but be defensive — drop a tracked handle silently
        # if it lingers.
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
        """True if we have a tracked Popen for this uav that's still
        running. Initial-PID-only entries return False — we don't
        track liveness for PIDs we didn't spawn."""
        proc = self._handles.get(uav_id)
        if proc is None:
            return False
        return proc.poll() is None

    @property
    def tracked_handles(self) -> dict[str, subprocess.Popen]:
        """Diagnostic view of tracked Popen handles. Read-only copy."""
        return dict(self._handles)

    @property
    def pending_initial_pids(self) -> dict[str, int]:
        """Diagnostic view of unused initial PIDs."""
        return dict(self._initial_pids)

    # ----- internals -----

    def _kill_popen(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=self._terminate_grace)
            return
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            return
        # Escalate to SIGKILL.
        try:
            proc.kill()
            proc.wait(timeout=self._kill_grace)
        except Exception:
            pass

    def _kill_pid(self, pid: int) -> None:
        if not self._pid_alive(pid):
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
        # Poll for exit up to terminate_grace.
        deadline = time.time() + self._terminate_grace
        while time.time() < deadline:
            if not self._pid_alive(pid):
                return
            time.sleep(self._poll_interval)
        # Force.
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        # Best-effort grace for the kernel to reap.
        deadline = time.time() + self._kill_grace
        while time.time() < deadline:
            if not self._pid_alive(pid):
                return
            time.sleep(self._poll_interval)

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


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
