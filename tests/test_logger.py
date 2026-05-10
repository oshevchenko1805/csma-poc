"""Tests for core.logger."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from core.events import (
    AttackEvent,
    IsolationAnnounce,
    SecurityEvent,
    TelemetryEvent,
)
from core.logger import EventLogger, merge_jsonl, read_jsonl


class TestEventLogger:
    def test_writes_jsonl(self, tmp_path: Path):
        path = tmp_path / "run.jsonl"
        with EventLogger(path) as logger:
            logger.log(TelemetryEvent(source="m1", uav_id="uav_0", msg_type="HEARTBEAT"))
            logger.log(
                SecurityEvent(
                    source="m1",
                    detector="heartbeat",
                    target_uav="uav_2",
                )
            )
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        # each line is valid JSON terminated with newline
        for line in lines:
            assert line.startswith("{") and line.endswith("}")

    def test_round_trip(self, tmp_path: Path):
        path = tmp_path / "run.jsonl"
        events_in = [
            TelemetryEvent(source="m1", uav_id="uav_0", msg_type="HEARTBEAT"),
            AttackEvent(
                source="attacker",
                attack_type="comm_disruption",
                target_uav="uav_2",
                phase="inject_start",
            ),
            SecurityEvent(
                source="m1",
                detector="heartbeat",
                target_uav="uav_2",
                evidence={"missing_for_sec": 3.1},
            ),
        ]
        with EventLogger(path) as logger:
            for e in events_in:
                logger.log(e)

        events_out = read_jsonl(path)
        assert len(events_out) == len(events_in)
        for a, b in zip(events_in, events_out):
            assert a.to_dict() == b.to_dict()

    def test_creates_parent_directory(self, tmp_path: Path):
        path = tmp_path / "deep" / "nested" / "run.jsonl"
        with EventLogger(path) as logger:
            logger.log(TelemetryEvent(source="m1", uav_id="uav_0", msg_type="HEARTBEAT"))
        assert path.exists()

    def test_log_after_close_raises(self, tmp_path: Path):
        path = tmp_path / "run.jsonl"
        logger = EventLogger(path)
        logger.close()
        with pytest.raises(RuntimeError, match="closed"):
            logger.log(TelemetryEvent(source="m1", uav_id="uav_0", msg_type="HEARTBEAT"))

    def test_count_tracks_events(self, tmp_path: Path):
        path = tmp_path / "run.jsonl"
        with EventLogger(path) as logger:
            assert logger.count == 0
            for i in range(5):
                logger.log(
                    TelemetryEvent(source="m1", uav_id="uav_0", msg_type="HEARTBEAT")
                )
            assert logger.count == 5

    def test_thread_safe_concurrent_writes(self, tmp_path: Path):
        """100 threads x 50 events each = 5000 lines, none corrupt."""
        path = tmp_path / "concurrent.jsonl"
        n_threads = 100
        per_thread = 50

        def writer(thread_id: int, logger: EventLogger):
            for i in range(per_thread):
                logger.log(
                    TelemetryEvent(
                        source=f"thread_{thread_id}",
                        uav_id="uav_0",
                        msg_type="HEARTBEAT",
                        data={"i": i},
                    )
                )

        with EventLogger(path) as logger:
            threads = [
                threading.Thread(target=writer, args=(t, logger))
                for t in range(n_threads)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert logger.count == n_threads * per_thread

        events = read_jsonl(path)
        assert len(events) == n_threads * per_thread
        # all sources present (no events lost or shuffled across threads)
        sources = {e.source for e in events}
        assert sources == {f"thread_{t}" for t in range(n_threads)}


class TestMergeJsonl:
    def test_merges_in_timestamp_order(self, tmp_path: Path):
        a = tmp_path / "a.jsonl"
        b = tmp_path / "b.jsonl"
        merged = tmp_path / "merged.jsonl"

        # Build events with explicit timestamps so order is deterministic.
        # File a: t=1.0, 3.0
        # File b: t=2.0, 4.0
        # Merged should be t=1.0, 2.0, 3.0, 4.0 regardless of file order.
        with EventLogger(a) as la:
            ev1 = TelemetryEvent(source="ma", uav_id="uav_0", msg_type="HEARTBEAT")
            ev1.timestamp = 1.0
            la.log(ev1)
            ev3 = TelemetryEvent(source="ma", uav_id="uav_0", msg_type="HEARTBEAT")
            ev3.timestamp = 3.0
            la.log(ev3)

        with EventLogger(b) as lb:
            ev2 = SecurityEvent(source="mb", detector="heartbeat", target_uav="uav_2")
            ev2.timestamp = 2.0
            lb.log(ev2)
            ev4 = IsolationAnnounce(
                source="mb", target_uav="uav_2", reason="x", decided_by="mb"
            )
            ev4.timestamp = 4.0
            lb.log(ev4)

        n = merge_jsonl([b, a], merged)  # intentionally swapped order
        assert n == 4
        events = read_jsonl(merged)
        ts = [e.timestamp for e in events]
        assert ts == [1.0, 2.0, 3.0, 4.0]


class TestReadJsonl:
    def test_corrupt_line_raises(self, tmp_path: Path):
        path = tmp_path / "bad.jsonl"
        path.write_text('{"event_type":"telemetry","source":"x"}\nNOT JSON\n')
        with pytest.raises(ValueError, match=":2:"):
            read_jsonl(path)

    def test_unknown_event_type_raises(self, tmp_path: Path):
        path = tmp_path / "bad.jsonl"
        path.write_text('{"event_type":"made_up","source":"x"}\n')
        with pytest.raises(ValueError, match="Unknown event_type"):
            read_jsonl(path)

    def test_skips_blank_lines(self, tmp_path: Path):
        path = tmp_path / "blanks.jsonl"
        with EventLogger(path) as logger:
            logger.log(TelemetryEvent(source="m1", uav_id="uav_0", msg_type="HEARTBEAT"))
        # append blank lines
        with open(path, "a") as f:
            f.write("\n\n   \n")
        events = read_jsonl(path)
        assert len(events) == 1

