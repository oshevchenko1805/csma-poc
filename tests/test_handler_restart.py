"""Tests for enforcement.handlers.restart."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.events import RecoveryRequest
from enforcement.handlers.restart import (
    ProcessRunner,
    ProcessSpec,
    RestartProcessHandler,
)


class FakeProcessRunner(ProcessRunner):
    """Records kill/start calls; can simulate failures."""

    def __init__(
        self, *, fail_kill: bool = False, fail_start: bool = False
    ) -> None:
        self.kills: list[str] = []
        self.starts: list[tuple[str, ProcessSpec]] = []
        self._fail_kill = fail_kill
        self._fail_start = fail_start

    def kill(self, uav_id: str) -> None:
        if self._fail_kill:
            raise RuntimeError("kill bombed")
        self.kills.append(uav_id)

    def start(self, uav_id: str, spec: ProcessSpec) -> None:
        if self._fail_start:
            raise RuntimeError("start bombed")
        self.starts.append((uav_id, spec))


def _request(target: str = "uav_0") -> RecoveryRequest:
    return RecoveryRequest(
        source="c", target_uav=target, action="restart_process", requester="c"
    )


def _spec(start_timeout: float = 0.0) -> ProcessSpec:
    return ProcessSpec(
        command=("./px4", "-i", "0"),
        env={"PX4_SYS_AUTOSTART": "4001"},
        cwd=Path("/tmp"),
        start_timeout_sec=start_timeout,
    )


class TestRestartHandler:
    def test_kill_then_start_in_order(self):
        runner = FakeProcessRunner()
        h = RestartProcessHandler({"uav_0": _spec()}, runner=runner)
        ok, err = asyncio.run(h.execute(_request("uav_0")))
        assert ok is True
        assert err is None
        assert runner.kills == ["uav_0"]
        assert len(runner.starts) == 1
        assert runner.starts[0][0] == "uav_0"

    def test_unknown_uav_returns_failure(self):
        runner = FakeProcessRunner()
        h = RestartProcessHandler({"uav_0": _spec()}, runner=runner)
        ok, err = asyncio.run(h.execute(_request("uav_99")))
        assert ok is False
        assert "no process spec" in err
        # No subprocess ops attempted
        assert runner.kills == []
        assert runner.starts == []

    def test_kill_failure_propagates(self):
        runner = FakeProcessRunner(fail_kill=True)
        h = RestartProcessHandler({"uav_0": _spec()}, runner=runner)
        ok, err = asyncio.run(h.execute(_request("uav_0")))
        assert ok is False
        assert "kill failed" in err
        assert runner.starts == []

    def test_start_failure_propagates(self):
        runner = FakeProcessRunner(fail_start=True)
        h = RestartProcessHandler({"uav_0": _spec()}, runner=runner)
        ok, err = asyncio.run(h.execute(_request("uav_0")))
        assert ok is False
        assert "start failed" in err
        assert runner.kills == ["uav_0"]  # we did try to kill first

    def test_supported_uavs(self):
        h = RestartProcessHandler(
            {"uav_0": _spec(), "uav_1": _spec()},
            runner=FakeProcessRunner(),
        )
        assert h.supported_uavs == frozenset({"uav_0", "uav_1"})

    def test_start_timeout_awaited(self):
        """spec.start_timeout_sec is awaited via asyncio.sleep."""
        import time

        runner = FakeProcessRunner()
        h = RestartProcessHandler(
            {"uav_0": _spec(start_timeout=0.2)}, runner=runner
        )
        t0 = time.monotonic()
        ok, _ = asyncio.run(h.execute(_request("uav_0")))
        elapsed = time.monotonic() - t0
        assert ok is True
        assert elapsed >= 0.18  # allow a hair of jitter
