"""Tests for enforcement.handlers.loiter."""

from __future__ import annotations

import asyncio

import pytest

from core.events import RecoveryRequest
from enforcement.handlers.loiter import MavsdkRunner, ModeLoiterHandler


class FakeMavsdkRunner(MavsdkRunner):
    def __init__(self, *, raise_on_call: Exception | None = None) -> None:
        self.calls: list[tuple[str, float]] = []
        self._raise = raise_on_call

    async def set_loiter(self, endpoint: str, *, timeout_sec: float) -> None:
        if self._raise is not None:
            raise self._raise
        self.calls.append((endpoint, timeout_sec))


def _request(target: str = "uav_1") -> RecoveryRequest:
    return RecoveryRequest(
        source="c", target_uav=target, action="mode_loiter", requester="c"
    )


class TestLoiterHandler:
    def test_constructor_rejects_non_positive_timeout(self):
        with pytest.raises(ValueError, match="timeout_sec"):
            ModeLoiterHandler({"uav_0": "udp://:14540"}, timeout_sec=0)

    def test_invokes_runner_with_endpoint(self):
        runner = FakeMavsdkRunner()
        h = ModeLoiterHandler(
            {"uav_0": "udp://:14540", "uav_1": "udp://:14541"},
            runner=runner,
            timeout_sec=2.5,
        )
        ok, err = asyncio.run(h.execute(_request("uav_1")))
        assert ok is True
        assert err is None
        assert runner.calls == [("udp://:14541", 2.5)]

    def test_unknown_uav_returns_failure(self):
        runner = FakeMavsdkRunner()
        h = ModeLoiterHandler({"uav_0": "udp://:14540"}, runner=runner)
        ok, err = asyncio.run(h.execute(_request("uav_99")))
        assert ok is False
        assert "no MAVSDK endpoint" in err
        assert runner.calls == []

    def test_runner_failure_returns_error(self):
        runner = FakeMavsdkRunner(raise_on_call=RuntimeError("connection refused"))
        h = ModeLoiterHandler({"uav_1": "udp://:14541"}, runner=runner)
        ok, err = asyncio.run(h.execute(_request("uav_1")))
        assert ok is False
        assert "loiter failed" in err
        assert "connection refused" in err

    def test_supported_uavs(self):
        h = ModeLoiterHandler(
            {"uav_0": "udp://:14540", "uav_2": "udp://:14542"},
            runner=FakeMavsdkRunner(),
        )
        assert h.supported_uavs == frozenset({"uav_0", "uav_2"})
