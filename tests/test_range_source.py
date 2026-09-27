"""Tests for the B1 range source: seam, truth buffer, simulated UWB, and
the TrajectoryRecorder on_sample feed (H3 "Range source")."""

from __future__ import annotations

import json
import math
import statistics
import threading
from pathlib import Path

import pytest

from detectors.range_source import (
    SimulatedUwbRangeSource,
    TruthBuffer,
    range_fn_for,
    uwb_noise_m,
)
from runners.trajectory import TrajectoryRecorder

NOISELESS = dict(sigma_m=0.0, bias_m=0.0, p_nlos=0.0, m_nlos=0.0)
MODEL = dict(sigma_m=0.1, bias_m=0.2, p_nlos=0.05, m_nlos=0.5)


def buffer_with(tracks: dict) -> TruthBuffer:
    """tracks: uav -> [(t, x, y, z), ...]"""
    b = TruthBuffer()
    for uav, samples in tracks.items():
        for s in samples:
            b.add(uav, *s)
    return b


STATIC = {
    "uav_0": [(t / 5, 0.0, 0.0, 10.0) for t in range(0, 51)],
    "uav_1": [(t / 5, 3.0, 4.0, 10.0) for t in range(0, 51)],
    "uav_2": [(t / 5, 0.0, 0.0, 20.0) for t in range(0, 51)],
}


# ---------------------------------------------------------------------------
# Noise model (pure)
# ---------------------------------------------------------------------------


class TestNoise:
    def test_deterministic(self):
        a = uwb_noise_m(7, "uav_0", "uav_1", 1790000000.123, **MODEL)
        b = uwb_noise_m(7, "uav_0", "uav_1", 1790000000.123, **MODEL)
        assert a == b

    def test_depends_on_seed_pair_direction_and_time(self):
        base = uwb_noise_m(7, "uav_0", "uav_1", 100.0, **MODEL)
        assert uwb_noise_m(8, "uav_0", "uav_1", 100.0, **MODEL) != base
        assert uwb_noise_m(7, "uav_1", "uav_0", 100.0, **MODEL) != base
        assert uwb_noise_m(7, "uav_0", "uav_1", 101.0, **MODEL) != base

    def test_noiseless_is_bias_only(self):
        assert uwb_noise_m(1, "a", "b", 5.0, sigma_m=0.0, bias_m=0.2,
                           p_nlos=0.0, m_nlos=0.5) == 0.2

    def test_statistics_match_the_preregistered_model(self):
        xs = [uwb_noise_m(3, "uav_0", "uav_1", t * 0.001, **MODEL) for t in range(20000)]
        # mean = bias + p_nlos * m_nlos = 0.2 + 0.025
        assert statistics.fmean(xs) == pytest.approx(0.225, abs=0.01)
        # without the NLOS tail the spread is sigma
        core = [x for x in xs if x < 0.2 + 0.4]
        assert statistics.pstdev(core) == pytest.approx(0.1, abs=0.01)
        # NLOS tail: P(x > bias + 0.5) ~ p_nlos * exp(-0.5 / m_nlos) = 0.018
        tail = sum(1 for x in xs if x > 0.2 + 0.5)
        assert 0.013 < tail / len(xs) < 0.025
        # the tail is positive only: nothing below bias - 5 sigma
        assert min(xs) > 0.2 - 0.5


# ---------------------------------------------------------------------------
# Truth buffer
# ---------------------------------------------------------------------------


