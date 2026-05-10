"""Tests for decision.isolation."""

from __future__ import annotations

import pytest

from core.events import IsolationAnnounce, SecurityEvent
from decision.isolation import IsolationDecider, reason_for_detector


def _security(
    *,
    detector: str = "heartbeat",
    target_uav: str = "uav_2",
    severity: str = "high",
    source: str = "monitor_uav_0",
) -> SecurityEvent:
    return SecurityEvent(
        source=source,
        detector=detector,
        target_uav=target_uav,
        severity=severity,
    )


class TestReasonMapping:
    @pytest.mark.parametrize(
        "detector,reason",
        [
            ("heartbeat", "heartbeat_loss"),
            ("command", "command_injection"),
            ("gps", "gps_anomaly"),
            ("cross_check", "cross_check_anomaly"),
        ],
    )
    def test_known_detectors_map(self, detector: str, reason: str):
        assert reason_for_detector(detector) == reason

    def test_unknown_detector_passes_through(self):
        assert reason_for_detector("brand_new") == "brand_new"


class TestConstructor:
    def test_unknown_severity_threshold_rejected(self):
        with pytest.raises(ValueError, match="unknown severity"):
            IsolationDecider(source="m", severity_threshold="critical")

    def test_default_threshold_is_medium(self):
        d = IsolationDecider(source="m")
        # 'low' should be ignored at the default
        assert d.evaluate(_security(severity="low")) is None
        # 'medium' should fire
        assert d.evaluate(_security(severity="medium")) is not None


class TestEvaluate:
    def test_emits_isolation_for_high_severity(self):
        d = IsolationDecider(source="monitor_uav_0")
        sec = _security(detector="heartbeat", target_uav="uav_2", severity="high")
        result = d.evaluate(sec)

        assert isinstance(result, IsolationAnnounce)
        assert result.source == "monitor_uav_0"
        assert result.target_uav == "uav_2"
        assert result.reason == "heartbeat_loss"
        assert result.decided_by == "monitor_uav_0"
        assert result.caused_by == sec.event_id
        assert d.is_isolated("uav_2")

    def test_emits_for_each_detector_type(self):
        d = IsolationDecider(source="m")
        for det, expected_reason in [
            ("heartbeat", "heartbeat_loss"),
            ("command", "command_injection"),
            ("gps", "gps_anomaly"),
            ("cross_check", "cross_check_anomaly"),
        ]:
            d.reset()
            result = d.evaluate(_security(detector=det))
            assert result is not None
            assert result.reason == expected_reason

    def test_below_threshold_ignored(self):
        d = IsolationDecider(source="m", severity_threshold="high")
        # 'medium' is below 'high'
        assert d.evaluate(_security(severity="medium")) is None
        assert d.evaluate(_security(severity="low")) is None
        # 'high' fires
        assert d.evaluate(_security(severity="high")) is not None

    def test_unknown_severity_treated_as_below_threshold(self):
        d = IsolationDecider(source="m")
        assert d.evaluate(_security(severity="garbage")) is None

    def test_empty_target_uav_ignored(self):
        d = IsolationDecider(source="m")
        sec = SecurityEvent(source="m", detector="heartbeat", target_uav="")
        assert d.evaluate(sec) is None


class TestStateAndDeduplication:
    def test_second_event_for_same_uav_not_re_announced(self):
        d = IsolationDecider(source="m")
        first = d.evaluate(_security(target_uav="uav_2"))
        second = d.evaluate(_security(target_uav="uav_2"))
        assert first is not None
        assert second is None
        assert d.is_isolated("uav_2")

    def test_independent_isolation_per_uav(self):
        d = IsolationDecider(source="m")
        a = d.evaluate(_security(target_uav="uav_1"))
        b = d.evaluate(_security(target_uav="uav_2"))
        assert a is not None
        assert b is not None
        assert d.isolated_uavs == frozenset({"uav_1", "uav_2"})

    def test_un_isolate_allows_fresh_announcement(self):
        d = IsolationDecider(source="m")
        first = d.evaluate(_security(target_uav="uav_2"))
        d.un_isolate("uav_2")
        assert not d.is_isolated("uav_2")
        second = d.evaluate(_security(target_uav="uav_2"))
        assert second is not None
        assert second.event_id != first.event_id

    def test_un_isolate_unknown_uav_silent(self):
        d = IsolationDecider(source="m")
        d.un_isolate("never_seen")  # no exception

    def test_reset_clears_all(self):
        d = IsolationDecider(source="m")
        d.evaluate(_security(target_uav="uav_1"))
        d.evaluate(_security(target_uav="uav_2"))
        d.reset()
        assert d.isolated_uavs == frozenset()
        # Subsequent identical events fire afresh
        assert d.evaluate(_security(target_uav="uav_1")) is not None
