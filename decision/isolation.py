"""
Isolation decider.

Pure decision logic: given a SecurityEvent from a detector, return an
IsolationAnnounce if the target UAV should be isolated, or None if no
new action is needed.

This is intentionally trivial in the PoC — any SecurityEvent at or
above a configured severity threshold triggers isolation. A real
deployment would use a score-based policy with weight per-detector and
hysteresis windows; that policy is documented as the next step beyond
the PoC in Chapter 6.

State
-----
The decider remembers which UAVs are currently isolated. A second
SecurityEvent for an already-isolated UAV does not produce a fresh
IsolationAnnounce. When recovery succeeds the host monitor calls
clear(uav_id) — implemented as `un_isolate()` — to allow the next
detection to fire.

Architecture independence
-------------------------
The decider does not know about A / B / C — it produces an announcement
event the same way regardless. What changes per architecture is who
*receives* the announcement (mesh vs local) and what the *enforcer*
does with it. Keeping that knowledge out of the decider preserves the
"architecture difference is deployment" principle.

Causal chain
------------
IsolationAnnounce.caused_by is set to the triggering SecurityEvent's
event_id, enabling end-to-end tracing in post-hoc JSONL analysis:
SecurityEvent -> IsolationAnnounce -> RecoveryRequest -> RecoveryAck.
"""

from __future__ import annotations

from typing import Optional

from core.events import IsolationAnnounce, SecurityEvent


# Map a detector name (SecurityEvent.detector) onto the canonical reason
# string carried in IsolationAnnounce.reason. RecoveryDecider, in turn,
# maps reason -> action.
_DETECTOR_TO_REASON: dict[str, str] = {
    "heartbeat": "heartbeat_loss",
    "command": "command_injection",
    "gps": "gps_anomaly",
    "cross_check": "cross_check_anomaly",
}


# Severity ordering used for the threshold check. Higher index = more
# severe. Anything < threshold is ignored.
_SEVERITY_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def reason_for_detector(detector: str) -> str:
    """Map detector name to canonical reason string. Unknown -> detector itself."""
    return _DETECTOR_TO_REASON.get(detector, detector)


class IsolationDecider:
    """
    Decide whether a SecurityEvent triggers a new IsolationAnnounce.

    Parameters
    ----------
    source                Process identifier emitted as
                          IsolationAnnounce.source.
    severity_threshold    Minimum severity to act on. Default 'medium' —
                          'low' is reserved for future advisory signals.
    """

    DEFAULT_SEVERITY_THRESHOLD: str = "medium"

    def __init__(
        self,
        source: str,
        *,
        severity_threshold: str = DEFAULT_SEVERITY_THRESHOLD,
    ) -> None:
        if severity_threshold not in _SEVERITY_ORDER:
            raise ValueError(
                f"unknown severity {severity_threshold!r}; "
                f"choose from {sorted(_SEVERITY_ORDER)}"
            )
        self._source = source
        self._threshold_idx = _SEVERITY_ORDER[severity_threshold]
        self._isolated: set[str] = set()

    # ----- main API -----

    def evaluate(self, event: SecurityEvent) -> Optional[IsolationAnnounce]:
        if not event.target_uav:
            return None

        sev_idx = _SEVERITY_ORDER.get(event.severity, -1)
        if sev_idx < self._threshold_idx:
            return None

        if event.target_uav in self._isolated:
            return None  # already isolated; no fresh announcement

        self._isolated.add(event.target_uav)
        return IsolationAnnounce(
            source=self._source,
            target_uav=event.target_uav,
            reason=reason_for_detector(event.detector),
            decided_by=self._source,
            caused_by=event.event_id,
        )

    def un_isolate(self, uav_id: str) -> None:
        """
        Mark a UAV as no longer isolated.

        Called by the host monitor on a successful RecoveryAck so the
        next detection can fire a fresh IsolationAnnounce. Idempotent:
        un-isolating an already-not-isolated UAV is a silent no-op.
        """
        self._isolated.discard(uav_id)

    def reset(self) -> None:
        """Clear all state. Called between experiment runs."""
        self._isolated.clear()

    # ----- diagnostics -----

    def is_isolated(self, uav_id: str) -> bool:
        return uav_id in self._isolated

    @property
    def isolated_uavs(self) -> frozenset[str]:
        return frozenset(self._isolated)
