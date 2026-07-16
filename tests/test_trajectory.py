from __future__ import annotations

import json
from pathlib import Path

import pytest

from runners.trajectory import (
    TrajectoryRecorder,
    default_model_to_uav,
)


# ---------------------------------------------------------------------------
# Helpers — build gz-shaped JSON lines
# ---------------------------------------------------------------------------


def _pose(name: str, x: float, y: float, z: float) -> dict:
    return {
        "name": name,
        "id": 10,
        "position": {"x": x, "y": y, "z": z},
        "orientation": {"w": 1.0},
    }


def _msg(sec: int, nsec: int, poses: list[dict]) -> str:
    return json.dumps(
        {"header": {"stamp": {"sec": str(sec), "nsec": nsec}}, "pose": poses}
    )


class FakeClock:
    """Deterministic clock: each call advances by `step`."""

    def __init__(self, start: float = 1000.0, step: float = 1.0) -> None:
        self.t = start
        self.step = step

    def __call__(self) -> float:
        v = self.t
        self.t += self.step
        return v


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(l) for l in path.read_text().splitlines() if l.strip()
    ]


def _run_recorder(tmp_path: Path, lines: list[str], **kw) -> tuple:
    """Drive a recorder over a finite source to completion.

    wait_done() matters: the reader runs on its own thread, and calling
    stop() straight after start() would race it and truncate the source.
    """
    out = tmp_path / "trajectory.jsonl"
    rec = TrajectoryRecorder(
        out_path=out,
        line_source_factory=lambda: iter(lines),
        **kw,
    )
    rec.start()
    assert rec.wait_done(5.0), "recorder did not drain the source in time"
    rec.stop()
    return rec, _read(out)


# ---------------------------------------------------------------------------
# Model name mapping
# ---------------------------------------------------------------------------


class TestModelMapping:
    def test_x500_maps_to_uav(self):
        assert default_model_to_uav("x500_0") == "uav_0"
        assert default_model_to_uav("x500_2") == "uav_2"
        assert default_model_to_uav("x500_11") == "uav_11"

    def test_non_uav_models_ignored(self):
        assert default_model_to_uav("ground_plane") is None
        assert default_model_to_uav("sun") is None
        assert default_model_to_uav("x500_0::base_link") is None
        assert default_model_to_uav("") is None


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


class TestRecording:
    def test_records_one_line_per_uav(self, tmp_path: Path):
        lines = [
            _msg(576, 148_000_000, [
                _pose("ground_plane", 0, 0, 0),
                _pose("x500_0", 1.0, 2.0, 3.0),
                _pose("x500_1", 4.0, 5.0, 6.0),
            ])
        ]
        rec, recs = _run_recorder(
            tmp_path, lines, clock=FakeClock(step=10.0)
        )
        # ground_plane filtered out; one record per UAV.
        assert len(recs) == 2
        assert [r["uav_id"] for r in recs] == ["uav_0", "uav_1"]
        assert rec.stats["samples_written"] == 2

    def test_position_and_sim_time_parsed(self, tmp_path: Path):
        lines = [_msg(576, 148_000_000, [_pose("x500_0", 1.5, -2.5, 3.25)])]
        _, recs = _run_recorder(tmp_path, lines, clock=FakeClock(step=10.0))
        r = recs[0]
        assert r["x"] == pytest.approx(1.5)
        assert r["y"] == pytest.approx(-2.5)
        assert r["z"] == pytest.approx(3.25)
        assert r["t_sim"] == pytest.approx(576.148)

    def test_wall_clock_recorded(self, tmp_path: Path):
        # Both clocks matter: merged.jsonl events are wall-clock, Gazebo
        # stamps are sim-clock. Correlation needs the wall clock.
        lines = [_msg(1, 0, [_pose("x500_0", 0, 0, 0)])]
        _, recs = _run_recorder(
            tmp_path, lines, clock=FakeClock(start=1784195298.0, step=10.0)
        )
        assert recs[0]["t_wall"] == pytest.approx(1784195298.0)

    def test_omitted_zero_fields_default_to_zero(self, tmp_path: Path):
        # Gazebo omits zero-valued fields entirely (seen live:
        # "position":{} for a model at the origin).
        line = json.dumps({
            "header": {"stamp": {"sec": "1", "nsec": 0}},
            "pose": [{"name": "x500_0", "position": {}, "orientation": {"w": 1}}],
        })
        _, recs = _run_recorder(tmp_path, [line], clock=FakeClock(step=10.0))
        assert recs[0]["x"] == 0.0
        assert recs[0]["y"] == 0.0
        assert recs[0]["z"] == 0.0
        assert recs[0]["qw"] == 1.0


