"""
Event types for the CSMA PoC.

All events flow through this module. Three transport contexts use them:
  1. Local in-process queues (telemetry -> detectors -> decision).
  2. JSONL log files (post-hoc analysis, metrics computation).
  3. Mesh-bus (security events, isolation announcements, recovery messages
     across UAV peers; only active in Architecture C).

Design choices:
  - Wall-clock timestamps via time.time(). Monotonic clocks are not used
    because cross-process comparison is required and the experiment runs
    on a single machine where wall clocks are coherent. Documented as
    a PoC assumption in Chapter 4.
  - Each event has a UUID4 event_id and an optional caused_by reference,
    enabling causal tracing through the JSONL logs (e.g. SecurityEvent ->
    IsolationAnnounce -> RecoveryRequest -> RecoveryAck).
  - Events are flat dataclasses, registered by event_type for round-trip
    JSON serialization.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


# ----------------------------------------------------------------------------
# Registry for round-trip (de)serialization
# ----------------------------------------------------------------------------

_EVENT_REGISTRY: dict[str, type] = {}


def _register(cls: type) -> type:
    """Register an event class by its event_type default value."""
    fields_map = cls.__dataclass_fields__  # type: ignore[attr-defined]
    if "event_type" not in fields_map:
        raise TypeError(f"{cls.__name__} is missing the event_type field")
    type_default = fields_map["event_type"].default
    if not isinstance(type_default, str):
        raise TypeError(f"{cls.__name__}.event_type must have a string default")
    _EVENT_REGISTRY[type_default] = cls
    return cls


# ----------------------------------------------------------------------------
# Base
# ----------------------------------------------------------------------------


@dataclass(kw_only=True)
class BaseEvent:
    """
    Common envelope shared by every event.

    Attributes
    ----------
    event_id     UUID4 identifying this exact event.
    timestamp    UTC wall-clock seconds (time.time()).
    source       Originating process. Examples: 'monitor_uav_0',
                 'monitor_gs', 'attacker', 'experiment_orchestrator'.
    event_type   Discriminator used by the registry.
    caused_by    Optional event_id of the parent/causing event,
                 enabling causal tracing in post-hoc analysis.
    """

    source: str
    event_type: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    caused_by: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


# ----------------------------------------------------------------------------
# Concrete events
# ----------------------------------------------------------------------------


@_register
@dataclass(kw_only=True)
class TelemetryEvent(BaseEvent):
    """
    Single MAVLink message captured by a monitor.

    uav_id is the UAV the telemetry describes (may differ from `source`,
    which is the process that captured it).
    """

    event_type: str = "telemetry"
    uav_id: str = ""
    msg_type: str = ""  # e.g. 'HEARTBEAT', 'GLOBAL_POSITION_INT'
    data: dict[str, Any] = field(default_factory=dict)


@_register
@dataclass(kw_only=True)
class SecurityEvent(BaseEvent):
    """
    Anomaly raised by a detector.

    detector     'heartbeat' | 'gps' | 'command' | 'cross_check'
    target_uav   The UAV the anomaly is about.
    severity     'low' | 'medium' | 'high'
    evidence     Raw values supporting the detection (e.g. residual ratios,
                 missing heartbeat duration, rejected sysid).
    """

    event_type: str = "security"
    detector: str = ""
    target_uav: str = ""
    severity: str = "medium"
    evidence: dict[str, Any] = field(default_factory=dict)


@_register
@dataclass(kw_only=True)
class IsolationAnnounce(BaseEvent):
    """
    A monitor announces it is isolating a UAV.

    In Architecture B this is logged locally only. In Architecture C it is
    published on the mesh-bus so peers can correlate and coordinate.
    """

    event_type: str = "isolation_announce"
    target_uav: str = ""
    reason: str = ""
    decided_by: str = ""  # which monitor took the decision


@_register
@dataclass(kw_only=True)
class RecoveryRequest(BaseEvent):
    """
    A request to perform a recovery action.

    Only emitted in Architecture C (recovery enabled). The coordinator
    issues this; the executor on the target node carries it out.
    """

    event_type: str = "recovery_request"
    target_uav: str = ""
    action: str = ""  # 'restart_process' | 'mode_loiter' | 'filter_commands'
    requester: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)


@_register
@dataclass(kw_only=True)
class RecoveryAck(BaseEvent):
    """Result of a recovery action execution."""

    event_type: str = "recovery_ack"
    target_uav: str = ""
    action: str = ""
    success: bool = False
    executor: str = ""
    error: Optional[str] = None


@_register
@dataclass(kw_only=True)
class AttackEvent(BaseEvent):
    """
    Ground-truth marker emitted by the attack-injection process.

    Used to compute MTTD precisely (time between attack_inject_start and
    the first SecurityEvent identifying the same target_uav).
    """

    event_type: str = "attack"
    attack_type: str = ""  # 'comm_disruption' | 'command_injection' | 'gps_spoofing'
    target_uav: str = ""
    phase: str = ""  # 'inject_start' | 'inject_active' | 'inject_end'
    parameters: dict[str, Any] = field(default_factory=dict)


@_register
@dataclass(kw_only=True)
class MissionEvent(BaseEvent):
    """Marker for mission lifecycle (start, waypoint reached, completed, aborted)."""

    event_type: str = "mission"
    phase: str = ""  # 'start' | 'waypoint_reached' | 'completed' | 'aborted'
    waypoint_index: Optional[int] = None
    uav_id: Optional[str] = None


@_register
@dataclass(kw_only=True)
class PeerPositionAnnounce(BaseEvent):
    """
    Mesh-broadcast position announcement.

    In Architecture C, every monitor periodically publishes its UAV's
    last reported GPS position on the mesh. Peers consume these to
    perform cross-checks (e.g. kinematic feasibility — did UAV-2 move
    further than physically possible since its last announcement?).

    Not a SecurityEvent — this is normal coordination traffic, not an
    anomaly report. Architectures A and B do not produce these events.

    sample_timestamp is the wall-clock time the position was sampled
    on the announcing UAV; the BaseEvent.timestamp is when the
    announcement itself was emitted. The cross-check detector uses
    sample_timestamp for kinematic computations to avoid mesh-latency
    bias.
    """

    event_type: str = "peer_position"
    uav_id: str = ""
    lat: float = 0.0  # degrees
    lon: float = 0.0  # degrees
    alt: float = 0.0  # meters above mean sea level
    sample_timestamp: float = 0.0


# ----------------------------------------------------------------------------
# Deserialization
# ----------------------------------------------------------------------------


def event_from_dict(d: dict[str, Any]) -> BaseEvent:
    """
    Reconstruct a typed event from its dict form.

    Raises ValueError if the event_type is unknown.
    """
    et = d.get("event_type")
    if et not in _EVENT_REGISTRY:
        raise ValueError(f"Unknown event_type: {et!r}")
    cls = _EVENT_REGISTRY[et]
    return cls(**d)


def event_from_json(s: str) -> BaseEvent:
    return event_from_dict(json.loads(s))


def known_event_types() -> list[str]:
    """For tests and diagnostics."""
    return sorted(_EVENT_REGISTRY.keys())