class TestTruthBuffer:
    def test_interpolates(self):
        b = buffer_with({"uav_0": [(0.0, 0.0, 0.0, 0.0), (0.2, 2.0, 0.0, 0.0)]})
        assert b.position_at("uav_0", 0.1, 0.5) == pytest.approx((1.0, 0.0, 0.0))

    def test_unknown_uav_and_gap(self):
        b = buffer_with({"uav_0": [(0.0, 0, 0, 0), (2.0, 1, 1, 1)]})
        assert b.position_at("uav_9", 0.0, 0.5) is None
        assert b.position_at("uav_0", 1.0, 0.5) is None

    def test_out_of_order_add(self):
        b = buffer_with({"uav_0": [(1.0, 1, 0, 0), (0.0, 0, 0, 0)]})
        assert b.position_at("uav_0", 0.5, 1.0) == pytest.approx((0.5, 0.0, 0.0))

    def test_history_pruned(self):
        b = TruthBuffer(history_s=1.0)
        for t in range(10):
            b.add("uav_0", float(t), 0, 0, 0)
        assert b.position_at("uav_0", 5.0, 0.5) is None
        assert b.position_at("uav_0", 9.0, 0.5) == (0.0, 0.0, 0.0)

    def test_invalid_history(self):
        with pytest.raises(ValueError):
            TruthBuffer(history_s=0)

    def test_concurrent_add_and_read(self):
        b = TruthBuffer()
        stop = threading.Event()

        def writer():
            t = 0.0
            while not stop.is_set():
                b.add("uav_0", t, t, 0, 0)
                t += 0.01

        th = threading.Thread(target=writer)
        th.start()
        try:
            for _ in range(2000):
                b.position_at("uav_0", 0.5, 0.5)
        finally:
            stop.set()
            th.join()


# ---------------------------------------------------------------------------
# Simulated UWB source
# ---------------------------------------------------------------------------


class TestSimulatedUwb:
    def test_noiseless_is_true_3d_range(self):
        src = SimulatedUwbRangeSource(buffer_with(STATIC), seed=1, **NOISELESS)
        assert src.range_m("uav_0", "uav_1", 3.3) == pytest.approx(5.0)
        assert src.range_m("uav_0", "uav_2", 3.3) == pytest.approx(10.0)

    def test_noise_added_and_reproducible(self):
        a = SimulatedUwbRangeSource(buffer_with(STATIC), seed=11)
        b = SimulatedUwbRangeSource(buffer_with(STATIC), seed=11)
        r = a.range_m("uav_0", "uav_1", 3.3)
        assert r == b.range_m("uav_0", "uav_1", 3.3)
        assert r == pytest.approx(5.0 + uwb_noise_m(11, "uav_0", "uav_1", 3.3, **MODEL))

    def test_defaults_are_the_preregistered_values(self):
        d = SimulatedUwbRangeSource(TruthBuffer(), seed=5).describe()
        assert d == {"model": "simulated_uwb", "seed": 5, "sigma_m": 0.1,
                     "bias_m": 0.2, "p_nlos": 0.05, "m_nlos": 0.5, "max_gap_s": 0.5}

    def test_missing_truth_gives_none(self):
        src = SimulatedUwbRangeSource(buffer_with(STATIC), seed=1)
        assert src.range_m("uav_0", "uav_7", 3.3) is None
        assert src.range_m("uav_0", "uav_1", 99.0) is None
        assert src.range_m("uav_0", "uav_0", 3.3) is None

    def test_never_negative(self):
        close = {"uav_0": [(0.0, 0, 0, 0), (1.0, 0, 0, 0)],
                 "uav_1": [(0.0, 0, 0, 0), (1.0, 0, 0, 0)]}
        src = SimulatedUwbRangeSource(buffer_with(close), seed=1, sigma_m=0.0,
                                      bias_m=-1.0, p_nlos=0.0, m_nlos=0.0)
        assert src.range_m("uav_0", "uav_1", 0.5) == 0.0

    @pytest.mark.parametrize("kw", [{"sigma_m": -0.1}, {"m_nlos": -1.0},
                                    {"p_nlos": 1.5}, {"max_gap_s": 0.0}])
    def test_invalid(self, kw):
        with pytest.raises(ValueError):
            SimulatedUwbRangeSource(TruthBuffer(), seed=1, **kw)

    def test_range_fn_for_binds_the_measuring_uav(self):
        src = SimulatedUwbRangeSource(buffer_with(STATIC), seed=4)
        fn = range_fn_for(src, "uav_1")
        assert fn("uav_0", 3.3) == src.range_m("uav_1", "uav_0", 3.3)
        assert fn("uav_0", 3.3) != src.range_m("uav_0", "uav_1", 3.3)