# ---------------------------------------------------------------------------
# Throttling
# ---------------------------------------------------------------------------


class TestThrottle:
    def test_throttles_to_sample_rate(self, tmp_path: Path):
        # 10 messages, clock advances 0.1s per read, 5 Hz => period 0.2s.
        lines = [_msg(i, 0, [_pose("x500_0", i, 0, 0)]) for i in range(10)]
        _, recs = _run_recorder(
            tmp_path, lines, sample_hz=5.0, clock=FakeClock(step=0.1)
        )
        # Roughly half the messages survive the 0.2s throttle.
        assert 4 <= len(recs) <= 6

    def test_high_rate_keeps_all_when_period_small(self, tmp_path: Path):
        lines = [_msg(i, 0, [_pose("x500_0", i, 0, 0)]) for i in range(5)]
        _, recs = _run_recorder(
            tmp_path, lines, sample_hz=1000.0, clock=FakeClock(step=1.0)
        )
        assert len(recs) == 5

    def test_rejects_bad_sample_hz(self, tmp_path: Path):
        with pytest.raises(ValueError, match="sample_hz"):
            TrajectoryRecorder(
                out_path=tmp_path / "t.jsonl",
                line_source_factory=lambda: iter([]),
                sample_hz=0,
            )


# ---------------------------------------------------------------------------
# Robustness — a recorder failure must never fail a flight
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_malformed_lines_skipped(self, tmp_path: Path):
        lines = [
            "not json at all",
            "",
            _msg(1, 0, [_pose("x500_0", 1, 1, 1)]),
            "{broken",
        ]
        rec, recs = _run_recorder(tmp_path, lines, clock=FakeClock(step=10.0))
        assert len(recs) == 1
        assert rec.stats["parse_errors"] == 2

    def test_source_exception_does_not_raise(self, tmp_path: Path):
        def boom():
            raise RuntimeError("gz not installed")

        out = tmp_path / "trajectory.jsonl"
        rec = TrajectoryRecorder(out_path=out, line_source_factory=boom)
        rec.start()
        assert rec.wait_done(5.0)
        rec.stop()  # must not raise
        assert rec.stats["source_errors"] == 1
        assert _read(out) == []

    def test_unknown_models_ignored(self, tmp_path: Path):
        lines = [_msg(1, 0, [
            _pose("sun", 0, 0, 0),
            _pose("ground_plane", 0, 0, 0),
        ])]
        _, recs = _run_recorder(tmp_path, lines, clock=FakeClock(step=10.0))
        assert recs == []


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_done_flag_set_after_source_exhausted(self, tmp_path: Path):
        rec = TrajectoryRecorder(
            out_path=tmp_path / "t.jsonl",
            line_source_factory=lambda: iter([]),
        )
        assert rec.done is False
        rec.start()
        assert rec.wait_done(5.0)
        assert rec.done is True
        rec.stop()

    def test_stop_is_idempotent(self, tmp_path: Path):
        rec = TrajectoryRecorder(
            out_path=tmp_path / "t.jsonl",
            line_source_factory=lambda: iter([]),
        )
        rec.start()
        rec.wait_done(5.0)
        rec.stop()
        rec.stop()  # must not raise

    def test_context_manager(self, tmp_path: Path):
        out = tmp_path / "t.jsonl"
        lines = [_msg(1, 0, [_pose("x500_0", 7.0, 0, 0)])]
        with TrajectoryRecorder(
            out_path=out,
            line_source_factory=lambda: iter(lines),
            clock=FakeClock(step=10.0),
        ) as rec:
            assert rec.wait_done(5.0)
        assert _read(out)[0]["x"] == pytest.approx(7.0)

    def test_double_start_is_safe(self, tmp_path: Path):
        rec = TrajectoryRecorder(
            out_path=tmp_path / "t.jsonl",
            line_source_factory=lambda: iter([]),
        )
        rec.start()
        rec.start()
        rec.wait_done(5.0)
        rec.stop()
