"""B1 step 10: ranging health counters (evaluated / no_own_position /
no_range) in the detector and in Monitor.stats. Setup diagnostics for the
technical flight, not outcomes; v1 stats keys unchanged."""

from __future__ import annotations

import math

import pytest

from detectors.ranging import RangingConsistencyDetector
from runners.monitor import Monitor
from tests.test_detector_ranging import ann, make, own
from tests.test_ranging_wiring import (
    FakeConnection, HeartbeatDetector, RecordingMesh, _ann, _monitor, _own_fix,
)

KEYS = {"evaluated", "no_own_position", "no_range"}


class TestDetectorCounters:
    def test_start_at_zero(self):
        det = make(ranges={"uav_1": 10.0})
        assert det.stats == {k: 0 for k in KEYS}

    def test_evaluated(self):
        det = make(ranges={"uav_1": 10.0})
        for t in (1.0, 2.0, 3.0):
            own(det, (0.0, 0.0, 0.0), t)
            det.feed_peer_position(ann("uav_1", (0.0, 10.0, 0.0), t))
        assert det.stats == {"evaluated": 3, "no_own_position": 0, "no_range": 0}

    def test_no_own_position(self):
        det = make(ranges={"uav_1": 10.0})
        det.feed_peer_position(ann("uav_1", (0.0, 10.0, 0.0), 1.0))
        assert det.stats == {"evaluated": 0, "no_own_position": 1, "no_range": 0}

    def test_own_position_too_far_in_time(self):
        det = make(ranges={"uav_1": 10.0})
        own(det, (0.0, 0.0, 0.0), 1.0)
        det.feed_peer_position(ann("uav_1", (0.0, 10.0, 0.0), 3.0))
        assert det.stats["no_own_position"] == 1

    @pytest.mark.parametrize("r", [None, math.nan, math.inf])
    def test_no_range(self, r):
        det = make(ranges={"uav_1": r})
        own(det, (0.0, 0.0, 0.0), 1.0)
        det.feed_peer_position(ann("uav_1", (0.0, 10.0, 0.0), 1.0))
        assert det.stats == {"evaluated": 0, "no_own_position": 0, "no_range": 1}

    def test_both_missing_counts_in_both(self):
        det = make(ranges={})
        det.feed_peer_position(ann("uav_1", (0.0, 10.0, 0.0), 1.0))
        assert det.stats == {"evaluated": 0, "no_own_position": 1, "no_range": 1}

    def test_own_announcement_not_counted(self):
        det = make(monitor="uav_0", ranges={"uav_0": 0.0})
        own(det, (0.0, 0.0, 0.0), 1.0)
        det.feed_peer_position(ann("uav_0", (0.0, 0.0, 0.0), 1.0))
        assert det.stats == {k: 0 for k in KEYS}

    def test_reset_keeps_counters(self):
        det = make(ranges={"uav_1": 10.0})
        own(det, (0.0, 0.0, 0.0), 1.0)
        det.feed_peer_position(ann("uav_1", (0.0, 10.0, 0.0), 1.0))
        det.reset()
        assert det.stats["evaluated"] == 1

    def test_counters_do_not_change_events(self):
        """Same inputs -> same events as before the counters (peer alarm on
        the 3rd bad announcement)."""
        det = make(ranges={"uav_1": 10.0, "uav_2": 10.0})
        out = []
        for k in range(5):
            t = float(k)
            own(det, (0.0, 0.0, 0.0), t)
            out += det.feed_peer_position(ann("uav_2", (10.0, 0.0, 0.0), t))
            out += det.feed_peer_position(ann("uav_1", (0.0, 13.0, 0.0), t))
        assert [e.target_uav for e in out] == ["uav_1"]
        assert det.stats["evaluated"] == 10


class TestMonitorStats:
    def test_v1_monitor_has_no_ranging_keys(self, tmp_path):
        mon = _monitor(tmp_path, None)
        assert not any(k.startswith("ranging_") for k in mon.stats)

    def test_ranging_keys_present(self, tmp_path):
        det = RangingConsistencyDetector("uav_1", "m", lambda p, t: 20.0)
        mon = _monitor(tmp_path, det)
        assert {k for k in mon.stats if k.startswith("ranging_")} == {
            f"ranging_{k}" for k in KEYS}

    def test_counts_flow_through_the_monitor(self, tmp_path):
        det = RangingConsistencyDetector("uav_1", "m", lambda p, t: 20.0)
        mesh = RecordingMesh()
        mon = _monitor(tmp_path, det, mesh=mesh)
        mesh.deliver("peer_position", _ann("uav_0", (0.0, 20.0, 0.0), 100.0))
        mon._on_telemetry(_own_fix("uav_1", (0.0, 0.0, 0.0), 101.0))
        mesh.deliver("peer_position", _ann("uav_0", (0.0, 20.0, 0.0), 101.0))
        s = mon.stats
        assert (s["ranging_evaluated"], s["ranging_no_own_position"],
                s["ranging_no_range"]) == (1, 1, 0)

    def test_takeout_freezes_counters(self, tmp_path):
        det = RangingConsistencyDetector("uav_1", "m", lambda p, t: 20.0)
        mesh = RecordingMesh()
        mon = _monitor(tmp_path, det, mesh=mesh)
        mon._on_telemetry(_own_fix("uav_1", (0.0, 0.0, 0.0), 100.0))
        mesh.deliver("peer_position", _ann("uav_0", (0.0, 20.0, 0.0), 100.0))
        mon.disable_local_detectors()
        mesh.deliver("peer_position", _ann("uav_0", (0.0, 20.0, 0.0), 101.0))
        assert mon.stats["ranging_evaluated"] == 1
        assert mon.stats["ranging_no_own_position"] == 0
