"""Tests for enforcement.handlers.restart.ExternalAwareProcessRunner.

Kept in a separate file from test_handler_restart.py because these
tests spawn real OS processes (small `sleep` subprocesses) — they
exercise signal handling and PID liveness checks that a FakeRunner
can't cover.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from enforcement.handlers.restart import (
    ExternalAwareProcessRunner,
    ProcessSpec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spawn_sleep(seconds: int = 60) -> subprocess.Popen:
    """Spawn a short-lived sleep subprocess we can kill in the test."""
    return subprocess.Popen(
        ["sleep", str(seconds)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _wait_until_dead(
    proc_or_pid, timeout: float = 3.0
) -> bool:
    """Wait until a process is dead. Accepts Popen or PID.

    For a Popen, uses poll() — which also REAPS the process, removing
    its zombie entry from the process table. We need this in tests
    because pytest (the parent) doesn't auto-reap, and os.kill(pid,0)
    treats zombies as alive.

    For a bare PID, falls back to os.kill(pid, 0) polling — appropriate
    for processes whose parent is init (which auto-reaps).
    """
    if isinstance(proc_or_pid, subprocess.Popen):
        try:
            proc_or_pid.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_alive(proc_or_pid):
            return True
        time.sleep(0.02)
    return False


def _spec_sleep(secs: int = 60, start_timeout: float = 0.0) -> ProcessSpec:
    """A ProcessSpec that re-spawns a sleep subprocess on start()."""
    return ProcessSpec(
        command=("sleep", str(secs)),
        env={},
        cwd=None,
        start_timeout_sec=start_timeout,
    )


# ---------------------------------------------------------------------------
# kill() against external PID
# ---------------------------------------------------------------------------


class TestKillByInitialPid:
    def test_kill_signals_external_pid(self):
        proc = _spawn_sleep()
        try:
            assert _pid_alive(proc.pid)
            runner = ExternalAwareProcessRunner(
                uav_to_initial_pid={"uav_0": proc.pid},
                terminate_grace_sec=2.0,
            )
            runner.kill("uav_0")
            assert _wait_until_dead(proc)
        finally:
            # Best-effort cleanup if the test failed.
            if _pid_alive(proc.pid):
                try:
                    os.kill(proc.pid, signal.SIGKILL)
                except OSError:
                    pass

    def test_kill_consumes_initial_pid(self):
        """After kill() the initial PID is removed from the map so a
        subsequent kill() falls back to Popen tracking (which is empty
        here, so the call is silent)."""
        proc = _spawn_sleep()
        try:
            runner = ExternalAwareProcessRunner(
                uav_to_initial_pid={"uav_0": proc.pid},
            )
            assert "uav_0" in runner.pending_initial_pids
            runner.kill("uav_0")
            assert "uav_0" not in runner.pending_initial_pids
            # Second kill is a silent no-op.
            runner.kill("uav_0")
        finally:
            if _pid_alive(proc.pid):
                try:
                    os.kill(proc.pid, signal.SIGKILL)
                except OSError:
                    pass

    def test_kill_silent_for_already_dead_pid(self):
        """If the initial PID is already dead, kill() must not raise."""
        proc = _spawn_sleep(1)
        proc.wait(timeout=3)  # let it exit on its own
        assert not _pid_alive(proc.pid)

        runner = ExternalAwareProcessRunner(
            uav_to_initial_pid={"uav_0": proc.pid},
        )
        # Should not raise.
        runner.kill("uav_0")

    def test_kill_silent_for_unknown_uav(self):
        runner = ExternalAwareProcessRunner(uav_to_initial_pid={})
        # No PID, no Popen -> no-op.
        runner.kill("uav_99")

    def test_sigkill_escalation_on_unresponsive_process(self):
        """If SIGTERM doesn't kill within terminate_grace_sec, SIGKILL
        should follow. We simulate an 'unresponsive' process with a
        very short terminate_grace so SIGKILL has to be sent."""
        # Spawn a process that ignores SIGTERM so the runner has to
        # escalate to SIGKILL.
        # Use a tiny Python program that traps SIGTERM.
        code = (
            "import signal, time;"
            "signal.signal(signal.SIGTERM, lambda *_: None);"
            "time.sleep(60)"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            # Wait for the trap to be installed.
            time.sleep(0.3)
            assert _pid_alive(proc.pid)
            runner = ExternalAwareProcessRunner(
                uav_to_initial_pid={"uav_0": proc.pid},
                terminate_grace_sec=0.5,
                kill_grace_sec=1.0,
            )
            runner.kill("uav_0")
            assert _wait_until_dead(proc, timeout=3.0)
        finally:
            if _pid_alive(proc.pid):
                try:
                    os.kill(proc.pid, signal.SIGKILL)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# start() and Popen tracking
# ---------------------------------------------------------------------------


class TestStartAndPopenTracking:
    def test_start_tracks_handle(self):
        runner = ExternalAwareProcessRunner(uav_to_initial_pid={})
        try:
            runner.start("uav_0", _spec_sleep())
            assert "uav_0" in runner.tracked_handles
            assert runner.is_alive("uav_0")
        finally:
            runner.kill("uav_0")

    def test_kill_after_start_uses_popen_not_initial_pid(self):
        """If we have both an initial PID and a tracked Popen for the
        same uav, the Popen is used. This shouldn't happen in practice
        (start() drops initial PID priority via separate dicts), but
        we lock it in: tracked-handle path takes priority in kill()."""
        external = _spawn_sleep()
        try:
            runner = ExternalAwareProcessRunner(
                uav_to_initial_pid={"uav_0": external.pid},
            )
            # Start a new tracked process for the same uav.
            runner.start("uav_0", _spec_sleep())
            tracked_pid = runner.tracked_handles["uav_0"].pid
            assert tracked_pid != external.pid

            runner.kill("uav_0")
            # The tracked Popen should be dead; the external should
            # still be alive (initial PID was NOT consumed).
            assert _wait_until_dead(tracked_pid)
            assert _pid_alive(external.pid)
            assert "uav_0" in runner.pending_initial_pids
        finally:
            for p in [external.pid]:
                if _pid_alive(p):
                    try:
                        os.kill(p, signal.SIGKILL)
                    except OSError:
                        pass

    def test_full_cycle_kill_external_then_start_then_kill(self):
        """Realistic recovery flow: external PX4 PID -> kill it ->
        start a fresh one -> later kill the fresh one."""
        external = _spawn_sleep()
        try:
            runner = ExternalAwareProcessRunner(
                uav_to_initial_pid={"uav_0": external.pid},
                terminate_grace_sec=2.0,
            )

            # Recovery step 1: kill external.
            runner.kill("uav_0")
            assert _wait_until_dead(external)
            assert "uav_0" not in runner.pending_initial_pids

            # Recovery step 2: start fresh.
            runner.start("uav_0", _spec_sleep())
            assert runner.is_alive("uav_0")
            tracked_pid = runner.tracked_handles["uav_0"].pid

            # Later teardown / next recovery: kill fresh.
            runner.kill("uav_0")
            assert _wait_until_dead(tracked_pid)
            assert "uav_0" not in runner.tracked_handles
        finally:
            for p in [external.pid]:
                if _pid_alive(p):
                    try:
                        os.kill(p, signal.SIGKILL)
                    except OSError:
                        pass


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_initial_pid_dict_copied_not_referenced(self):
        """Mutating the passed-in map must not affect the runner."""
        original = {"uav_0": 12345}
        runner = ExternalAwareProcessRunner(uav_to_initial_pid=original)
        original["uav_1"] = 67890
        assert "uav_1" not in runner.pending_initial_pids

    def test_pending_and_tracked_views_are_copies(self):
        runner = ExternalAwareProcessRunner(
            uav_to_initial_pid={"uav_0": 12345}
        )
        view = runner.pending_initial_pids
        view["uav_1"] = 99999
        assert "uav_1" not in runner.pending_initial_pids
