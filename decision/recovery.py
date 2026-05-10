"""
Recovery decider.

Given an IsolationAnnounce, decide what recovery action to request,
and emit a RecoveryRequest. Only active in Architecture C (mesh +
self-healing); A and B leave recovery disabled and the decider
short-circuits to None.

State
-----
Tracks UAVs for which a RecoveryRequest has already been issued. A
second IsolationAnnounce for the same UAV does not produce a duplicate
recovery request. The host monitor calls `clear()` on a successful
RecoveryAck — implemented as `mark_recovered()` — to permit subsequent
recoveries.

Reason -> action mapping
------------------------
Each IsolationAnnounce.reason maps to one canonical recovery action:

    heartbeat_loss        restart_process
    command_injection     filter_commands
    gps_anomaly           mode_loiter
    cross_check_anomaly   mode_loiter

These are documented in Chapter 4 alongside the attack-detection table.
The mapping table is module-level so other code (tests, monitors) can
inspect or override it.

Causal chain
------------
RecoveryRequest.caused_by is the IsolationAnnounce.event_id, which in
turn is caused_by the original SecurityEvent. Full chain reconstructible
from the JSONL log.
"""

from __future__ import annotations

from typing import Optional

from core.events import IsolationAnnounce, RecoveryRequest


# Canonical action names. Used by RecoveryExecutor (step 7.3) to dispatch.
class RecoveryAction:
    RESTART_PROCESS = "restart_process"
    FILTER_COMMANDS = "filter_commands"
    MODE_LOITER = "mode_loiter"


REASON_TO_ACTION: dict[str, str] = {
    "heartbeat_loss": RecoveryAction.RESTART_PROCESS,
    "command_injection": RecoveryAction.FILTER_COMMANDS,
    "gps_anomaly": RecoveryAction.MODE_LOITER,
    "cross_check_anomaly": RecoveryAction.MODE_LOITER,
}


def action_for_reason(reason: str) -> Optional[str]:
    """Look up the canonical recovery action for a reason. None if unknown."""
    return REASON_TO_ACTION.get(reason)


class RecoveryDecider:
    """
    Decide whether an IsolationAnnounce yields a RecoveryRequest.

    Parameters
    ----------
    source     Process identifier emitted as RecoveryRequest.source and
               .requester. In Architecture C this is the elected
               coordinator (e.g. 'coordinator_uav_0').
    enabled    False for Architectures A and B — short-circuits all
               evaluations to None. True for C.
    """

    def __init__(self, source: str, *, enabled: bool) -> None:
        self._source = source
        self._enabled = enabled
        self._requested: set[str] = set()

    # ----- main API -----

    def evaluate(
        self, announcement: IsolationAnnounce
    ) -> Optional[RecoveryRequest]:
        if not self._enabled:
            return None
        if not announcement.target_uav:
            return None

        action = action_for_reason(announcement.reason)
        if action is None:
            return None  # unknown reason -> no canonical recovery action

        if announcement.target_uav in self._requested:
            return None  # recovery already requested

        self._requested.add(announcement.target_uav)
        return RecoveryRequest(
            source=self._source,
            target_uav=announcement.target_uav,
            action=action,
            requester=self._source,
            caused_by=announcement.event_id,
        )

    def mark_recovered(self, uav_id: str) -> None:
        """
        Mark a UAV as recovered so the next IsolationAnnounce for that UAV
        can produce a fresh RecoveryRequest. Idempotent.
        """
        self._requested.discard(uav_id)

    def reset(self) -> None:
        """Clear all state. Called between experiment runs."""
        self._requested.clear()

    # ----- diagnostics -----

    @property
    def enabled(self) -> bool:
        return self._enabled

    def is_recovery_requested(self, uav_id: str) -> bool:
        return uav_id in self._requested

    @property
    def requested_uavs(self) -> frozenset[str]:
        return frozenset(self._requested)
