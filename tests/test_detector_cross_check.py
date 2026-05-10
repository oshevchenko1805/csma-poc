"""Tests for CrossCheckDetector and its haversine helper."""

from __future__ import annotations

import math

import pytest

from core.events import PeerPositionAnnounce, SecurityEvent
from detectors.cross_check import CrossCheckDetector, haversine_distance_m


def _ann(
    *,
    uav_id: str,
    lat: float,
    lon: float,
    alt: float = 500.0,
    sample_ts: float = 0.0,
) -> PeerPositionAnnounce:
    return PeerPositionAnnounce(
        source=f"monitor_{uav_id}",
        uav_id=uav_id,
        lat=lat,
        lon=lon,
        alt=alt,
        sample_timestamp=sample_ts,
    )


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------


class TestHaversine:
    def test_zero_distance(self):
        d = haversine_distance_m(47.4, 8.5, 47.4, 8.5)
        assert d == 0.0

    def test_known_short_distance(self):
        """1 degree latitude ~ 111 km. Anywhere on Earth this holds within
        a fraction of a percent."""
        d = haversine_distance_m(0.0, 0.0, 1.0, 0.0)
        assert 110_000 < d < 112_000

    def test_known_meter_scale(self):
        """At Zurich (PX4 SITL home), 1e-5 deg latitude ~ 1.11 m.
        Verifies sub-metre accuracy of the formula at our working scale."""
        d = haversine_distance_m(47.397742, 8.545594, 47.397742 + 1e-5, 8.545594)
        assert 1.0 < d < 1.3

    def test_symmetric(self):
        d_ab = haversine_distance_m(47.4, 8.5, 47.41, 8.51)
        d_ba = haversine_distance_m(47.41, 8.51, 47.4, 8.5)
        assert math.isclose(d_ab, d_ba)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_rejects_non_positive_max_velocity(self):
        with pytest.raises(ValueError):
            CrossCheckDetector(monitor_uav_id="uav_0", source="m", max_velocity_mps=0)

    def test_rejects_negative_margin(self):
        with pytest.raises(ValueError):
            CrossCheckDetector(
                monitor_uav_id="uav_0", source="m", position_error_margin_m=-1
            )

    def test_rejects_zero_min_dt(self):
        with pytest.raises(ValueError):
            CrossCheckDetector(monitor_uav_id="uav_0", source="m", min_dt_sec=0)

    def test_name_and_monitor(self):
        d = CrossCheckDetector(monitor_uav_id="uav_0", source="m")
        assert d.name == "cross_check"
        assert d.monitor_uav_id == "uav_0"


# ---------------------------------------------------------------------------
# Routing & state init
# ---------------------------------------------------------------------------


class TestRouting:
    def test_self_announcements_skipped(self):
        d = CrossCheckDetector(monitor_uav_id="uav_0", source="m")
        # The monitor's own UAV announcing itself: never raises.
        result = d.feed_peer_position(
            _ann(uav_id="uav_0", lat=47.4, lon=8.5, sample_ts=0.0)
        )
        assert result is None
        # Even a "teleport" claimed about ourselves is skipped — that's
        # a different detector's job (gps EKF residuals).
        result = d.feed_peer_position(
            _ann(uav_id="uav_0", lat=47.5, lon=8.6, sample_ts=1.0)
        )
        assert result is None

    def test_first_announcement_no_alert(self):
        """Need at least two samples to compute Δposition."""
        d = CrossCheckDetector(monitor_uav_id="uav_0", source="m")
        result = d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4, lon=8.5, sample_ts=0.0)
        )
        assert result is None
        assert not d.is_alerted("uav_2")

    def test_empty_uav_id_skipped(self):
        d = CrossCheckDetector(monitor_uav_id="uav_0", source="m")
        ann = _ann(uav_id="", lat=47.4, lon=8.5)
        assert d.feed_peer_position(ann) is None


# ---------------------------------------------------------------------------
# Kinematic check
# ---------------------------------------------------------------------------


