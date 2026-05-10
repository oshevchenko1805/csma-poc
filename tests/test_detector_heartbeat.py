"""
Tests for HeartbeatDetector.

Time is supplied explicitly to feed() (via event.timestamp) and tick(),
so all tests are deterministic — no sleeps required.
"""

from __future__ import annotations

import pytest

from core.events import SecurityEvent, TelemetryEvent
from detectors.heartbeat import HeartbeatDetector


def _heartbeat(uav_id: str, ts: float) -> TelemetryEvent:
    ev = TelemetryEvent(
        source=f"monitor_{uav_id}",
        uav_id=uav_id,
        msg_type="HEARTBEAT",
        data={"type": 2, "autopilot": 12},
    )
    ev.timestamp = ts
    return ev


class TestHeartbeatDetector:
    def test_constructor_rejects_non_positive_timeout(self):
        with pytest.raises(ValueError):
            HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=0)
        with pytest.raises(ValueError):
            HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=-1)

    def test_no_alert_before_first_heartbeat(self):
        """Grace period: no heartbeat ever seen -> no alarm."""
        d = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=3.0)
        for now in (0.0, 5.0, 100.0):
            assert d.tick(now=now) is None
        assert not d.is_alerted

    def test_feed_updates_last_heartbeat(self):
        d = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=3.0)
        d.feed(_heartbeat("uav_0", ts=10.0))
        assert d.last_heartbeat == 10.0

    def test_feed_ignores_wrong_uav(self):
        d = HeartbeatDetector(target_uav="uav_0", source="m")
        d.feed(_heartbeat("uav_1", ts=10.0))
        assert d.last_heartbeat is None

    def test_feed_ignores_non_heartbeat(self):
        d = HeartbeatDetector(target_uav="uav_0", source="m")
        ev = TelemetryEvent(
            source="m", uav_id="uav_0", msg_type="ATTITUDE", data={}
        )
        ev.timestamp = 10.0
        d.feed(ev)
        assert d.last_heartbeat is None

    def test_no_alert_within_timeout(self):
        d = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=3.0)
        d.feed(_heartbeat("uav_0", ts=10.0))
        assert d.tick(now=12.0) is None  # 2s elapsed
        assert d.tick(now=12.99) is None  # just under threshold

    def test_alert_beyond_timeout(self):
        d = HeartbeatDetector(
            target_uav="uav_0", source="monitor_uav_0", timeout_sec=3.0
        )
        d.feed(_heartbeat("uav_0", ts=10.0))
        result = d.tick(now=14.0)  # 4s elapsed > 3s threshold

        assert isinstance(result, SecurityEvent)
        assert result.detector == "heartbeat"
        assert result.target_uav == "uav_0"
        assert result.source == "monitor_uav_0"
        assert result.severity == "high"
        ev = result.evidence
        assert ev["last_heartbeat_ts"] == 10.0
        assert ev["time_since_heartbeat"] == 4.0
        assert ev["timeout_threshold"] == 3.0
        assert d.is_alerted

    def test_hysteresis_no_repeat_alert(self):
        """While the disruption persists, only one SecurityEvent fires."""
        d = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=3.0)
        d.feed(_heartbeat("uav_0", ts=10.0))
        first = d.tick(now=14.0)
        assert first is not None
        assert d.tick(now=15.0) is None
        assert d.tick(now=20.0) is None
        assert d.tick(now=100.0) is None

    def test_recovery_clears_alerted_flag(self):
        """Heartbeat resumes -> flag clears -> next disruption fires fresh."""
        d = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=3.0)
        d.feed(_heartbeat("uav_0", ts=10.0))
        first = d.tick(now=14.0)
        assert first is not None
        assert d.is_alerted

        # Heartbeat returns
        d.feed(_heartbeat("uav_0", ts=15.0))
        assert not d.is_alerted

        # Within timeout — no alert
        assert d.tick(now=17.0) is None
        # Beyond timeout again — fresh alert
        second = d.tick(now=20.0)
        assert second is not None
        assert second.event_id != first.event_id
        assert second.evidence["last_heartbeat_ts"] == 15.0

    def test_reset_clears_all_state(self):
        d = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=3.0)
        d.feed(_heartbeat("uav_0", ts=10.0))
        d.tick(now=14.0)
        assert d.is_alerted

        d.reset()
        assert d.last_heartbeat is None
        assert not d.is_alerted
        assert d.tick(now=20.0) is None  # grace period back

    def test_severity_configurable(self):
        d = HeartbeatDetector(
            target_uav="uav_0", source="m", timeout_sec=3.0, severity="medium"
        )
        d.feed(_heartbeat("uav_0", ts=10.0))
        result = d.tick(now=14.0)
        assert result is not None
        assert result.severity == "medium"

    def test_name_and_target(self):
        d = HeartbeatDetector(target_uav="uav_2", source="m")
        assert d.name == "heartbeat"
        assert d.target_uav == "uav_2"

    def test_alert_at_exact_threshold_does_not_fire(self):
        """Boundary: elapsed == threshold should not fire (strict inequality)."""
        d = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=3.0)
        d.feed(_heartbeat("uav_0", ts=10.0))
        assert d.tick(now=13.0) is None  # exactly 3.0s elapsed
        assert d.tick(now=13.001) is not None  # one millisecond past
