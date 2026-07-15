from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from attacks.base import AttackContext, AttackInjector
from attacks.composite import SequentialAttackInjector


# ---------------------------------------------------------------------------
# Recording child — logs arm/fire/cleanup into a shared list so order is
# observable across children.
# ---------------------------------------------------------------------------


class RecordingChild(AttackInjector):
    def __init__(
        self,
        name: str,
        log: list,
        *,
        arm_raises: bool = False,
        fire_raises: bool = False,
        cleanup_raises: bool = False,
    ) -> None:
        self._name = name
        self._log = log
        self._arm_raises = arm_raises
        self._fire_raises = fire_raises
        self._cleanup_raises = cleanup_raises
        self.ctx: AttackContext | None = None
        self.armed = False
        self.fired = False
        self.cleaned = False

    @property
    def name(self) -> str:
        return self._name

    async def arm(self, ctx: AttackContext) -> None:
        self.ctx = ctx
        self._log.append(("arm", self._name))
        if self._arm_raises:
            raise RuntimeError(f"{self._name} arm failed")
        self.armed = True

    async def fire(self) -> None:
        self._log.append(("fire", self._name))
        if self._fire_raises:
            raise RuntimeError(f"{self._name} fire failed")
        self.fired = True

    async def cleanup(self) -> None:
        self._log.append(("cleanup", self._name))
        self.cleaned = True
        if self._cleanup_raises:
            raise RuntimeError(f"{self._name} cleanup failed")


def _ctx() -> AttackContext:
    return AttackContext(
        target_uav="uav_0", target_sysid=1, log_dir=Path("/tmp")
    )


# ---------------------------------------------------------------------------
# Name + construction
# ---------------------------------------------------------------------------


class TestName:
    def test_default_name_is_joined(self):
        log: list = []
        inj = SequentialAttackInjector(
            [RecordingChild("a", log), RecordingChild("b", log)]
        )
        assert inj.name == "a+b"

    def test_name_override(self):
        log: list = []
        inj = SequentialAttackInjector(
            [RecordingChild("a", log)], name="scenario_x"
        )
        assert inj.name == "scenario_x"

    def test_empty_children_rejected(self):
        with pytest.raises(ValueError, match="at least one"):
            SequentialAttackInjector([])

    def test_children_exposed(self):
        log: list = []
        a, b = RecordingChild("a", log), RecordingChild("b", log)
        inj = SequentialAttackInjector([a, b])
        assert inj.children == (a, b)


# ---------------------------------------------------------------------------
# Arm
# ---------------------------------------------------------------------------


class TestArm:
    def test_arms_all_in_order_same_ctx(self):
        log: list = []
        a, b = RecordingChild("a", log), RecordingChild("b", log)
        inj = SequentialAttackInjector([a, b])
        ctx = _ctx()
        asyncio.run(inj.arm(ctx))
        assert log == [("arm", "a"), ("arm", "b")]
        assert a.ctx is ctx and b.ctx is ctx
        assert a.armed and b.armed

    def test_arm_error_propagates(self):
        log: list = []
        a = RecordingChild("a", log)
        b = RecordingChild("b", log, arm_raises=True)
        inj = SequentialAttackInjector([a, b])
        with pytest.raises(RuntimeError, match="b arm failed"):
            asyncio.run(inj.arm(_ctx()))
        # 'a' armed before 'b' failed
        assert a.armed and not b.armed


# ---------------------------------------------------------------------------
# Fire
# ---------------------------------------------------------------------------


class TestFire:
    def test_fires_all_in_order(self):
        log: list = []
        a, b = RecordingChild("a", log), RecordingChild("b", log)
        inj = SequentialAttackInjector([a, b])
        asyncio.run(inj.arm(_ctx()))
        log.clear()
        asyncio.run(inj.fire())
        assert log == [("fire", "a"), ("fire", "b")]

    def test_fire_before_arm_raises(self):
        log: list = []
        inj = SequentialAttackInjector([RecordingChild("a", log)])
        with pytest.raises(RuntimeError, match="before arm"):
            asyncio.run(inj.fire())

    def test_fire_error_propagates_and_is_partial(self):
        log: list = []
        a = RecordingChild("a", log)
        b = RecordingChild("b", log, fire_raises=True)
        inj = SequentialAttackInjector([a, b])
        asyncio.run(inj.arm(_ctx()))
        with pytest.raises(RuntimeError, match="b fire failed"):
            asyncio.run(inj.fire())
        assert a.fired and not b.fired


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_cleans_in_reverse_order(self):
        log: list = []
        a, b = RecordingChild("a", log), RecordingChild("b", log)
        inj = SequentialAttackInjector([a, b])
        asyncio.run(inj.arm(_ctx()))
        asyncio.run(inj.fire())
        log.clear()
        asyncio.run(inj.cleanup())
        assert log == [("cleanup", "b"), ("cleanup", "a")]

    def test_cleanup_after_fire_failure_cleans_all(self):
        # Simulate the runner: arm all, fire (second raises), then the
        # finally-block cleanup must still tear down every child.
        log: list = []
        a = RecordingChild("a", log)
        b = RecordingChild("b", log, fire_raises=True)
        inj = SequentialAttackInjector([a, b])
        asyncio.run(inj.arm(_ctx()))
        with pytest.raises(RuntimeError):
            asyncio.run(inj.fire())
        asyncio.run(inj.cleanup())
        assert a.cleaned and b.cleaned

    def test_one_child_cleanup_failure_does_not_block_others(self):
        log: list = []
        a = RecordingChild("a", log)
        b = RecordingChild("b", log, cleanup_raises=True)
        inj = SequentialAttackInjector([a, b])
        asyncio.run(inj.arm(_ctx()))
        asyncio.run(inj.fire())
        # b (cleaned first, reverse order) raises internally; a must still
        # be cleaned and cleanup() must not propagate.
        asyncio.run(inj.cleanup())
        assert a.cleaned and b.cleaned