class TestKinematic:
    def test_consistent_movement_no_alert(self):
        """5 m in 2 s = 2.5 m/s is well within 25 m/s limit."""
        d = CrossCheckDetector(
            monitor_uav_id="uav_0",
            source="m",
            max_velocity_mps=25.0,
            position_error_margin_m=10.0,
        )
        # First baseline
        d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4, lon=8.5, sample_ts=0.0)
        )
        # Move ~5m north in 2s. 1 m ≈ 9e-6 deg lat at this latitude.
        result = d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4 + 5e-5, lon=8.5, sample_ts=2.0)
        )
        assert result is None
        assert not d.is_alerted("uav_2")

    def test_teleport_fires(self):
        """200 m in 1 s would require 200 m/s. Way above 25 m/s budget."""
        d = CrossCheckDetector(
            monitor_uav_id="uav_0",
            source="monitor_uav_0",
            max_velocity_mps=25.0,
            position_error_margin_m=10.0,
        )
        d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4, lon=8.5, sample_ts=0.0)
        )
        # 1e-3 deg lat ≈ 111 m, 1 second elapsed
        result = d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4 + 2e-3, lon=8.5, sample_ts=1.0)
        )
        assert isinstance(result, SecurityEvent)
        assert result.detector == "cross_check"
        assert result.target_uav == "uav_2"
        assert result.source == "monitor_uav_0"
        assert result.severity == "high"
        ev = result.evidence
        assert ev["dt_sec"] == 1.0
        assert ev["max_velocity_mps"] == 25.0
        assert ev["distance_m"] > 200.0
        assert ev["max_allowed_m"] == 35.0  # 25 * 1 + 10
        # Snapshot of previous and current positions
        assert ev["previous_lat"] == 47.4
        assert ev["current_lat"] == 47.4 + 2e-3
        assert d.is_alerted("uav_2")

    def test_within_margin_no_alert(self):
        """Movement within position_error_margin_m alone (zero velocity)
        must not fire."""
        d = CrossCheckDetector(
            monitor_uav_id="uav_0",
            source="m",
            max_velocity_mps=25.0,
            position_error_margin_m=10.0,
        )
        d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4, lon=8.5, sample_ts=0.0)
        )
        # Stationary peer: 5m drift in 1s due to GPS noise
        result = d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4 + 4.5e-5, lon=8.5, sample_ts=1.0)
        )
        assert result is None

    def test_negative_dt_skipped(self):
        """Out-of-order announcement: don't crash, don't alarm, don't update."""
        d = CrossCheckDetector(monitor_uav_id="uav_0", source="m")
        d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4, lon=8.5, sample_ts=10.0)
        )
        # Older announcement arrives late
        result = d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4 + 1e-2, lon=8.5, sample_ts=5.0)
        )
        assert result is None
        # Subsequent in-order announcement should still compare against
        # the original baseline.
        result = d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4 + 5e-5, lon=8.5, sample_ts=12.0)
        )
        # 5e-5 deg ≈ 5.5m; 2s elapsed -> max allowed 25*2+10=60m -> no alert
        assert result is None


# ---------------------------------------------------------------------------
# Hysteresis & recovery
# ---------------------------------------------------------------------------


class TestHysteresis:
    def test_no_repeat_alert(self):
        d = CrossCheckDetector(
            monitor_uav_id="uav_0", source="m", max_velocity_mps=25.0
        )
        d.feed_peer_position(_ann(uav_id="uav_2", lat=47.4, lon=8.5, sample_ts=0.0))
        first = d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4 + 2e-3, lon=8.5, sample_ts=1.0)
        )
        assert first is not None

        # More bad data (still anomalous): no further alerts
        for i in range(5):
            r = d.feed_peer_position(
                _ann(
                    uav_id="uav_2",
                    lat=47.4 + 2e-3 + (i + 1) * 1e-3,
                    lon=8.5,
                    sample_ts=2.0 + i,
                )
            )
            assert r is None

    def test_recovery_clears_alert(self):
        d = CrossCheckDetector(
            monitor_uav_id="uav_0", source="m", max_velocity_mps=25.0
        )
        d.feed_peer_position(_ann(uav_id="uav_2", lat=47.4, lon=8.5, sample_ts=0.0))
        first = d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4 + 2e-3, lon=8.5, sample_ts=1.0)
        )
        assert first is not None
        assert d.is_alerted("uav_2")

        # Plausible movement now: clear hysteresis
        d.feed_peer_position(
            _ann(
                uav_id="uav_2",
                lat=47.4 + 2e-3 + 5e-5,  # ~5m in 1s
                lon=8.5,
                sample_ts=2.0,
            )
        )
        assert not d.is_alerted("uav_2")

        # New teleport: fresh alert
        second = d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4 + 5e-3, lon=8.5, sample_ts=3.0)
        )
        assert second is not None
        assert second.event_id != first.event_id


# ---------------------------------------------------------------------------
# Multi-peer
# ---------------------------------------------------------------------------


class TestMultiPeer:
    def test_peers_tracked_independently(self):
        d = CrossCheckDetector(
            monitor_uav_id="uav_0", source="m", max_velocity_mps=25.0
        )
        # Two peers, both establish baseline
        d.feed_peer_position(_ann(uav_id="uav_1", lat=47.4, lon=8.5, sample_ts=0.0))
        d.feed_peer_position(_ann(uav_id="uav_2", lat=47.4, lon=8.5, sample_ts=0.0))

        # uav_1 moves normally
        r1 = d.feed_peer_position(
            _ann(uav_id="uav_1", lat=47.4 + 5e-5, lon=8.5, sample_ts=1.0)
        )
        assert r1 is None

        # uav_2 teleports
        r2 = d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4 + 2e-3, lon=8.5, sample_ts=1.0)
        )
        assert r2 is not None
        assert r2.target_uav == "uav_2"
        assert d.is_alerted("uav_2")
        assert not d.is_alerted("uav_1")


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_all_peer_state(self):
        d = CrossCheckDetector(monitor_uav_id="uav_0", source="m")
        d.feed_peer_position(_ann(uav_id="uav_1", lat=47.4, lon=8.5, sample_ts=0.0))
        d.feed_peer_position(_ann(uav_id="uav_2", lat=47.4, lon=8.5, sample_ts=0.0))
        d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.4 + 2e-3, lon=8.5, sample_ts=1.0)
        )
        assert d.is_alerted("uav_2")

        d.reset()
        assert not d.is_alerted("uav_2")
        # Next announcement should be treated as first-seen baseline
        result = d.feed_peer_position(
            _ann(uav_id="uav_2", lat=47.5, lon=8.6, sample_ts=10.0)
        )
        assert result is None
