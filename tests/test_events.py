"""Tests for core.events."""

from __future__ import annotations

import json
import time

import pytest

from core.events import (
    AttackEvent,
    BaseEvent,
    IsolationAnnounce,
    MissionEvent,
    PeerPositionAnnounce,
    RecoveryAck,
    RecoveryRequest,
    SecurityEvent,
    TelemetryEvent,
    event_from_dict,
    event_from_json,
    known_event_types,
)


class TestRegistry:
    def test_all_event_types_registered(self):
        expected = {
            "telemetry",
            "security",
            "isolation_announce",
            "recovery_request",
            "recovery_ack",
            "attack",
            "mission",
            "peer_position",
        }
        assert set(known_event_types()) == expected

    def test_unknown_event_type_raises(self):
        with pytest.raises(ValueError, match="Unknown event_type"):
            event_from_dict({"event_type": "made_up", "source": "x"})


class TestBaseFields:
    def test_auto_event_id_is_unique(self):
        a = TelemetryEvent(source="m1", uav_id="uav_0", msg_type="HEARTBEAT")
        b = TelemetryEvent(source="m1", uav_id="uav_0", msg_type="HEARTBEAT")
        assert a.event_id != b.event_id
        assert len(a.event_id) == 36  # UUID4

    def test_auto_timestamp_is_now(self):
        before = time.time()
        ev = TelemetryEvent(source="m1", uav_id="uav_0", msg_type="HEARTBEAT")
        after = time.time()
        assert before <= ev.timestamp <= after

    def test_caused_by_defaults_none(self):
        ev = TelemetryEvent(source="m1", uav_id="uav_0", msg_type="HEARTBEAT")
        assert ev.caused_by is None


class TestSerialization:
    """Round-trip every event type. If a field is dropped or renamed, this fails."""

    @pytest.mark.parametrize(
        "event",
        [
            TelemetryEvent(
                source="monitor_uav_0",
                uav_id="uav_0",
                msg_type="GLOBAL_POSITION_INT",
                data={"lat": 473977418, "lon": 85455938, "alt": 488000},
            ),
            SecurityEvent(
                source="monitor_uav_1",
                detector="gps",
                target_uav="uav_1",
                severity="high",
                evidence={"pos_horiz_ratio": 1.42, "duration_sec": 2.3},
            ),
            IsolationAnnounce(
                source="monitor_uav_2",
                target_uav="uav_2",
                reason="gps_anomaly",
                decided_by="monitor_uav_2",
            ),
            RecoveryRequest(
                source="coordinator",
                target_uav="uav_2",
                action="mode_loiter",
                requester="coordinator",
                parameters={"timeout_sec": 30},
            ),
            RecoveryAck(
                source="enforcer_uav_2",
                target_uav="uav_2",
                action="mode_loiter",
                success=True,
                executor="enforcer_uav_2",
            ),
            AttackEvent(
                source="attacker",
                attack_type="gps_spoofing",
                target_uav="uav_2",
                phase="inject_start",
                parameters={"drift_m_per_s": 0.5, "direction_deg": 90},
            ),
            MissionEvent(
                source="experiment_orchestrator",
                phase="waypoint_reached",
                waypoint_index=2,
                uav_id="uav_0",
            ),
            PeerPositionAnnounce(
                source="monitor_uav_0",
                uav_id="uav_0",
                lat=47.397742,
                lon=8.545594,
                alt=508.0,
                sample_timestamp=1700000000.5,
            ),
        ],
    )
    def test_round_trip_dict(self, event: BaseEvent):
        d = event.to_dict()
        assert isinstance(d, dict)
        assert d["event_type"] == event.event_type
        rebuilt = event_from_dict(d)
        assert type(rebuilt) is type(event)
        assert rebuilt.to_dict() == d

    def test_round_trip_json(self):
        ev = SecurityEvent(
            source="monitor_uav_1",
            detector="gps",
            target_uav="uav_1",
            evidence={"residual": 1.5},
        )
        s = ev.to_json()
        assert isinstance(s, str)
        # must be parseable JSON
        json.loads(s)
        rebuilt = event_from_json(s)
        assert rebuilt.to_dict() == ev.to_dict()


class TestCausalChain:
    def test_caused_by_links_events(self):
        sec = SecurityEvent(
            source="monitor_uav_0",
            detector="heartbeat",
            target_uav="uav_2",
        )
        iso = IsolationAnnounce(
            source="monitor_uav_0",
            target_uav="uav_2",
            reason="heartbeat_loss",
            decided_by="monitor_uav_0",
            caused_by=sec.event_id,
        )
        rec = RecoveryRequest(
            source="coordinator",
            target_uav="uav_2",
            action="restart_process",
            requester="coordinator",
            caused_by=iso.event_id,
        )
        # The chain reconstructible from any starting point.
        assert iso.caused_by == sec.event_id
        assert rec.caused_by == iso.event_id
