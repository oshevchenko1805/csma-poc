"""Tests for attacks.gps_spoofing."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from attacks.base import AttackContext
from attacks.gps_spoofing import (
    DefaultGpsSpoofingRunner,
    GpsSpoofingInjector,
    GpsSpoofingRunner,
)


# ---------------------------------------------------------------------------
# Test double
# ---------------------------------------------------------------------------


class FakeGpsSpoofingRunner(GpsSpoofingRunner):
    def __init__(
        self,
        *,
        param_values: dict[str, float | int] | None = None,
        raise_on_get: bool = False,
        raise_on_set: bool = False,
    ) -> None:
        # Initial PX4 param state seen by get_param.
        self._state: dict[str, float | int] = dict(param_values or {})
        self.gets: list[tuple[str, str]] = []
        self.sets: list[tuple[str, str, float | int]] = []
        self.closed: bool = False
        self._raise_on_get = raise_on_get
        self._raise_on_set = raise_on_set

    async def get_param(self, *, mavsdk_endpoint, param_name):
        if self._raise_on_get:
            raise RuntimeError("get failed")
        self.gets.append((mavsdk_endpoint, param_name))
        return self._state.get(param_name, 0.0)

    async def set_param(self, *, mavsdk_endpoint, param_name, value):
        if self._raise_on_set:
            raise RuntimeError("set failed")
        self.sets.append((mavsdk_endpoint, param_name, value))
        self._state[param_name] = value

    async def close(self):
        self.closed = True


def _ctx(target_sysid: int = 1) -> AttackContext:
    return AttackContext(
        target_uav=f"uav_{target_sysid - 1}",
        target_sysid=target_sysid,
        log_dir=Path("/tmp"),
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_defaults(self):
        inj = GpsSpoofingInjector()
        assert inj.name == "gps_spoofing"
        assert isinstance(inj._runner, DefaultGpsSpoofingRunner)
        assert inj._param_name == "SIM_GPS_NOISE"
        assert inj._spoofed_value == 100.0

    def test_empty_param_name_rejected(self):
        with pytest.raises(ValueError, match="param_name"):
            GpsSpoofingInjector(param_name="")

    def test_bool_value_rejected(self):
        with pytest.raises(TypeError, match="bool"):
            GpsSpoofingInjector(spoofed_value=True)  # type: ignore

    def test_non_numeric_value_rejected(self):
        with pytest.raises(TypeError, match="int or float"):
            GpsSpoofingInjector(spoofed_value="100")  # type: ignore


# ---------------------------------------------------------------------------
# Arm
# ---------------------------------------------------------------------------


class TestArm:
    def test_arm_derives_endpoint(self):
        runner = FakeGpsSpoofingRunner(param_values={"SIM_GPS_NOISE": 0.5})
        inj = GpsSpoofingInjector(runner=runner)
        asyncio.run(inj.arm(_ctx(target_sysid=2)))
        assert inj.target_endpoint == "udp://127.0.0.1:14541"

    def test_explicit_endpoint_overrides(self):
        runner = FakeGpsSpoofingRunner()
        inj = GpsSpoofingInjector(
            runner=runner, explicit_endpoint="udp://10.0.0.1:14550"
        )
        asyncio.run(inj.arm(_ctx()))
        assert inj.target_endpoint == "udp://10.0.0.1:14550"

    def test_arm_captures_original_value(self):
        runner = FakeGpsSpoofingRunner(param_values={"SIM_GPS_NOISE": 0.5})
        inj = GpsSpoofingInjector(runner=runner)
        asyncio.run(inj.arm(_ctx()))
        assert inj.original_value == 0.5
        assert runner.gets == [("udp://127.0.0.1:14540", "SIM_GPS_NOISE")]

    def test_arm_uses_explicit_restore_value(self):
        runner = FakeGpsSpoofingRunner()
        inj = GpsSpoofingInjector(runner=runner, restore_value=0.3)
        asyncio.run(inj.arm(_ctx()))
        assert inj.original_value == 0.3
        # get_param should NOT have been called
        assert runner.gets == []

    def test_arm_fallback_when_get_fails(self):
        """If reading the current value fails, fall back to 0 / 0.0."""
        runner = FakeGpsSpoofingRunner(raise_on_get=True)
        inj = GpsSpoofingInjector(runner=runner, spoofed_value=100.0)
        asyncio.run(inj.arm(_ctx()))
        assert inj.original_value == 0.0

        runner2 = FakeGpsSpoofingRunner(raise_on_get=True)
        inj2 = GpsSpoofingInjector(runner=runner2, spoofed_value=5)  # int
        asyncio.run(inj2.arm(_ctx()))
        assert inj2.original_value == 0  # int fallback for int spoofed value

    def test_arm_does_not_set(self):
        runner = FakeGpsSpoofingRunner()
        inj = GpsSpoofingInjector(runner=runner)
        asyncio.run(inj.arm(_ctx()))
        assert runner.sets == []


# ---------------------------------------------------------------------------
# Fire
# ---------------------------------------------------------------------------


class TestFire:
    def test_fire_sets_spoofed_value(self):
        runner = FakeGpsSpoofingRunner(param_values={"SIM_GPS_NOISE": 0.5})
        inj = GpsSpoofingInjector(runner=runner, spoofed_value=100.0)
        asyncio.run(inj.arm(_ctx(target_sysid=2)))
        asyncio.run(inj.fire())
        assert runner.sets == [
            ("udp://127.0.0.1:14541", "SIM_GPS_NOISE", 100.0)
        ]

    def test_fire_before_arm_raises(self):
        inj = GpsSpoofingInjector(runner=FakeGpsSpoofingRunner())
        with pytest.raises(RuntimeError, match="before arm"):
            asyncio.run(inj.fire())

    def test_fire_propagates_runner_failure(self):
        runner = FakeGpsSpoofingRunner(raise_on_set=True)
        inj = GpsSpoofingInjector(runner=runner)
        asyncio.run(inj.arm(_ctx()))
        with pytest.raises(RuntimeError, match="set failed"):
            asyncio.run(inj.fire())


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_restores_original(self):
        runner = FakeGpsSpoofingRunner(param_values={"SIM_GPS_NOISE": 0.5})
        inj = GpsSpoofingInjector(runner=runner, spoofed_value=100.0)
        asyncio.run(inj.arm(_ctx()))
        asyncio.run(inj.fire())
        asyncio.run(inj.cleanup())
        # Sets: fire set 100.0, cleanup restored 0.5
        assert runner.sets[-1] == ("udp://127.0.0.1:14540", "SIM_GPS_NOISE", 0.5)
        assert runner.closed is True

    def test_cleanup_without_arm_is_noop(self):
        runner = FakeGpsSpoofingRunner()
        inj = GpsSpoofingInjector(runner=runner)
        asyncio.run(inj.cleanup())
        assert runner.sets == []
        # close still attempted
        assert runner.closed is True

    def test_cleanup_after_arm_no_fire_still_restores(self):
        """If fire didn't run, cleanup still writes original_value —
        a no-op at the PX4 level (writing same value)."""
        runner = FakeGpsSpoofingRunner(param_values={"SIM_GPS_NOISE": 0.5})
        inj = GpsSpoofingInjector(runner=runner)
        asyncio.run(inj.arm(_ctx()))
        asyncio.run(inj.cleanup())
        assert runner.sets == [("udp://127.0.0.1:14540", "SIM_GPS_NOISE", 0.5)]

    def test_cleanup_swallows_set_failure(self):
        runner = FakeGpsSpoofingRunner(
            param_values={"SIM_GPS_NOISE": 0.5}, raise_on_set=True
        )
        inj = GpsSpoofingInjector(runner=runner)
        asyncio.run(inj.arm(_ctx()))
        # Must not raise
        asyncio.run(inj.cleanup())

    def test_int_value_roundtrip(self):
        """Validates that int spoofed values flow through correctly
        (not coerced to float)."""
        runner = FakeGpsSpoofingRunner(param_values={"EKF2_GPS_CTRL": 5})
        inj = GpsSpoofingInjector(
            runner=runner,
            param_name="EKF2_GPS_CTRL",
            spoofed_value=0,  # int
        )
        asyncio.run(inj.arm(_ctx()))
        asyncio.run(inj.fire())
        asyncio.run(inj.cleanup())
        # First set: spoofed 0, second set: restore 5
        assert runner.sets[0][2] == 0
        assert runner.sets[1][2] == 5


# ---------------------------------------------------------------------------
# DefaultGpsSpoofingRunner — minimal construction tests
# ---------------------------------------------------------------------------


class TestDefaultRunnerConstruction:
    def test_default_timeout(self):
        r = DefaultGpsSpoofingRunner()
        assert r._timeout == DefaultGpsSpoofingRunner.DEFAULT_TIMEOUT_SEC

    def test_invalid_timeout(self):
        with pytest.raises(ValueError, match="timeout_sec"):
            DefaultGpsSpoofingRunner(timeout_sec=0)
