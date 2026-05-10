"""
AttackInjector contract.

An AttackInjector represents the adversary's action during one
experiment run. It is invoked once by the experiment runner at the
configured `attack_at_sec` offset; concrete attack modules (step 9)
implement `arm`, `fire`, `cleanup` against PX4 / iptables / MAVLink.

Lifecycle
---------
- arm(target_uav, fleet_context)  → called once before run start
  (e.g. preload iptables chain, open MAVLink injection socket)
- fire()                          → called at attack_at_sec.
  Must complete quickly (target effect online); long-running
  background side effects (e.g. continuous spoofing) start a
  daemon thread inside fire().
- cleanup()                       → called at end of run, ALWAYS,
  even on exception. Must restore the pre-arm state (delete
  iptables rule, close socket, kill spoofer thread).

Why a class, not a function
---------------------------
- Concrete attacks (command_injection, gps_spoofing) have setup state
  that lives across the fire-then-wait observation window.
- Separating arm/fire/cleanup gives a clear hook for cleanup-on-error
  in the runner (try / finally).
- An injector instance is single-use per run — instantiate fresh
  for each experiment run.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class AttackContext:
    """What the runner hands to the injector at arm() time."""

    target_uav: str
    target_sysid: int
    log_dir: Path
    extra: dict = field(default_factory=dict)


class AttackInjector(ABC):
    """Single-use adversary action for one experiment run."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable name (e.g. 'comm_disruption'). Goes into AttackEvent."""

    @abstractmethod
    async def arm(self, ctx: AttackContext) -> None:
        """Prepare resources but don't have effect yet."""

    @abstractmethod
    async def fire(self) -> None:
        """Cause the attack effect. Must return promptly."""

    @abstractmethod
    async def cleanup(self) -> None:
        """Tear everything down. Must be idempotent."""


class NullAttackInjector(AttackInjector):
    """No-op injector for baseline (no-attack) runs.

    Used so the runner can have one code path: build injector, arm,
    fire, cleanup. For baseline runs, build a Null and nothing happens
    except the AttackEvent ground-truth marker which the runner emits
    around fire().
    """

    name_: str = "none"

    @property
    def name(self) -> str:
        return self.name_

    async def arm(self, ctx: AttackContext) -> None:
        return None

    async def fire(self) -> None:
        return None

    async def cleanup(self) -> None:
        return None
