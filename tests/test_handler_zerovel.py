"""Tests for enforcement.handlers.zerovel (review stage 3)."""

from __future__ import annotations

import asyncio

import pytest

from core.events import RecoveryRequest
from enforcement.handlers import VelocityHoldRunner, ZeroVelocityHoldHandler


class FakeRunner(VelocityHoldRunner):
    def __init__(self, *, exc: Exception | None = None, delay: float = 0.0):
        self.calls = 0
        self._exc = exc
        self._delay = delay

    async def hold_zero_velocity(self) -> None:
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._exc is not None:
            raise self._exc


def _req(target: str = "uav_0") -> RecoveryRequest:
    return RecoveryRequest(
        source="c", target_uav=target, action="hold_zero_velocity",
        requester="c",
    )


class TestZeroVelocityHoldHandler:
    def test_rejects_empty_uav(self):
        with pytest.raises(ValueError, match="uav_id"):
            ZeroVelocityHoldHandler("")

    def test_rejects_non_positive_timeout(self):
        with pytest.raises(ValueError, match="timeout_sec"):
            ZeroVelocityHoldHandler("uav_0", timeout_sec=0)

    def test_success_calls_runner_once(self):
        r = FakeRunner()
        h = ZeroVelocityHoldHandler("uav_0", runner=r)
        assert asyncio.run(h.execute(_req())) == (True, None)
        assert r.calls == 1

    def test_no_runner_is_failure_not_silent_success(self):
        ok, err = asyncio.run(ZeroVelocityHoldHandler("uav_0").execute(_req()))
        assert ok is False
        assert "mission connection" in err

    def test_wrong_target_is_failure_and_runner_untouched(self):
        r = FakeRunner()
        ok, err = asyncio.run(
            ZeroVelocityHoldHandler("uav_0", runner=r).execute(_req("uav_1"))
        )
        assert ok is False and "uav_1" in err
        assert r.calls == 0

    def test_runner_exception_reported(self):
        r = FakeRunner(exc=RuntimeError("offboard denied"))
        ok, err = asyncio.run(
            ZeroVelocityHoldHandler("uav_0", runner=r).execute(_req())
        )
        assert ok is False and "offboard denied" in err

    def test_timeout_reported(self):
        r = FakeRunner(delay=1.0)
        ok, err = asyncio.run(
            ZeroVelocityHoldHandler("uav_0", runner=r, timeout_sec=0.05)
            .execute(_req())
        )
        assert ok is False and "timed out" in err

    def test_set_runner_and_supported_uavs(self):
        h = ZeroVelocityHoldHandler("uav_2")
        assert h.runner is None
        r = FakeRunner()
        h.set_runner(r)
        assert h.runner is r
        assert h.supported_uavs == frozenset({"uav_2"})
        assert h.target_uav == "uav_2"
