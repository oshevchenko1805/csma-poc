from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from attacks.base import AttackContext
from attacks.detector_takeout import DetectorTakeoutInjector


# ---------------------------------------------------------------------------
# Test double — satisfies attacks.base.MonitorHandle plus
# disable_local_detectors().
# ---------------------------------------------------------------------------


class FakeMonitor:
    def __init__(self, uav_id: str, failure_domain: str) -> None:
        self.uav_id = uav_id
        self.failure_domain = failure_domain
        self.detectors_disabled = False
        self.disable_calls = 0
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def disable_local_detectors(self) -> None:
        self.detectors_disabled = True
        self.disable_calls += 1


def _ctx(monitors, target_uav: str = "uav_0") -> AttackContext:
    return AttackContext(
        target_uav=target_uav,
        target_sysid=int(target_uav.split("_")[1]) + 1,
        log_dir=Path("/tmp"),
        monitors=tuple(monitors),
    )


# Arch A: three monitors, one per watched UAV, sharing one domain.
def _arch_a_monitors():
    return [
        FakeMonitor("uav_0", "ground_station"),
        FakeMonitor("uav_1", "ground_station"),
        FakeMonitor("uav_2", "ground_station"),
    ]


# Arch B/C: per-UAV monitors and domains.
def _per_uav_monitors():
    return [
        FakeMonitor("uav_0", "uav_0"),
        FakeMonitor("uav_1", "uav_1"),
        FakeMonitor("uav_2", "uav_2"),
    ]


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_name(self):
        assert DetectorTakeoutInjector().name == "detector_takeout"

    def test_pre_fire_state_empty(self):
        assert DetectorTakeoutInjector().disabled_uavs == []


# ---------------------------------------------------------------------------
# Arm
# ---------------------------------------------------------------------------


class TestArm:
    def test_arm_does_not_disable(self):
        mons = _per_uav_monitors()
        inj = DetectorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(mons, "uav_0")))
        assert all(not m.detectors_disabled for m in mons)
        assert inj.disabled_uavs == []

    def test_arm_without_monitors_does_not_raise(self):
        inj = DetectorTakeoutInjector()
        asyncio.run(inj.arm(_ctx([], "uav_0")))


# ---------------------------------------------------------------------------
# Fire
# ---------------------------------------------------------------------------


class TestFire:
    def test_only_target_monitor_disabled_per_uav(self):
        mons = _per_uav_monitors()
        inj = DetectorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(mons, "uav_1")))
        asyncio.run(inj.fire())
        by_id = {m.uav_id: m for m in mons}
        assert by_id["uav_1"].detectors_disabled
        assert not by_id["uav_0"].detectors_disabled
        assert not by_id["uav_2"].detectors_disabled
        assert inj.disabled_uavs == ["uav_1"]

    def test_only_target_monitor_disabled_shared_domain(self):
        # Even in arch A (shared domain), detector_takeout silences only
        # the monitor watching the target — NOT the whole domain. That is
        # the difference from monitor_takeout: detection of the target
        # only came from the target's own monitor anyway.
        mons = _arch_a_monitors()
        inj = DetectorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(mons, "uav_0")))
        asyncio.run(inj.fire())
        by_id = {m.uav_id: m for m in mons}
        assert by_id["uav_0"].detectors_disabled
        assert not by_id["uav_1"].detectors_disabled
        assert not by_id["uav_2"].detectors_disabled
        assert inj.disabled_uavs == ["uav_0"]

    def test_monitors_not_stopped(self):
        # The monitor must stay alive (listener/peer-pub keep running so
        # the mesh signal survives) — only detectors are silenced.
        mons = _per_uav_monitors()
        inj = DetectorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(mons, "uav_0")))
        asyncio.run(inj.fire())
        assert all(not m.stopped for m in mons)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


class TestGuards:
    def test_fire_before_arm_raises(self):
        inj = DetectorTakeoutInjector()
        with pytest.raises(RuntimeError, match="before arm"):
            asyncio.run(inj.fire())

    def test_fire_with_no_monitors_raises(self):
        inj = DetectorTakeoutInjector()
        asyncio.run(inj.arm(_ctx([], "uav_0")))
        with pytest.raises(RuntimeError, match="no monitor watches target"):
            asyncio.run(inj.fire())

    def test_fire_with_target_absent_raises(self):
        mons = _per_uav_monitors()
        inj = DetectorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(mons, "uav_9")))
        with pytest.raises(RuntimeError, match="no monitor watches target"):
            asyncio.run(inj.fire())


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_noop_leaves_disabled(self):
        mons = _per_uav_monitors()
        inj = DetectorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(mons, "uav_0")))
        asyncio.run(inj.fire())
        asyncio.run(inj.cleanup())
        by_id = {m.uav_id: m for m in mons}
        assert by_id["uav_0"].detectors_disabled
        assert by_id["uav_0"].disable_calls == 1  # cleanup added no calls

    def test_cleanup_without_fire_safe(self):
        inj = DetectorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(_per_uav_monitors(), "uav_0")))
        asyncio.run(inj.cleanup())
