"""
monitor_takeout — attack on the defensive perimeter (blast radius / SPOF).

Where detector_takeout isolates the marginal value of the mesh, this
attack isolates the *blast radius* of compromising the host that runs a
monitor — i.e. it tests the single-point-of-failure claim the thesis
makes for Architecture A (Tables 3.9 / 3.10: A's security loop depends
on the availability of the central C2, so losing the centre takes the
whole loop with it).

Scenario
--------
The adversary compromises the host running the monitor of ONE UAV (the
`takeout_uav`), stopping every monitor that shares that host's failure
domain. Then a *different* UAV (the attack target) is GPS-spoofed. What
is measured is whether the target is still detected.

  - A (centralised): every monitor lives in the single 'ground_station'
    failure domain. Compromising the host of ANY monitor stops ALL of
    them — including the target's. -> target undetected.
  - B (segmented):   monitors are per-UAV failure domains. Only the
    takeout_uav's monitor dies; the target's monitor is untouched.
    -> target detected.
  - C (CSMA):        same per-UAV domains, plus mesh.
    -> target detected.

The action is IDENTICAL in all three architectures — compromise the host
of one monitor. That in A this removes three monitors and in B/C only
one is not an unfair handicap: it is the definition of a single point of
failure, and it is precisely the property under test. Nothing here
branches on architecture; the divergence comes from how the factory
assigns `failure_domain` (shared 'ground_station' vs per-UAV), which is
a pure config/DI choice.

Why the takeout target must differ from the attack target
---------------------------------------------------------
Taking out the *attack target's own* domain measures nothing: in A, B
and C alike the target's monitor dies, so the target goes undetected
everywhere (0%/0%/0%). In C it also silences the target's peer-position
publishing, blinding the neighbours' cross_check — C degrades to B for a
mechanical reason, not an architectural one. Attacking a *neighbour's*
domain is what exposes the blast radius: it leaves B/C's detection of
the target fully intact while collapsing A's.

(To silence the target's own detection while keeping the mesh signal
alive, use detector_takeout instead — a different threat model.)

Mechanics
---------
- arm():   capture the live monitors + attack target from AttackContext.
- fire():  resolve the failure domain of `takeout_uav` (defaults to the
           attack target when not given), stop every monitor sharing it.
           Stops run in a thread executor because Monitor.stop() is
           synchronous and joins threads — in arch A three monitors are
           stopped at once and the experiment event loop must keep
           servicing mission telemetry.
- cleanup(): no-op. The monitors stay down by design; the ExperimentRunner
           teardown calls stop() again (idempotent). Reviving the
           perimeter would defeat the point.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from attacks.base import AttackContext, AttackInjector, MonitorHandle


class MonitorTakeoutInjector(AttackInjector):
    """Stop every monitor sharing the failure domain of one chosen UAV."""

    name_: str = "monitor_takeout"

    def __init__(self, takeout_uav: Optional[str] = None) -> None:
        """
        takeout_uav: whose monitor's failure domain to take out. When
            None, falls back to the attack target from AttackContext
            (a pure perimeter-loss run). For the SPOF / blast-radius
            scenario this MUST be a UAV other than the attack target —
            see module docstring.
        """
        self._takeout_uav_arg = takeout_uav
        self._monitors: tuple[MonitorHandle, ...] = ()
        self._target_uav: Optional[str] = None
        self._armed: bool = False
        self._fired: bool = False
        self._stopped_uavs: list[str] = []
        self._target_domain: Optional[str] = None

    @property
    def name(self) -> str:
        return self.name_

    @property
    def stopped_uavs(self) -> list[str]:
        """UAV ids whose monitors this injector stopped (post-fire)."""
        return list(self._stopped_uavs)

    @property
    def target_domain(self) -> Optional[str]:
        """The failure domain that was taken out (post-fire)."""
        return self._target_domain

    @property
    def takeout_uav(self) -> Optional[str]:
        """The UAV whose domain gets taken out (resolved after arm())."""
        return self._takeout_uav_arg or self._target_uav

    async def arm(self, ctx: AttackContext) -> None:
        # Capture the live monitors and the attack target. Nothing is
        # stopped here — arm() only prepares; the effect is in fire().
        self._monitors = tuple(ctx.monitors)
        self._target_uav = ctx.target_uav
        self._armed = True

    async def fire(self) -> None:
        if not self._armed:
            raise RuntimeError("monitor_takeout.fire() called before arm()")

        domain = self._resolve_domain()
        victims = [m for m in self._monitors if m.failure_domain == domain]

        # Stop off the event loop: Monitor.stop() joins threads.
        loop = asyncio.get_running_loop()
        await asyncio.gather(
            *(loop.run_in_executor(None, m.stop) for m in victims)
        )

        self._stopped_uavs = [m.uav_id for m in victims]
        self._target_domain = domain
        self._fired = True

    async def cleanup(self) -> None:
        # No-op by design: monitors remain stopped. See module docstring.
        return None

    # ----- internals -----

    def _resolve_domain(self) -> str:
        """Return the failure domain of the UAV whose monitor we take out.

        Raising is intentional: monitor_takeout only makes sense when the
        runner supplied live monitors including one for that UAV. A
        missing monitor is a misconfiguration, not something to swallow.
        """
        whose = self.takeout_uav
        for m in self._monitors:
            if m.uav_id == whose:
                return m.failure_domain
        raise RuntimeError(
            f"monitor_takeout: no monitor watches {whose!r} "
            f"(monitors present: {[m.uav_id for m in self._monitors]!r}). "
            f"Was the injector given a real fleet via AttackContext.monitors?"
        )
