"""
SequentialAttackInjector — compose several attacks into one run.

The ExperimentRunner drives exactly one AttackInjector per run (arm ->
fire -> cleanup). Scenarios like detector_takeout followed by
gps_spoofing need two effects in one run: first silence the target
monitor's local detectors, then apply the spoof, and measure whether
detection survives. Rather than teach the runner about a pre-phase
(which would push scenario logic into the orchestrator), we compose the
injectors: SequentialAttackInjector is itself an AttackInjector that
holds an ordered list of children and drives them.

This keeps the project's discipline intact — composition and DI, not
special cases in the runner. The runner stays a single generic
arm/fire/cleanup path; the composite is just another injector.

Ordering
--------
- arm():     children are armed in list order, all with the SAME
             AttackContext (it already carries monitors, param_writer
             and target, so every child gets what it needs).
- fire():    children fire in list order. For detector_takeout ->
             gps_spoofing that means "blind the local detector, then
             spoof".
- cleanup(): children are cleaned in REVERSE order. This matters:
             gps_spoofing's cleanup restores the PX4 param over the live
             mission connection and must run before the mission is torn
             down — ExperimentRunner already runs attack.cleanup() before
             mission.abort(), and reverse order keeps the param-restoring
             child (added last, fired last) cleaned first. cleanup is
             best-effort per child: one child's failure does not stop the
             others (mirrors ExperimentRunner._cleanup_attack).

Naming
------
The composite's name defaults to the '+'-joined child names
(e.g. 'detector_takeout+gps_spoofing'). The analyzer groups runs by
(architecture, attack_type) and treats the name purely as a label — it
does not parse it — so a composite name is a clean, distinct row in the
Chapter 5 tables. An explicit name can be passed if a shorter label is
wanted.
"""

from __future__ import annotations

from typing import Iterable, Optional

from attacks.base import AttackContext, AttackInjector


class SequentialAttackInjector(AttackInjector):
    """Run several AttackInjectors as one: fire in order, clean in reverse."""

    def __init__(
        self,
        children: Iterable[AttackInjector],
        *,
        name: Optional[str] = None,
    ) -> None:
        self._children: list[AttackInjector] = list(children)
        if not self._children:
            raise ValueError(
                "SequentialAttackInjector needs at least one child injector"
            )
        self._name = (
            name
            if name is not None
            else "+".join(c.name for c in self._children)
        )
        self._armed: bool = False
        self._fired: bool = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def children(self) -> tuple[AttackInjector, ...]:
        return tuple(self._children)

    async def arm(self, ctx: AttackContext) -> None:
        # Arm in order, all with the same context. A child raising here
        # propagates; the runner then calls our cleanup(), which cleans
        # every child (each child's cleanup is safe pre-fire).
        for child in self._children:
            await child.arm(ctx)
        self._armed = True

    async def fire(self) -> None:
        if not self._armed:
            raise RuntimeError(
                "SequentialAttackInjector.fire() called before arm()"
            )
        # Fire in order. A child raising propagates so the runner sees the
        # error; cleanup() (run by the runner's finally) still tears down
        # every child.
        for child in self._children:
            await child.fire()
        self._fired = True

    async def cleanup(self) -> None:
        # Reverse order, best-effort. The last-fired child (e.g. the
        # param-restoring gps_spoofing) is cleaned first, while the
        # mission connection is still live.
        for child in reversed(self._children):
            try:
                await child.cleanup()
            except Exception:
                # One child's cleanup failure must not block the others.
                pass
