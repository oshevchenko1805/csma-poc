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

    heartbeat_loss        (none - see REASON_TO_ACTION)
    command_injection     filter_commands
    gps_anomaly           mode_loiter
    cross_check_anomaly   mode_loiter

These are documented in Chapter 4 alongside the attack-detection table.
The mapping table is module-level so other code (tests, monitors) can
inspect or override it.

Recovery policies (review stage 3, 2026-09-26)
----------------------------------------------
The table above is the `proportionate` policy and stays the default:
every existing configuration and run is unchanged. Two further tables
are selected by `recovery.policy` in the architecture YAML — a config
value, never an architecture branch:

    proportionate   the table above (LOITER on position anomalies)
    trust_aware     position anomalies -> hold_zero_velocity
    detect_only     no recovery action for any reason (ablation arm)

`trust_aware` chooses the action by which information the attack has
compromised. gps_anomaly and cross_check_anomaly both mean the position
estimate is no longer trustworthy; LOITER holds that very estimate and
is dragged by it (~50 m, review P1). A zero-velocity hold does not use
the position estimate. command_injection leaves the estimate intact, so
its action is unchanged.

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
    HOLD_ZERO_VELOCITY = "hold_zero_velocity"


class RecoveryPolicy:
    PROPORTIONATE = "proportionate"
    TRUST_AWARE = "trust_aware"
    DETECT_ONLY = "detect_only"


REASON_TO_ACTION: dict[str, str] = {
    # heartbeat_loss deliberately maps to NO action.
    #
    # Measured in pass 1 (N=5, architecture C): answering heartbeat loss
    # with restart_process cost 36.65 +- 11.73 m of mission deviation and
    # dropped residual mission function to 0.73, while A and B, which take
    # no recovery action at all, stayed on plan (1.95 m / 0.74 m, residual
    # 1.00). Loss of heartbeat means the node is unreachable, not
    # compromised; a destructive automated response is not warranted on
    # that signal alone. Detection, isolation and the mesh announcement
    # still happen — only the destructive action is withheld.
    #
    # The superseded mapping is kept in COARSE_POLICY_REASON_TO_ACTION
    # below for the policy comparison in Chapter 4.
    "command_injection": RecoveryAction.FILTER_COMMANDS,
    "gps_anomaly": RecoveryAction.MODE_LOITER,
    "cross_check_anomaly": RecoveryAction.MODE_LOITER,
}


# Superseded policy, retained for the Chapter 4 comparison of a coarse
# (destructive) recovery policy against a proportionate one. Not used by
# RecoveryDecider; restore by merging it into REASON_TO_ACTION.
COARSE_POLICY_REASON_TO_ACTION: dict[str, str] = {
    "heartbeat_loss": RecoveryAction.RESTART_PROCESS,
}


# Position-trust-aware policy (review stage 3). heartbeat_loss keeps NO
# action — the pass-1 regression guard applies to every policy.
TRUST_AWARE_REASON_TO_ACTION: dict[str, str] = {
    "command_injection": RecoveryAction.FILTER_COMMANDS,
    "gps_anomaly": RecoveryAction.HOLD_ZERO_VELOCITY,
    "cross_check_anomaly": RecoveryAction.HOLD_ZERO_VELOCITY,
}

# Ablation arm: detection, isolation and the mesh announcement happen as
# in every C run; no recovery action is requested.
DETECT_ONLY_REASON_TO_ACTION: dict[str, str] = {}

POLICY_TABLES: dict[str, dict[str, str]] = {
    RecoveryPolicy.PROPORTIONATE: REASON_TO_ACTION,
    RecoveryPolicy.TRUST_AWARE: TRUST_AWARE_REASON_TO_ACTION,
    RecoveryPolicy.DETECT_ONLY: DETECT_ONLY_REASON_TO_ACTION,
}


def _policy_table(policy: str) -> dict[str, str]:
    try:
        return POLICY_TABLES[policy]
    except KeyError:
        raise ValueError(
            f"unknown recovery policy {policy!r}; "
            f"expected one of {sorted(POLICY_TABLES)}"
        ) from None


def action_for_reason(
    reason: str, policy: str = RecoveryPolicy.PROPORTIONATE
) -> Optional[str]:
    """Look up the recovery action for a reason under a policy.

    None if the policy assigns no action to the reason. Raises ValueError
    for an unknown policy.
    """
    return _policy_table(policy).get(reason)


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
    policy     Name of the reason -> action table (POLICY_TABLES).
               Default 'proportionate' = the historical behaviour.
    """

    def __init__(
        self,
        source: str,
        *,
        enabled: bool,
        policy: str = RecoveryPolicy.PROPORTIONATE,
    ) -> None:
        _policy_table(policy)  # fail fast on an unknown policy
        self._source = source
        self._enabled = enabled
        self._policy = policy
        self._requested: set[str] = set()

    # ----- main API -----

    def evaluate(
        self, announcement: IsolationAnnounce
    ) -> Optional[RecoveryRequest]:
        if not self._enabled:
            return None
        if not announcement.target_uav:
            return None

        action = action_for_reason(announcement.reason, self._policy)
        if action is None:
            return None  # policy assigns no action to this reason

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

    @property
    def policy(self) -> str:
        return self._policy

    def is_recovery_requested(self, uav_id: str) -> bool:
        return uav_id in self._requested

    @property
    def requested_uavs(self) -> frozenset[str]:
        return frozenset(self._requested)
