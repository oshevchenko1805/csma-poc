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

ParamWriter seam (step 10e)
---------------------------
A param-writing attack (gps_spoofing) needs to set a PX4 param while
the target is flying, but during flight the mission owns the only
MAVSDK connection to that UAV (the UDP fan-out port is bound; a second
client can't attach). So the attack does not open its own connection —
the experiment layer hands it a `ParamWriter` in AttackContext, backed
by the live mission controller. The attack layer only depends on this
small Protocol; the mission layer provides the concrete implementation.

MonitorHandle seam (monitor_takeout)
------------------------------------
An attack on the defensive perimeter (monitor_takeout) needs to stop
the monitors of the target's failure domain — modelling loss of the
observation contour (thesis Table 3.10, Detection capability row). The
attack must not import runners/, so the experiment layer hands it the
live monitors as `MonitorHandle` objects in AttackContext. The attack
selects its victims structurally by `failure_domain`; there is no
`if architecture` branching — architecture A's monitors share the
`ground_station` domain, so disabling that domain drops all of them
(single point of failure), while B/C's per-UAV domains drop only the
target's monitor. The divergence in detection across A/B/C therefore
falls out of the shared domain model, not out of attack-side branching.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol


class ParamWriter(Protocol):
    """Minimal PX4 param read/write capability an attack may need.

    Implemented by the mission layer (backed by a live MAVSDK
    connection) and passed to the attack via AttackContext. Structural
    typing: anything with these two coroutines satisfies it.
    """

    async def get_param_float(self, name: str) -> float: ...

    async def set_param_float(self, name: str, value: float) -> None: ...


class MonitorHandle(Protocol):
    """Minimal view of a fleet monitor an attack may need to disable.

    Implemented by runners.monitor.Monitor. The attack layer depends
    only on this Protocol so attacks/ never imports runners/. Structural
    typing: any object exposing these two read attributes and a
    synchronous stop() satisfies it.

    - uav_id:          the UAV this monitor watches.
    - failure_domain:  the shared failure domain (arch A: a single
                       'ground_station' for all monitors; B/C: per-UAV).
    - stop():          synchronous, idempotent teardown of the monitor
                       (sets its stop event, stops the listener, joins
                       its threads, closes its logger). After it the
                       monitor no longer detects or publishes.
    """

    uav_id: str
    failure_domain: str

    def stop(self) -> None: ...

    def disable_local_detectors(self) -> None: ...


@dataclass
class AttackContext:
    """What the runner hands to the injector at arm() time."""

    target_uav: str
    target_sysid: int
    log_dir: Path
    extra: dict = field(default_factory=dict)
    # Optional PX4 param channel for the target UAV. Present only when the
    # mission runner can provide one (real MAVSDK flight); None otherwise
    # (e.g. NullMissionRunner). Only param-writing attacks use it.
    param_writer: Optional[ParamWriter] = None
    # Live fleet monitors, provided by the experiment layer. Present for
    # real runs; empty for contexts built without a fleet. Only attacks
    # that disable the observation contour (monitor_takeout) read it. A
    # tuple so an attack cannot mutate the fleet's monitor list.
    monitors: tuple[MonitorHandle, ...] = ()


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
