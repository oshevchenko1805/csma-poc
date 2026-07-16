from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from attacks.base import AttackContext
from attacks.monitor_takeout import MonitorTakeoutInjector


# ---------------------------------------------------------------------------
# Test double — satisfies attacks.base.MonitorHandle (uav_id, failure_domain,
# synchronous stop()).
# ---------------------------------------------------------------------------


class FakeMonitor:
    def __init__(self, uav_id: str, failure_domain: str) -> None:
        self.uav_id = uav_id
        self.failure_domain = failure_domain
        self.stopped = False
        self.stop_calls = 0

    def stop(self) -> None:
        self.stopped = True
        self.stop_calls += 1


def _ctx(monitors, target_uav: str = "uav_0") -> AttackContext:
    return AttackContext(
        target_uav=target_uav,
        target_sysid=int(target_uav.split("_")[1]) + 1,
        log_dir=Path("/tmp"),
        monitors=tuple(monitors),
    )


# Arch A: one shared 'ground_station' domain across all three monitors.
def _arch_a_monitors():
    return [
        FakeMonitor("uav_0", "ground_station"),
        FakeMonitor("uav_1", "ground_station"),
        FakeMonitor("uav_2", "ground_station"),
    ]


# Arch B/C: per-UAV failure domains (domain == uav_id).
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
        assert MonitorTakeoutInjector().name == "monitor_takeout"

    def test_pre_fire_state_empty(self):
        inj = MonitorTakeoutInjector()
        assert inj.stopped_uavs == []
        assert inj.target_domain is None


# ---------------------------------------------------------------------------
# Arm
# ---------------------------------------------------------------------------


class TestArm:
    def test_arm_does_not_stop_anything(self):
        mons = _per_uav_monitors()
        inj = MonitorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(mons, "uav_0")))
        assert all(not m.stopped for m in mons)
        assert inj.stopped_uavs == []

    def test_arm_without_monitors_does_not_raise(self):
        inj = MonitorTakeoutInjector()
        # No monitors in ctx (e.g. a null-mission context). arm() must
        # not fail; fire() is where the misconfiguration surfaces.
        asyncio.run(inj.arm(_ctx([], "uav_0")))


# ---------------------------------------------------------------------------
# Fire — Architecture A (shared domain => SPOF)
# ---------------------------------------------------------------------------


class TestFireArchA:
    def test_all_domain_monitors_stopped(self):
        mons = _arch_a_monitors()
        inj = MonitorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(mons, "uav_0")))
        asyncio.run(inj.fire())
        # Shared ground_station domain => all three monitors go down.
        assert all(m.stopped for m in mons)
        assert sorted(inj.stopped_uavs) == ["uav_0", "uav_1", "uav_2"]
        assert inj.target_domain == "ground_station"

    def test_spof_independent_of_which_uav_targeted(self):
        # Targeting any UAV in arch A takes out the whole contour.
        mons = _arch_a_monitors()
        inj = MonitorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(mons, "uav_2")))
        asyncio.run(inj.fire())
        assert all(m.stopped for m in mons)


# ---------------------------------------------------------------------------
# Fire — Architecture B/C (per-UAV domain => only target's monitor)
# ---------------------------------------------------------------------------


class TestFirePerUav:
    def test_only_target_monitor_stopped(self):
        mons = _per_uav_monitors()
        inj = MonitorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(mons, "uav_1")))
        asyncio.run(inj.fire())
        by_id = {m.uav_id: m for m in mons}
        assert by_id["uav_1"].stopped
        assert not by_id["uav_0"].stopped
        assert not by_id["uav_2"].stopped
        assert inj.stopped_uavs == ["uav_1"]
        assert inj.target_domain == "uav_1"


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


class TestGuards:
    def test_fire_before_arm_raises(self):
        inj = MonitorTakeoutInjector()
        with pytest.raises(RuntimeError, match="before arm"):
            asyncio.run(inj.fire())

    def test_fire_with_no_monitors_raises(self):
        inj = MonitorTakeoutInjector()
        asyncio.run(inj.arm(_ctx([], "uav_0")))
        with pytest.raises(RuntimeError, match="no monitor watches"):
            asyncio.run(inj.fire())

    def test_fire_with_target_absent_raises(self):
        # Monitors present but none watches the target.
        mons = _per_uav_monitors()
        inj = MonitorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(mons, "uav_9")))
        with pytest.raises(RuntimeError, match="no monitor watches"):
            asyncio.run(inj.fire())


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_is_noop_and_leaves_monitors_stopped(self):
        mons = _arch_a_monitors()
        inj = MonitorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(mons, "uav_0")))
        asyncio.run(inj.fire())
        asyncio.run(inj.cleanup())
        # cleanup must not revive monitors, and must not raise.
        assert all(m.stopped for m in mons)
        # No extra stop() calls from cleanup (fire stopped each once).
        assert all(m.stop_calls == 1 for m in mons)

    def test_cleanup_without_fire_is_safe(self):
        inj = MonitorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(_per_uav_monitors(), "uav_0")))
        # cleanup before fire must be a safe no-op.
        asyncio.run(inj.cleanup())


class TestNonTargetTakeout:
    """SPOF / blast-radius scenario: take out a NON-target UAV's domain,
    then attack a different UAV. In A the shared ground_station domain
    means the target's monitor dies too; in B/C it survives."""

    def test_arch_a_neighbour_takeout_kills_target_monitor(self):
        mons = _arch_a_monitors()
        inj = MonitorTakeoutInjector(takeout_uav="uav_1")
        asyncio.run(inj.arm(_ctx(mons, "uav_0")))  # attack target = uav_0
        asyncio.run(inj.fire())
        # Shared domain: taking out uav_1's host stops every monitor,
        # including the one watching the attack target uav_0.
        assert all(m.stopped for m in mons)
        assert inj.target_domain == "ground_station"
        assert sorted(inj.stopped_uavs) == ["uav_0", "uav_1", "uav_2"]

    def test_per_uav_neighbour_takeout_spares_target_monitor(self):
        mons = _per_uav_monitors()
        inj = MonitorTakeoutInjector(takeout_uav="uav_1")
        asyncio.run(inj.arm(_ctx(mons, "uav_0")))
        asyncio.run(inj.fire())
        by_id = {m.uav_id: m for m in mons}
        # Only uav_1's monitor dies; the target's monitor lives on.
        assert by_id["uav_1"].stopped
        assert not by_id["uav_0"].stopped
        assert not by_id["uav_2"].stopped
        assert inj.stopped_uavs == ["uav_1"]
        assert inj.target_domain == "uav_1"

    def test_takeout_uav_property(self):
        inj = MonitorTakeoutInjector(takeout_uav="uav_1")
        asyncio.run(inj.arm(_ctx(_per_uav_monitors(), "uav_0")))
        assert inj.takeout_uav == "uav_1"

    def test_defaults_to_attack_target(self):
        inj = MonitorTakeoutInjector()
        asyncio.run(inj.arm(_ctx(_per_uav_monitors(), "uav_2")))
        assert inj.takeout_uav == "uav_2"

    def test_unknown_takeout_uav_raises(self):
        inj = MonitorTakeoutInjector(takeout_uav="uav_9")
        asyncio.run(inj.arm(_ctx(_per_uav_monitors(), "uav_0")))
        with pytest.raises(RuntimeError, match="no monitor watches"):
            asyncio.run(inj.fire())