def test_detector_with_simulated_uwb_honest_swarm_is_silent():
    """End to end, noise on: an honest static swarm raises nothing."""
    from detectors.ranging import RangingConsistencyDetector
    from core.events import PeerPositionAnnounce

    R = 6_371_000.0
    REF = (47.397742, 8.545594, 488.0)

    def geo(x, y, z):   # gz ENU: x east, y north
        return (REF[0] + math.degrees(y / R),
                REF[1] + math.degrees(x / (R * math.cos(math.radians(REF[0])))),
                REF[2] + z)

    truth = {u: s[0][1:] for u, s in STATIC.items()}
    tracks = {u: [(t / 5, *p) for t in range(0, 301)] for u, p in truth.items()}
    src = SimulatedUwbRangeSource(buffer_with(tracks), seed=2026)
    dets = {u: RangingConsistencyDetector(u, f"monitor_{u}", range_fn_for(src, u))
            for u in truth}
    events = []
    for k in range(60):
        t = float(k)
        for u, p in truth.items():
            dets[u].feed_own_position(*geo(*p), sample_ts=t)
        for j, p in truth.items():
            lat, lon, alt = geo(*p)
            a = PeerPositionAnnounce(source=f"monitor_{j}", uav_id=j, lat=lat,
                                     lon=lon, alt=alt, sample_timestamp=t)
            for u in truth:
                events += dets[u].feed_peer_position(a)
    assert events == []


# ---------------------------------------------------------------------------
# TrajectoryRecorder on_sample feed (additive; default = v1)
# ---------------------------------------------------------------------------


def _msg(poses):
    return json.dumps({"header": {"stamp": {"sec": "1", "nsec": 0}},
                       "pose": [{"name": n, "position": {"x": x, "y": y, "z": z},
                                 "orientation": {"w": 1.0}} for n, x, y, z in poses]})


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        v = self.t
        self.t += 1.0
        return v


def _record(tmp_path: Path, lines, **kw):
    rec = TrajectoryRecorder(out_path=tmp_path / "trajectory.jsonl",
                             line_source_factory=lambda: iter(lines),
                             clock=_Clock(), **kw)
    rec.start()
    assert rec.wait_done(5.0)
    rec.stop()
    return rec


class TestRecorderOnSample:
    LINES = [_msg([("x500_0", 1.0, 2.0, 3.0), ("x500_1", 4.0, 5.0, 6.0), ("sun", 0, 0, 0)]),
             _msg([("x500_0", 1.5, 2.0, 3.0)])]

    def test_default_has_no_new_stat(self, tmp_path):
        rec = _record(tmp_path, self.LINES)
        assert set(rec.stats) == {"lines_read", "samples_written",
                                  "parse_errors", "source_errors"}

    def test_callback_gets_every_written_sample(self, tmp_path):
        got = []
        rec = _record(tmp_path, self.LINES, on_sample=lambda *a: got.append(a))
        assert got == [("uav_0", 1000.0, 1.0, 2.0, 3.0),
                       ("uav_1", 1000.0, 4.0, 5.0, 6.0),
                       ("uav_0", 1001.0, 1.5, 2.0, 3.0)]
        assert rec.stats["on_sample_errors"] == 0
        assert rec.stats["samples_written"] == 3

    def test_feeds_truth_buffer(self, tmp_path):
        b = TruthBuffer()
        _record(tmp_path, self.LINES, on_sample=b.add)
        assert b.position_at("uav_0", 1000.5, 1.0) == pytest.approx((1.25, 2.0, 3.0))

    def test_failing_callback_is_counted_not_fatal(self, tmp_path):
        def boom(*a):
            raise RuntimeError("x")
        rec = _record(tmp_path, self.LINES, on_sample=boom)
        assert rec.stats["on_sample_errors"] == 3
        assert rec.stats["samples_written"] == 3
        lines = (tmp_path / "trajectory.jsonl").read_text().splitlines()
        assert len(lines) == 3
