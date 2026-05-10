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

    def __init__(self) -> None:
        self._filtered: set[str] = set()
        self._lock = threading.Lock()

    async def execute(
        self, request: RecoveryRequest
    ) -> tuple[bool, Optional[str]]:
        if not request.target_uav:
            return False, "empty target_uav"
        with self._lock:
            self._filtered.add(request.target_uav)
        return True, None

    # ----- queries / cleanup -----

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
