"""
monitor_takeout — attack on the defensive perimeter.

Where the payload attacks (comm_disruption, command_injection,
gps_spoofing) strike a *useful* UAV, this attack strikes the
*observation contour* itself: it stops the monitors that watch the
target's failure domain. It exists to test empirically the claim made
in the thesis (Table 3.10, Detection capability row):

  - Architecture A (centralised): all monitors share one failure
    domain ('ground_station'), so disabling that domain removes the
    entire detection contour — the single point of failure the model
    predicts. Detection of a subsequent incident is expected to
    collapse.
  - Architecture B (segmented, no mesh): each monitor is its own
    per-UAV domain. Disabling the target's monitor removes local
    detection for that UAV; neighbours cannot compensate (no security
    context sharing).
  - Architecture C (CSMA): each monitor is its own per-UAV domain too,
    but neighbours share security context over the mesh (cross_check),
    so detection of the target is expected to survive the loss of its
    own monitor.

Design discipline
-----------------
The injector never branches on architecture. It resolves the target's
failure domain from the target's own monitor, then stops every monitor
that shares that domain. The A/B/C divergence is a consequence of how
the factory assigns `failure_domain` (shared vs per-UAV), not of any
attack-side logic. See attacks.base.MonitorHandle for the seam.

Mechanics
---------
- arm():   capture the live monitors + target from AttackContext.
- fire():  resolve the target's domain, stop every monitor in it. The
           stops run in a thread executor so the (synchronous, thread-
           joining) Monitor.stop() never blocks the experiment event
           loop — important for arch A where three monitors are stopped
           at once.
- cleanup(): no-op. The monitors stay down by design; the run is
           ending and the ExperimentRunner teardown calls stop() again
           (idempotent). Reviving the perimeter would defeat the point.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from attacks.base import AttackContext, AttackInjector, MonitorHandle


class MonitorTakeoutInjector(AttackInjector):
    """Disable the monitors of the target's failure domain mid-flight."""

    name_: str = "monitor_takeout"

    def __init__(self) -> None:
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

    async def arm(self, ctx: AttackContext) -> None:
        # Capture the live monitors and the target. We do NOT stop
        # anything here — arm() only prepares; the effect happens in
        # fire() at attack_at_sec.
        self._monitors = tuple(ctx.monitors)
        self._target_uav = ctx.target_uav
        self._armed = True

    async def fire(self) -> None:
        if not self._armed:
            raise RuntimeError("monitor_takeout.fire() called before arm()")

        domain = self._resolve_target_domain()
        victims = [m for m in self._monitors if m.failure_domain == domain]

        # Stop synchronously-joining monitors off the event loop so
        # mission telemetry keeps flowing while threads wind down.
        loop = asyncio.get_running_loop()
        await asyncio.gather(
            *(loop.run_in_executor(None, m.stop) for m in victims)
        )

        self._stopped_uavs = [m.uav_id for m in victims]
        self._target_domain = domain
        self._fired = True

    async def cleanup(self) -> None:
        # No-op by design: monitors remain stopped. The ExperimentRunner
        # teardown stops them again idempotently. See module docstring.
        return None

    # ----- internals -----

    def _resolve_target_domain(self) -> str:
        """Find the target's own monitor and return its failure domain.

        Raising here is intentional: monitor_takeout only makes sense
        when the runner supplied live monitors that include one watching
        the target. A missing target monitor is a misconfiguration, not
        something to silently swallow (mirrors gps_spoofing raising when
        no param_writer is present).
        """
        for m in self._monitors:
            if m.uav_id == self._target_uav:
                return m.failure_domain
        raise RuntimeError(
            f"monitor_takeout: no monitor watches target "
            f"{self._target_uav!r} (monitors present: "
            f"{[m.uav_id for m in self._monitors]!r}). Was the injector "
            f"given a real fleet via AttackContext.monitors?"
        )
