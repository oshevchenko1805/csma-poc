"""Tests for GpsSpoofingDetector."""

from __future__ import annotations

import pytest

from core.events import SecurityEvent, TelemetryEvent
from detectors.gps import GpsSpoofingDetector


def _estimator(
    *,
    uav_id: str = "uav_0",
    pos_horiz_ratio: float = 0.3,
    vel_ratio: float = 0.2,
    pos_vert_ratio: float = 0.2,
    mag_ratio: float | None = None,
) -> TelemetryEvent:
    data = {
        "pos_horiz_ratio": pos_horiz_ratio,
        "vel_ratio": vel_ratio,
        "pos_vert_ratio": pos_vert_ratio,
        "_src_sysid": int(uav_id.split("_")[1]) + 1,
    }
    if mag_ratio is not None:
        data["mag_ratio"] = mag_ratio
    return TelemetryEvent(
        source=f"monitor_{uav_id}",
        uav_id=uav_id,
        msg_type="ESTIMATOR_STATUS",
        data=data,
    )


class TestConstructor:
    def test_rejects_non_positive_threshold(self):
        with pytest.raises(ValueError):
            GpsSpoofingDetector(target_uav="uav_0", source="m", threshold=0)
        with pytest.raises(ValueError):
            GpsSpoofingDetector(target_uav="uav_0", source="m", threshold=-1)

    def test_rejects_zero_sustained_samples(self):
        with pytest.raises(ValueError):
            GpsSpoofingDetector(
                target_uav="uav_0", source="m", sustained_samples=0
            )

    def test_defaults(self):
        d = GpsSpoofingDetector(target_uav="uav_0", source="m")
        assert d.threshold == 1.0
        assert d.sustained_samples == 3

    def test_name_and_target(self):
        d = GpsSpoofingDetector(target_uav="uav_2", source="m")
        assert d.name == "gps"
        assert d.target_uav == "uav_2"


class TestRouting:
    def test_wrong_uav_ignored(self):
        d = GpsSpoofingDetector(target_uav="uav_0", source="m")
        result = d.feed(_estimator(uav_id="uav_1", pos_horiz_ratio=5.0))
        assert result is None
        assert d.consecutive_above_threshold == 0

    def test_non_estimator_msg_ignored(self):
        d = GpsSpoofingDetector(target_uav="uav_0", source="m")
        ev = TelemetryEvent(
            source="m",
            uav_id="uav_0",
            msg_type="HEARTBEAT",
            data={"pos_horiz_ratio": 5.0},
        )
        assert d.feed(ev) is None
        assert d.consecutive_above_threshold == 0

    def test_missing_ratio_ignored(self):
        d = GpsSpoofingDetector(target_uav="uav_0", source="m")
        ev = TelemetryEvent(
            source="m",
            uav_id="uav_0",
            msg_type="ESTIMATOR_STATUS",
            data={"vel_ratio": 0.2},  # pos_horiz_ratio missing
        )
        assert d.feed(ev) is None

    def test_garbage_ratio_ignored(self):
        d = GpsSpoofingDetector(target_uav="uav_0", source="m")
        ev = TelemetryEvent(
            source="m",
            uav_id="uav_0",
            msg_type="ESTIMATOR_STATUS",
            data={"pos_horiz_ratio": "not a number"},
        )
        assert d.feed(ev) is None


class TestThresholdLogic:
    def test_below_threshold_no_alert(self):
        d = GpsSpoofingDetector(
            target_uav="uav_0", source="m", threshold=1.0, sustained_samples=3
        )
        for _ in range(10):
            assert d.feed(_estimator(pos_horiz_ratio=0.5)) is None
        assert not d.is_alerted

    def test_at_exact_threshold_does_not_fire(self):
        """Strict inequality: ratio == threshold is not anomalous."""
        d = GpsSpoofingDetector(
            target_uav="uav_0", source="m", threshold=1.0, sustained_samples=3
        )
        for _ in range(10):
            assert d.feed(_estimator(pos_horiz_ratio=1.0)) is None

    def test_single_spike_below_sustained_no_alert(self):
        d = GpsSpoofingDetector(
            target_uav="uav_0", source="m", threshold=1.0, sustained_samples=3
        )
        # Only 2 consecutive — sustained requires 3
        assert d.feed(_estimator(pos_horiz_ratio=1.5)) is None
        assert d.feed(_estimator(pos_horiz_ratio=1.5)) is None
        assert not d.is_alerted

    def test_sustained_breach_fires_on_nth_sample(self):
        d = GpsSpoofingDetector(
            target_uav="uav_0",
            source="monitor_uav_0",
            threshold=1.0,
            sustained_samples=3,
        )
        assert d.feed(_estimator(pos_horiz_ratio=1.5)) is None
        assert d.feed(_estimator(pos_horiz_ratio=1.5)) is None
        result = d.feed(_estimator(pos_horiz_ratio=1.7))

        assert isinstance(result, SecurityEvent)
        assert result.detector == "gps"
        assert result.target_uav == "uav_0"
        assert result.source == "monitor_uav_0"
        assert result.severity == "high"
        ev = result.evidence
        assert ev["pos_horiz_ratio"] == 1.7
        assert ev["threshold"] == 1.0
        assert ev["sustained_samples"] == 3
        assert "vel_ratio" in ev
        assert d.is_alerted

    def test_dip_below_resets_counter(self):
        d = GpsSpoofingDetector(
            target_uav="uav_0", source="m", threshold=1.0, sustained_samples=3
        )
        assert d.feed(_estimator(pos_horiz_ratio=1.5)) is None
        assert d.feed(_estimator(pos_horiz_ratio=1.5)) is None
        # Dip below threshold — counter resets
        assert d.feed(_estimator(pos_horiz_ratio=0.4)) is None
        assert d.consecutive_above_threshold == 0
        # Need 3 fresh consecutive
        assert d.feed(_estimator(pos_horiz_ratio=1.5)) is None
        assert d.feed(_estimator(pos_horiz_ratio=1.5)) is None
        result = d.feed(_estimator(pos_horiz_ratio=1.5))
        assert result is not None


