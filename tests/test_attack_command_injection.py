"""Tests for attacks.command_injection."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from attacks.base import AttackContext
from attacks.command_injection import (
    CommandInjectionInjector,
    MavlinkSender,
    PymavlinkSender,
)


# ---------------------------------------------------------------------------
# Test double
# ---------------------------------------------------------------------------


class FakeMavlinkSender(MavlinkSender):
    def __init__(self, *, raise_on_send: bool = False) -> None:
        self.sends: list[dict] = []
        self.closed: bool = False
        self._raise_on_send = raise_on_send

    async def send_command_long(
        self, *, target_endpoint, source_sysid, target_sysid, command_id, params
    ) -> None:
        if self._raise_on_send:
            raise RuntimeError("network down")
        self.sends.append({
            "target_endpoint": target_endpoint,
            "source_sysid": source_sysid,
            "target_sysid": target_sysid,
            "command_id": command_id,
            "params": params,
        })

    async def close(self) -> None:
        self.closed = True


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
    def test_default_sender_is_pymavlink(self):
        inj = CommandInjectionInjector()
        assert isinstance(inj._sender, PymavlinkSender)
        assert inj.attacker_sysid == 99
        assert inj.name == "command_injection"

    def test_whitelisted_sysid_rejected(self):
        # The whole point of this attack is to use a non-whitelist sysid.
        for s in [1, 2, 3, 255]:
            with pytest.raises(ValueError, match="whitelist"):
                CommandInjectionInjector(attacker_sysid=s)

    def test_invalid_sysid_range_rejected(self):
        with pytest.raises(ValueError, match="\\(0, 255\\]"):
            CommandInjectionInjector(attacker_sysid=0)
        with pytest.raises(ValueError, match="\\(0, 255\\]"):
            CommandInjectionInjector(attacker_sysid=256)
        with pytest.raises(ValueError, match="\\(0, 255\\]"):
            CommandInjectionInjector(attacker_sysid=-5)

    def test_invalid_period_rejected(self):
        with pytest.raises(ValueError, match="period_sec"):
            CommandInjectionInjector(period_sec=0)
        with pytest.raises(ValueError, match="period_sec"):
            CommandInjectionInjector(period_sec=-1.0)

    def test_invalid_params_length_rejected(self):
        with pytest.raises(ValueError, match="7-tuple"):
            CommandInjectionInjector(params=(0.0, 0.0))  # type: ignore


# ---------------------------------------------------------------------------
# Arm
# ---------------------------------------------------------------------------


class TestArm:
    def test_arm_derives_endpoint_from_sysid(self):
        sender = FakeMavlinkSender()
        inj = CommandInjectionInjector(sender=sender)
        asyncio.run(inj.arm(_ctx(target_sysid=2)))
        assert inj.target_endpoint == "udpout:127.0.0.1:14541"

    def test_explicit_endpoint_overrides(self):
        inj = CommandInjectionInjector(
            sender=FakeMavlinkSender(),
            explicit_endpoint="udpout:1.2.3.4:9999",
        )
        asyncio.run(inj.arm(_ctx()))
        assert inj.target_endpoint == "udpout:1.2.3.4:9999"

    def test_arm_does_not_send(self):
        sender = FakeMavlinkSender()
        inj = CommandInjectionInjector(sender=sender)
        asyncio.run(inj.arm(_ctx()))
        assert sender.sends == []


# ---------------------------------------------------------------------------
# Fire — background loop
# ---------------------------------------------------------------------------


class TestFireLoop:
    def test_fire_sends_with_spoofed_sysid(self):
        async def scenario():
            sender = FakeMavlinkSender()
            inj = CommandInjectionInjector(
                sender=sender, attacker_sysid=99, period_sec=0.05
            )
            await inj.arm(_ctx(target_sysid=2))
            await inj.fire()
            # Let the loop run for a few iterations
            await asyncio.sleep(0.25)
            await inj.cleanup()
            return sender, inj

        sender, inj = asyncio.run(scenario())
        # We expect at least 3 sends in 0.25s with period 0.05s
        assert len(sender.sends) >= 3
        for s in sender.sends:
            assert s["source_sysid"] == 99
            assert s["target_sysid"] == 2
            assert s["target_endpoint"] == "udpout:127.0.0.1:14541"
            assert s["command_id"] == 192  # default DO_REPOSITION
        assert sender.closed is True

    def test_fire_before_arm_raises(self):
        inj = CommandInjectionInjector(sender=FakeMavlinkSender())
        with pytest.raises(RuntimeError, match="before arm"):
            asyncio.run(inj.fire())

    def test_double_fire_raises(self):
        async def scenario():
            inj = CommandInjectionInjector(
                sender=FakeMavlinkSender(), period_sec=0.05
            )
            await inj.arm(_ctx())
            await inj.fire()
            try:
                await inj.fire()
                return False
            except RuntimeError:
                return True
            finally:
                await inj.cleanup()

        assert asyncio.run(scenario()) is True

    def test_send_failure_does_not_kill_loop(self):
        """One failing send call shouldn't stop subsequent sends —
        but with raise_on_send=True ALL sends fail, so we only verify
        the loop survives and keeps ticking through cleanup."""
        async def scenario():
            sender = FakeMavlinkSender(raise_on_send=True)
            inj = CommandInjectionInjector(
                sender=sender, period_sec=0.05
            )
            await inj.arm(_ctx())
            await inj.fire()
            await asyncio.sleep(0.2)
            # Verify the task is still alive (loop didn't crash)
            task_alive = inj._task is not None and not inj._task.done()
            await inj.cleanup()
            return task_alive

        assert asyncio.run(scenario()) is True

    def test_cleanup_stops_loop_promptly(self):
        async def scenario():
            sender = FakeMavlinkSender()
            inj = CommandInjectionInjector(sender=sender, period_sec=1.0)
            await inj.arm(_ctx())
            await inj.fire()
            await asyncio.sleep(0.05)  # let one send happen
            t0 = asyncio.get_event_loop().time()
            await inj.cleanup()
            elapsed = asyncio.get_event_loop().time() - t0
            return elapsed, sender

        elapsed, sender = asyncio.run(scenario())
        # cleanup must wake the loop from its 1.0s sleep promptly
        # (via stop_event); should complete well under a second.
        assert elapsed < 0.5
        # At least one send happened before cleanup
        assert len(sender.sends) >= 1


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_without_arm_is_noop(self):
        sender = FakeMavlinkSender()
        inj = CommandInjectionInjector(sender=sender)
        asyncio.run(inj.cleanup())
        assert sender.sends == []
        # Sender close was still attempted (defensive)
        assert sender.closed is True

    def test_cleanup_after_arm_no_fire(self):
        async def scenario():
            sender = FakeMavlinkSender()
            inj = CommandInjectionInjector(sender=sender)
            await inj.arm(_ctx())
            await inj.cleanup()
            return sender

        sender = asyncio.run(scenario())
        assert sender.sends == []
        assert sender.closed is True

    def test_cleanup_is_idempotent(self):
        async def scenario():
            sender = FakeMavlinkSender()
            inj = CommandInjectionInjector(sender=sender, period_sec=0.05)
            await inj.arm(_ctx())
            await inj.fire()
            await asyncio.sleep(0.1)
            await inj.cleanup()
            # Second cleanup should be safe
            await inj.cleanup()
            return sender

        # Must not raise
        asyncio.run(scenario())
