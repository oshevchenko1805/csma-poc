"""
FilterCommandsHandler — mark a UAV as command-filtered.

Used as the recovery action for MAVLink command injection. Conceptually,
"filter" means: drop further inbound commands directed at the target
UAV that arrive from non-whitelisted sources. The handler in this PoC
flips a state flag and exposes it via is_filtered(); the actual command
dropping is the responsibility of whatever transport sits between
attacker and PX4 (a MAVLink router rule, an iptables rule, or a
companion-computer firewall).

PoC simplification (Chapter 4)
------------------------------
Real production filtering would invoke iptables / mavlink-router on
the host. The dissertation explicitly notes this gap: the PoC
demonstrates *that the recovery decision is taken and signalled* but
not the kernel-level filter wiring. The recovery time (MTTR) measured
here is the decision-and-signalling time, not the iptables-apply time
which would add a tens-of-milliseconds round-trip.

Design
------
- Stateful and thread-safe: feed/clear from any thread.
- Public is_filtered(uav_id) and clear(uav_id) so a downstream
  component (or the experiment runner during cleanup) can read or
  reset the state.
- No DI seam needed — the entire effect lives in this handler.
"""

from __future__ import annotations

import threading
from typing import Optional

from core.events import RecoveryRequest
from enforcement.recovery import ActionHandler


class FilterCommandsHandler(ActionHandler):
    """State-flag handler for command-injection recovery."""

    def __init__(self, *, uav_id: Optional[str] = None, guard=None) -> None:
        # uav_id and guard are optional so existing unit tests that
        # construct FilterCommandsHandler() with no arguments still pass.
        # When a guard is provided (Architecture C wiring), execute()
        # actuates it: a real MAVLink sysid drop, not just a flag.
        self._uav_id = uav_id
        self._guard = guard
        self._resume_runner = None
        self._filtered: set[str] = set()
        self._lock = threading.Lock()

    async def execute(
        self, request: RecoveryRequest
    ) -> tuple[bool, Optional[str]]:
        if not request.target_uav:
            return False, "empty target_uav"
        with self._lock:
            self._filtered.add(request.target_uav)
        # Actuate the in-path guard so non-whitelisted commands to this
        # UAV are physically dropped from here on. start_filtering() only
        # sets a threading.Event, so it is safe from this handler's
        # (mesh-receiver thread) execution context.
        if self._guard is not None:
            self._guard.start_filtering()
        # Restore control: the first injected frame is delivered before it
        # can be detected, so it may have hijacked the flight mode before
        # the guard engaged. Re-command the mission so the target returns
        # to its route rather than loitering at the injected point. The
        # guard now drops any further injected frames, so one restore
        # holds. No-op when no resume runner is wired.
        if self._resume_runner is not None:
            try:
                await self._resume_runner.resume()
            except Exception as exc:
                return False, f"resume_failed:{exc}"
        return True, None

    # ----- queries / cleanup -----

    @property
    def target_uav(self) -> Optional[str]:
        return self._uav_id

    def set_resume_runner(self, runner) -> None:
        """Wire a mission-resume runner, called after the guard engages.

        Optional: without it, execute() only filters (Architectures with
        no live mission connection, and existing unit tests, are
        unaffected)."""
        self._resume_runner = runner

    def is_filtered(self, uav_id: str) -> bool:
        with self._lock:
            return uav_id in self._filtered

    def clear(self, uav_id: str) -> None:
        with self._lock:
            self._filtered.discard(uav_id)

    def reset(self) -> None:
        with self._lock:
            self._filtered.clear()

    @property
    def filtered_uavs(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._filtered)
