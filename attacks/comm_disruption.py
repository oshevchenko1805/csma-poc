"""
comm_disruption — heartbeat-loss attack via iptables DROP rule.

Approximates a jamming or link-failure attack by inserting an iptables
INPUT chain rule that drops UDP traffic on the target UAV's MAVLink
telemetry port. The target monitor stops receiving HEARTBEAT, triggers
the heartbeat detector (3 s timeout default), and the rest of the
detection→isolation→recovery pipeline proceeds.

PoC caveats (Chapter 4)
-----------------------
- Real jamming would affect the radio layer (multi-hop, partial loss,
  packet corruption). Here all-or-nothing UDP DROP gives a clean
  reproducible signal for MTTD measurement, at the cost of being less
  realistic.
- Requires CAP_NET_ADMIN or sudo. On the experiment VM the user is
  expected to either run with sudo or grant the capability to the
  python interpreter. Document in the experiment-run README.

Resource constraints
--------------------
The cleanup step (`iptables -D`) is idempotent-by-design here: we
swallow non-zero exit codes from the delete command because the rule
may already be gone (manual `iptables -F`, system reboot, prior
cleanup pass). What we cannot tolerate is a leaked rule between runs —
so cleanup ALWAYS runs from the experiment runner's try/finally
regardless of arm/fire outcome.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Optional

from attacks.base import AttackContext, AttackInjector


# ---------------------------------------------------------------------------
# IptablesRunner — DI seam
# ---------------------------------------------------------------------------


class IptablesRunner(ABC):
    """Abstract iptables interface; concrete runner = subprocess call."""

    @abstractmethod
    async def add_drop_rule(
        self, *, port: int, protocol: str = "udp"
    ) -> None:
        """Add an INPUT-chain DROP rule. Raises on failure."""

    @abstractmethod
    async def delete_drop_rule(
        self, *, port: int, protocol: str = "udp"
    ) -> None:
        """Remove the matching DROP rule. Idempotent — must not raise
        if the rule is absent."""


class SubprocessIptablesRunner(IptablesRunner):
    """Real iptables runner via async subprocess."""

    DEFAULT_TIMEOUT_SEC: float = 5.0

    def __init__(
        self,
        *,
        sudo: bool = True,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        if timeout_sec <= 0:
            raise ValueError("timeout_sec must be positive")
        self._sudo = sudo
        self._timeout = timeout_sec

    def _cmd_prefix(self) -> list[str]:
        return ["sudo", "-n"] if self._sudo else []

    async def add_drop_rule(self, *, port: int, protocol: str = "udp") -> None:
        cmd = self._cmd_prefix() + [
            "iptables", "-A", "INPUT",
            "-p", protocol,
            "--dport", str(port),
            "-j", "DROP",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(
                f"iptables add timed out after {self._timeout}s"
            )
        if proc.returncode != 0:
            msg = stderr.decode("utf-8", errors="replace").strip() if stderr else ""
            raise RuntimeError(
                f"iptables add failed (rc={proc.returncode}): {msg}"
            )

    async def delete_drop_rule(
        self, *, port: int, protocol: str = "udp"
    ) -> None:
        cmd = self._cmd_prefix() + [
            "iptables", "-D", "INPUT",
            "-p", protocol,
            "--dport", str(port),
            "-j", "DROP",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            # Idempotent: swallow timeout on delete.
            return
        # Non-zero return code is also swallowed (rule may not exist).


# ---------------------------------------------------------------------------
# Injector
# ---------------------------------------------------------------------------


class CommDisruptionInjector(AttackInjector):
    """Drop UDP traffic on the target UAV's MAVLink telemetry port."""

    name_: str = "comm_disruption"

    # MAVLink port for PX4 SITL instance i is 14540 + (sysid - 1).
    DEFAULT_PORT_BASE: int = 14540

    def __init__(
        self,
        *,
        runner: Optional[IptablesRunner] = None,
        explicit_port: Optional[int] = None,
        port_base: int = DEFAULT_PORT_BASE,
    ) -> None:
        if explicit_port is not None and explicit_port <= 0:
            raise ValueError("explicit_port must be positive")
        self._runner: IptablesRunner = runner or SubprocessIptablesRunner()
        self._explicit_port = explicit_port
        self._port_base = port_base
        self._target_port: Optional[int] = None
        self._armed: bool = False
        self._fired: bool = False

    @property
    def name(self) -> str:
        return self.name_

    @property
    def target_port(self) -> Optional[int]:
        return self._target_port

    async def arm(self, ctx: AttackContext) -> None:
        # Derive target port from sysid unless caller pinned one.
        if self._explicit_port is not None:
            self._target_port = self._explicit_port
        else:
            self._target_port = self._port_base + (ctx.target_sysid - 1)
        self._armed = True

    async def fire(self) -> None:
        if not self._armed or self._target_port is None:
            raise RuntimeError("fire() called before arm()")
        await self._runner.add_drop_rule(port=self._target_port)
        self._fired = True

    async def cleanup(self) -> None:
        # cleanup runs from try/finally — must tolerate any prior state.
        if self._target_port is None:
            return  # arm() never ran
        try:
            await self._runner.delete_drop_rule(port=self._target_port)
        except Exception:
            # Idempotent by contract; ignore.
            pass