class TestHysteresisAndRecovery:
    def test_hysteresis_no_repeat_alert(self):
        """Once alarmed, further samples above threshold do not re-fire."""
        d = GpsSpoofingDetector(
            target_uav="uav_0", source="m", threshold=1.0, sustained_samples=3
        )
        for _ in range(3):
            d.feed(_estimator(pos_horiz_ratio=1.5))
        assert d.is_alerted
        # Subsequent samples while still anomalous: no further alerts.
        for _ in range(20):
            assert d.feed(_estimator(pos_horiz_ratio=2.0)) is None

    def test_recovery_cycle(self):
        """Spike -> alert -> dip -> spike -> fresh alert."""
        d = GpsSpoofingDetector(
            target_uav="uav_0", source="m", threshold=1.0, sustained_samples=3
        )
        # First detection cycle
        for _ in range(2):
            d.feed(_estimator(pos_horiz_ratio=1.5))
        first = d.feed(_estimator(pos_horiz_ratio=1.5))
        assert first is not None
        assert d.is_alerted

        # Recovery
        d.feed(_estimator(pos_horiz_ratio=0.4))
        assert not d.is_alerted

        # Some normal samples
        for _ in range(5):
            d.feed(_estimator(pos_horiz_ratio=0.3))

        # Second detection cycle — must produce a new alert
        for _ in range(2):
            d.feed(_estimator(pos_horiz_ratio=1.5))
        second = d.feed(_estimator(pos_horiz_ratio=1.5))
        assert second is not None
        assert second.event_id != first.event_id


class TestEvidence:
    def test_evidence_includes_secondary_signals(self):
        d = GpsSpoofingDetector(
            target_uav="uav_0", source="m", threshold=1.0, sustained_samples=2
        )
        d.feed(
            _estimator(
                pos_horiz_ratio=1.5,
                vel_ratio=0.3,
                pos_vert_ratio=0.4,
                mag_ratio=0.2,
            )
        )
        result = d.feed(
            _estimator(
                pos_horiz_ratio=1.6,
                vel_ratio=0.35,
                pos_vert_ratio=0.45,
                mag_ratio=0.25,
            )
        )
        assert result is not None
        ev = result.evidence
        assert ev["vel_ratio"] == 0.35
        assert ev["pos_vert_ratio"] == 0.45
        assert ev["mag_ratio"] == 0.25

    def test_evidence_omits_missing_secondary_signals(self):
        d = GpsSpoofingDetector(
            target_uav="uav_0", source="m", threshold=1.0, sustained_samples=2
        )
        # ESTIMATOR_STATUS without pos_vert_ratio
        ev1 = TelemetryEvent(
            source="m",
            uav_id="uav_0",
            msg_type="ESTIMATOR_STATUS",
            data={"pos_horiz_ratio": 1.5, "vel_ratio": 0.3},
        )
        ev2 = TelemetryEvent(
            source="m",
            uav_id="uav_0",
            msg_type="ESTIMATOR_STATUS",
            data={"pos_horiz_ratio": 1.6, "vel_ratio": 0.35},
        )
        d.feed(ev1)
        result = d.feed(ev2)
        assert result is not None
        assert "vel_ratio" in result.evidence
        assert "pos_vert_ratio" not in result.evidence


class TestConfigurable:
    def test_custom_threshold(self):
        d = GpsSpoofingDetector(
            target_uav="uav_0", source="m", threshold=2.0, sustained_samples=2
        )
        # 1.5 not anomalous under tighter threshold
        for _ in range(5):
            assert d.feed(_estimator(pos_horiz_ratio=1.5)) is None

        # 2.5 sustained -> alert
        d.feed(_estimator(pos_horiz_ratio=2.5))
        result = d.feed(_estimator(pos_horiz_ratio=2.5))
        assert result is not None

    def test_custom_sustained_samples(self):
        """Higher N means more conservative detector (lower false-positive
        rate, higher MTTD)."""
        d = GpsSpoofingDetector(
            target_uav="uav_0", source="m", threshold=1.0, sustained_samples=5
        )
        for _ in range(4):
            assert d.feed(_estimator(pos_horiz_ratio=1.5)) is None
        result = d.feed(_estimator(pos_horiz_ratio=1.5))
        assert result is not None

    def test_severity_configurable(self):
        d = GpsSpoofingDetector(
            target_uav="uav_0",
            source="m",
            threshold=1.0,
            sustained_samples=2,
            severity="medium",
        )
        d.feed(_estimator(pos_horiz_ratio=1.5))
        result = d.feed(_estimator(pos_horiz_ratio=1.5))
        assert result is not None
        assert result.severity == "medium"


class TestReset:
    def test_reset_clears_counter_and_alerted(self):
        d = GpsSpoofingDetector(
            target_uav="uav_0", source="m", threshold=1.0, sustained_samples=3
        )
        for _ in range(3):
            d.feed(_estimator(pos_horiz_ratio=1.5))
        assert d.is_alerted

        d.reset()
        assert d.consecutive_above_threshold == 0
        assert not d.is_alerted

        # After reset behaves like fresh detector
        for _ in range(2):
            assert d.feed(_estimator(pos_horiz_ratio=1.5)) is None
