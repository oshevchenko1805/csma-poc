"""
detector_takeout — attack on node-local detection, mesh left intact.

This is the companion to monitor_takeout and the sharper of the two: it
isolates the marginal value of Architecture C's mesh (security context
sharing via cross_check), which the raw 3x4 matrix cannot show because
there the local gps detector already catches the spoof on every
architecture (detection is 100% everywhere, so the mesh looks
redundant).

Threat model
------------
An adversary compromises the *node-local* intrusion detection on the
target UAV (disables its telemetry-driven detectors), but the UAV keeps
broadcasting its telemetry and position — it must, to stay in formation
and remain controllable. So the local detection layer is blind, yet the
peer-position announcements the mesh depends on keep flowing.

Predicted outcome (this is what the smoke test must confirm)
------------------------------------------------------------
Against the same GPS spoof, with the target monitor's local detectors
silenced but the monitor otherwise alive:
  - A (centralised): the target's local detector is off; no mesh.
    -> target undetected.
  - B (segmented):   the target's local detector is off; no mesh.
    -> target undetected.
  - C (CSMA):        the target's local detector is off, but neighbours
    run cross_check over the still-published peer positions and catch
    the kinematically implausible spoof.
    -> target detected.

That is a clean three-way split (C detects, A and B do not) from a
single scenario, and it directly evidences the thesis claim (3.4.5,
Table 3.10) that distributed local-first detection with security
context sharing catches what a segmented node misses. It does not
depend on tuning the spoof magnitude into a narrow gap — at the
existing 50 m offset cross_check is already shown (in runs_v1) to fire
against the target.

Design discipline
-----------------
No architecture branching. The injector silences the single monitor
whose uav_id == target_uav; detection of the target only ever came from
that monitor, so this is the minimal, architecture-agnostic action. The
A/B-vs-C divergence is a consequence of whether a mesh + cross_check is
wired (a DI/config choice in the factory), not of anything here.

Mechanics
---------
- arm():   capture the live monitors + target from AttackContext.
- fire():  disable the local detectors of the target's monitor. The
           call is cheap (takes the monitor's detector lock, clears its
           detector list) so it runs inline — unlike monitor_takeout's
           stop(), it joins no threads.
- cleanup(): no-op. The detectors stay disabled for the rest of the
           run by design; the run then tears down normally.
"""

from __future__ import annotations

from typing import Optional

from attacks.base import AttackContext, AttackInjector, MonitorHandle


class DetectorTakeoutInjector(AttackInjector):
    """Silence the local detectors of the target's monitor mid-flight."""

    name_: str = "detector_takeout"

    def __init__(self) -> None:
        self._monitors: tuple[MonitorHandle, ...] = ()
        self._target_uav: Optional[str] = None
        self._armed: bool = False
        self._fired: bool = False
        self._disabled_uavs: list[str] = []

    @property
    def name(self) -> str:
        return self.name_

    @property
    def disabled_uavs(self) -> list[str]:
        """UAV ids whose local detectors this injector silenced (post-fire)."""
        return list(self._disabled_uavs)

    async def arm(self, ctx: AttackContext) -> None:
        self._monitors = tuple(ctx.monitors)
        self._target_uav = ctx.target_uav
        self._armed = True

    async def fire(self) -> None:
        if not self._armed:
            raise RuntimeError("detector_takeout.fire() called before arm()")

        victims = [
            m for m in self._monitors if m.uav_id == self._target_uav
        ]
        if not victims:
            raise RuntimeError(
                f"detector_takeout: no monitor watches target "
                f"{self._target_uav!r} (monitors present: "
                f"{[m.uav_id for m in self._monitors]!r}). Was the injector "
                f"given a real fleet via AttackContext.monitors?"
            )

        for m in victims:
            m.disable_local_detectors()

        self._disabled_uavs = [m.uav_id for m in victims]
        self._fired = True

    async def cleanup(self) -> None:
        # No-op by design: local detectors stay disabled for the rest of
        # the run. See module docstring.
        return None
