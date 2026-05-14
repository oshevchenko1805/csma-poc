"""Tests for attacks.comm_disruption."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from attacks.base import AttackContext
from attacks.comm_disruption import (
    CommDisruptionInjector,
    IptablesRunner,
    SubprocessIptablesRunner,
)


# ---------------------------------------------------------------------------
# Test double
# ---------------------------------------------------------------------------


class FakeIptablesRunner(IptablesRunner):
    """Records add/delete calls; optionally raises."""

    def __init__(
        self,
        *,
        raise_on_add: bool = False,
        raise_on_delete: bool = False,
    ) -> None:
        self.adds: list[tuple[int, str]] = []
        self.deletes: list[tuple[int, str]] = []
        self._raise_on_add = raise_on_add
        self._raise_on_delete = raise_on_delete

    async def add_drop_rule(self, *, port: int, protocol: str = "udp") -> None:
        if self._raise_on_add:
            raise RuntimeError("iptables add failed")
        self.adds.append((port, protocol))

    async def delete_drop_rule(self, *, port: int, protocol: str = "udp") -> None:
        if self._raise_on_delete:
            raise RuntimeError("iptables delete failed")
        self.deletes.append((port, protocol))


def _ctx(target_uav: str = "uav_0", target_sysid: int = 1) -> AttackContext:
    return AttackContext(
        target_uav=target_uav,
        target_sysid=target_sysid,
        log_dir=Path("/tmp"),
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_runner_is_subprocess(self):
        inj = CommDisruptionInjector()
        assert isinstance(inj._runner, SubprocessIptablesRunner)

    def test_explicit_port_must_be_positive(self):
        with pytest.raises(ValueError, match="explicit_port"):
            CommDisruptionInjector(explicit_port=0)
        with pytest.raises(ValueError, match="explicit_port"):
            CommDisruptionInjector(explicit_port=-100)

    def test_name(self):
        assert CommDisruptionInjector().name == "comm_disruption"


# ---------------------------------------------------------------------------
# Arm
# ---------------------------------------------------------------------------


class TestArm:
    def test_arm_derives_port_from_sysid(self):
        runner = FakeIptablesRunner()
        inj = CommDisruptionInjector(runner=runner)
        asyncio.run(inj.arm(_ctx(target_sysid=1)))
        assert inj.target_port == 14540  # 14540 + (1-1)

        inj2 = CommDisruptionInjector(runner=runner)
        asyncio.run(inj2.arm(_ctx(target_sysid=3)))
        assert inj2.target_port == 14542  # 14540 + (3-1)

    def test_explicit_port_overrides(self):
        inj = CommDisruptionInjector(
            runner=FakeIptablesRunner(), explicit_port=14580
        )
        asyncio.run(inj.arm(_ctx(target_sysid=1)))
        assert inj.target_port == 14580

    def test_custom_port_base(self):
        inj = CommDisruptionInjector(
            runner=FakeIptablesRunner(), port_base=18570
        )
        asyncio.run(inj.arm(_ctx(target_sysid=2)))
        assert inj.target_port == 18571  # 18570 + (2-1)

    def test_arm_does_not_invoke_iptables(self):
        """arm() is just resource computation, no side effects."""
        runner = FakeIptablesRunner()
        inj = CommDisruptionInjector(runner=runner)
        asyncio.run(inj.arm(_ctx()))
        assert runner.adds == []
        assert runner.deletes == []


# ---------------------------------------------------------------------------
# Fire
# ---------------------------------------------------------------------------


class TestFire:
    def test_fire_invokes_add(self):
        runner = FakeIptablesRunner()
        inj = CommDisruptionInjector(runner=runner)
        asyncio.run(inj.arm(_ctx(target_sysid=2)))
        asyncio.run(inj.fire())
        assert runner.adds == [(14541, "udp")]

    def test_fire_before_arm_raises(self):
        inj = CommDisruptionInjector(runner=FakeIptablesRunner())
        with pytest.raises(RuntimeError, match="before arm"):
            asyncio.run(inj.fire())

    def test_fire_propagates_runner_failure(self):
        runner = FakeIptablesRunner(raise_on_add=True)
        inj = CommDisruptionInjector(runner=runner)
        asyncio.run(inj.arm(_ctx()))
        with pytest.raises(RuntimeError, match="iptables add failed"):
            asyncio.run(inj.fire())


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_after_fire_deletes_rule(self):
        runner = FakeIptablesRunner()
        inj = CommDisruptionInjector(runner=runner)
        asyncio.run(inj.arm(_ctx(target_sysid=1)))
        asyncio.run(inj.fire())
        asyncio.run(inj.cleanup())
        assert runner.deletes == [(14540, "udp")]

    def test_cleanup_without_arm_is_noop(self):
        runner = FakeIptablesRunner()
        inj = CommDisruptionInjector(runner=runner)
        asyncio.run(inj.cleanup())
        assert runner.deletes == []

    def test_cleanup_after_arm_no_fire_still_attempts_delete(self):
        """If arm succeeded but fire didn't run, cleanup still tries
        the delete (idempotent runner handles non-existent rule)."""
        runner = FakeIptablesRunner()
        inj = CommDisruptionInjector(runner=runner)
        asyncio.run(inj.arm(_ctx(target_sysid=2)))
        asyncio.run(inj.cleanup())
        assert runner.deletes == [(14541, "udp")]

    def test_cleanup_swallows_runner_failure(self):
        """Even if the runner raises, cleanup must not propagate —
        otherwise the runner's try/finally surfaces a misleading error."""
        runner = FakeIptablesRunner(raise_on_delete=True)
        inj = CommDisruptionInjector(runner=runner)
        asyncio.run(inj.arm(_ctx()))
        # Must not raise
        asyncio.run(inj.cleanup())


# ---------------------------------------------------------------------------
# SubprocessIptablesRunner — minimal construction tests (no real iptables)
# ---------------------------------------------------------------------------


class TestSubprocessRunnerConstruction:
    def test_default_uses_sudo(self):
        r = SubprocessIptablesRunner()
        assert r._sudo is True
        assert r._cmd_prefix() == ["sudo", "-n"]

    def test_no_sudo(self):
        r = SubprocessIptablesRunner(sudo=False)
        assert r._cmd_prefix() == []

    def test_invalid_timeout(self):
        with pytest.raises(ValueError, match="timeout_sec"):
            SubprocessIptablesRunner(timeout_sec=0)
