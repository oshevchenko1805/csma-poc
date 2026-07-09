"""Tests for attacks.gps_spoofing (via FakeParamWriter)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from attacks.base import AttackContext
from attacks.gps_spoofing import GpsSpoofingInjector


# ---------------------------------------------------------------------------
# Test double — satisfies the attacks.base.ParamWriter Protocol
# ---------------------------------------------------------------------------


class FakeParamWriter:
    def __init__(
        self,
        *,
        params: dict[str, float] | None = None,
        raise_on_get: bool = False,
        raise_on_set: bool = False,
    ) -> None:
        self.params: dict[str, float] = dict(params or {})
        self.raise_on_get = raise_on_get
        self.raise_on_set = raise_on_set
        self.gets: list[str] = []
        self.sets: list[tuple[str, float]] = []

    async def get_param_float(self, name: str) -> float:
        if self.raise_on_get:
            raise RuntimeError("get failed")
        self.gets.append(name)
        return self.params.get(name, 0.0)

    async def set_param_float(self, name: str, value: float) -> None:
        if self.raise_on_set:
            raise RuntimeError("set failed")
        self.sets.append((name, value))
        self.params[name] = value


def _ctx(writer=None, sysid: int = 1) -> AttackContext:
    return AttackContext(
        target_uav=f"uav_{sysid - 1}",
        target_sysid=sysid,
        log_dir=Path("/tmp"),
        param_writer=writer,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_defaults(self):
        inj = GpsSpoofingInjector()
        assert inj.name == "gps_spoofing"
        assert inj._param_name == "SIM_GPS_OFF_N"
        assert inj._spoofed_value == 50.0

    def test_empty_param_name_rejected(self):
        with pytest.raises(ValueError, match="param_name"):
            GpsSpoofingInjector(param_name="")

    def test_bool_value_rejected(self):
        with pytest.raises(TypeError, match="bool"):
            GpsSpoofingInjector(spoofed_value=True)  # type: ignore

    def test_non_numeric_value_rejected(self):
        with pytest.raises(TypeError, match="int or float"):
            GpsSpoofingInjector(spoofed_value="50")  # type: ignore


# ---------------------------------------------------------------------------
# Arm
# ---------------------------------------------------------------------------


class TestArm:
    def test_arm_stores_writer_without_touching_it(self):
        w = FakeParamWriter(params={"SIM_GPS_OFF_N": 0.0})
        inj = GpsSpoofingInjector()
        asyncio.run(inj.arm(_ctx(writer=w)))
        # arm must not read or write the param (mission not flying yet)
        assert w.gets == []
        assert w.sets == []

    def test_arm_without_writer_does_not_raise(self):
        inj = GpsSpoofingInjector()
        # None param_writer (e.g. NullMissionRunner) — arm stays quiet.
        asyncio.run(inj.arm(_ctx(writer=None)))


# ---------------------------------------------------------------------------
# Fire
# ---------------------------------------------------------------------------


class TestFire:
    def test_fire_before_arm_raises(self):
        inj = GpsSpoofingInjector()
        with pytest.raises(RuntimeError, match="before arm"):
            asyncio.run(inj.fire())

    def test_fire_without_writer_raises(self):
        inj = GpsSpoofingInjector()
        asyncio.run(inj.arm(_ctx(writer=None)))
        with pytest.raises(RuntimeError, match="param_writer"):
            asyncio.run(inj.fire())

    def test_fire_captures_baseline_then_sets_spoofed(self):
        w = FakeParamWriter(params={"SIM_GPS_OFF_N": 0.0})
        inj = GpsSpoofingInjector(spoofed_value=50.0)
        asyncio.run(inj.arm(_ctx(writer=w)))
        asyncio.run(inj.fire())
        assert inj.original_value == 0.0
        assert w.gets == ["SIM_GPS_OFF_N"]
        assert w.sets == [("SIM_GPS_OFF_N", 50.0)]

    def test_fire_captures_nonzero_baseline(self):
        w = FakeParamWriter(params={"SIM_GPS_OFF_N": 3.5})
        inj = GpsSpoofingInjector(spoofed_value=50.0)
        asyncio.run(inj.arm(_ctx(writer=w)))
        asyncio.run(inj.fire())
        assert inj.original_value == 3.5

    def test_fire_explicit_restore_value_skips_read(self):
        # raise_on_get would blow up if fire tried to read.
        w = FakeParamWriter(raise_on_get=True)
        inj = GpsSpoofingInjector(spoofed_value=50.0, restore_value=0.0)
        asyncio.run(inj.arm(_ctx(writer=w)))
        asyncio.run(inj.fire())
        assert inj.original_value == 0.0
        assert w.gets == []  # never read
        assert w.sets == [("SIM_GPS_OFF_N", 50.0)]

    def test_fire_baseline_read_failure_falls_back(self):
        w = FakeParamWriter(raise_on_get=True)  # no restore_value set
        inj = GpsSpoofingInjector(spoofed_value=50.0)
        asyncio.run(inj.arm(_ctx(writer=w)))
        asyncio.run(inj.fire())
        # Falls back to DEFAULT_RESTORE_VALUE, spoof still applied.
        assert inj.original_value == 0.0
        assert w.sets == [("SIM_GPS_OFF_N", 50.0)]

    def test_fire_propagates_set_failure(self):
        w = FakeParamWriter(params={"SIM_GPS_OFF_N": 0.0}, raise_on_set=True)
        inj = GpsSpoofingInjector()
        asyncio.run(inj.arm(_ctx(writer=w)))
        with pytest.raises(RuntimeError, match="set failed"):
            asyncio.run(inj.fire())


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_restores_baseline(self):
        w = FakeParamWriter(params={"SIM_GPS_OFF_N": 0.0})
        inj = GpsSpoofingInjector(spoofed_value=50.0)
        asyncio.run(inj.arm(_ctx(writer=w)))
        asyncio.run(inj.fire())
        asyncio.run(inj.cleanup())
        # Last write restores the captured baseline.
        assert w.sets[-1] == ("SIM_GPS_OFF_N", 0.0)
        assert w.params["SIM_GPS_OFF_N"] == 0.0

    def test_cleanup_restores_nonzero_baseline(self):
        w = FakeParamWriter(params={"SIM_GPS_OFF_N": 3.5})
        inj = GpsSpoofingInjector(spoofed_value=50.0)
        asyncio.run(inj.arm(_ctx(writer=w)))
        asyncio.run(inj.fire())
        asyncio.run(inj.cleanup())
        assert w.sets[-1] == ("SIM_GPS_OFF_N", 3.5)

    def test_cleanup_without_fire_is_noop(self):
        w = FakeParamWriter(params={"SIM_GPS_OFF_N": 0.0})
        inj = GpsSpoofingInjector()
        asyncio.run(inj.arm(_ctx(writer=w)))
        asyncio.run(inj.cleanup())  # never fired
        assert w.sets == []

    def test_cleanup_without_writer_is_noop(self):
        inj = GpsSpoofingInjector()
        asyncio.run(inj.arm(_ctx(writer=None)))
        # Must not raise even though there's no writer.
        asyncio.run(inj.cleanup())

    def test_cleanup_swallows_set_failure(self):
        w = FakeParamWriter(params={"SIM_GPS_OFF_N": 0.0})
        inj = GpsSpoofingInjector(spoofed_value=50.0)
        asyncio.run(inj.arm(_ctx(writer=w)))
        asyncio.run(inj.fire())
        w.raise_on_set = True  # cleanup's restore will fail
        asyncio.run(inj.cleanup())  # must not raise
