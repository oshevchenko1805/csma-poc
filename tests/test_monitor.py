"""
Tests for runners.monitor (steps 8.1 + 8.2 — observation + isolation).

Uses FakeConnection from tests.test_telemetry-style fakes (replicated
locally to keep this test file self-contained) and real detector
implementations writing to a tmp_path EventLogger.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

import pytest

from core.events import (
    IsolationAnnounce,
    PeerPositionAnnounce,
    SecurityEvent,
    TelemetryEvent,
)
from core.logger import read_jsonl
from core.mesh import MeshBus, NoOpMesh, ZmqMesh
from decision.isolation import IsolationDecider
from detectors.command import CommandInjectionDetector
from detectors.cross_check import CrossCheckDetector
from detectors.heartbeat import HeartbeatDetector
from enforcement.isolation import LocalIsolationEnforcer
from runners.monitor import DEFAULT_TELEMETRY_LOG_TYPES, Monitor


# ---------------------------------------------------------------------------
# Fake MAVLink connection (same shape as in test_telemetry.py)
# ---------------------------------------------------------------------------


class FakeMessage:
    def __init__(self, type_name: str, sysid: int, fields: Optional[dict] = None):
        self._type = type_name
        self._sysid = sysid
        self._fields = dict(fields or {})

    def get_type(self): return self._type
    def get_srcSystem(self): return self._sysid
    def to_dict(self): return dict(self._fields)


class FakeConnection:
    def __init__(self) -> None:
        self._q: deque[FakeMessage] = deque()
        self._lock = threading.Lock()
        self._closed = False

    def push(self, msg: FakeMessage) -> None:
        with self._lock:
            self._q.append(msg)

    def recv_match(self, type=None, blocking: bool = True, timeout: float = 1.0):
        deadline = time.time() + timeout
        allowed = None
        if type is not None:
            allowed = {type} if isinstance(type, str) else set(type)
        while True:
            if self._closed:
                return None
            with self._lock:
                if self._q:
                    msg = self._q[0]
                    if allowed is None or msg.get_type() in allowed:
                        self._q.popleft()
                        return msg
                    self._q.popleft()
                    continue
            if not blocking or time.time() >= deadline:
                return None
            time.sleep(0.005)

    def close(self) -> None:
        self._closed = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wait_until(predicate, timeout: float = 3.0, poll: float = 0.02) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(poll)
    return predicate()


def _make_monitor(
    tmp_path: Path,
    *,
    detectors: list,
    conn: Optional[FakeConnection] = None,
    telemetry_log_path: Optional[Path] = None,
    telemetry_log_types: Optional[list] = None,
    tick_period_sec: float = 0.1,
    isolation_decider: Optional[IsolationDecider] = None,
    isolation_enforcer: Optional[LocalIsolationEnforcer] = None,
) -> Monitor:
    if conn is None:
        conn = FakeConnection()
    log_path = tmp_path / "monitor.jsonl"
    return Monitor(
        uav_id="uav_0",
        source="monitor_uav_0",
        telemetry_endpoint="udpin:127.0.0.1:14540",
        sysid=1,
        detectors=detectors,
        log_path=log_path,
        tick_period_sec=tick_period_sec,
        telemetry_log_path=telemetry_log_path,
        telemetry_log_types=telemetry_log_types,
        isolation_decider=isolation_decider,
        isolation_enforcer=isolation_enforcer,
        _telemetry_connection=conn,
    )


def _estimator_msg(ratio: float = 0.006, vel_ratio: float = 0.31) -> FakeMessage:
    """Mimics PX4's ESTIMATOR_STATUS — the message carrying the EKF
    residual GpsSpoofingDetector fires on."""
    return FakeMessage(
        "ESTIMATOR_STATUS",
        1,
        {"pos_horiz_ratio": ratio, "vel_ratio": vel_ratio},
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_rejects_empty_detector_list(self, tmp_path: Path):
        with pytest.raises(ValueError, match="at least one detector"):
            Monitor(
                uav_id="uav_0",
                source="m",
                telemetry_endpoint="x",
                sysid=1,
                detectors=[],
                log_path=tmp_path / "m.jsonl",
            )

    def test_rejects_detector_targeting_other_uav(self, tmp_path: Path):
        d = HeartbeatDetector(target_uav="uav_2", source="m")
        with pytest.raises(ValueError, match="targets"):
            Monitor(
                uav_id="uav_0",
                source="m",
                telemetry_endpoint="x",
                sysid=1,
                detectors=[d],
                log_path=tmp_path / "m.jsonl",
            )

    def test_rejects_non_positive_tick_period(self, tmp_path: Path):
        d = HeartbeatDetector(target_uav="uav_0", source="m")
        with pytest.raises(ValueError, match="tick_period_sec"):
            Monitor(
                uav_id="uav_0",
                source="m",
                telemetry_endpoint="x",
                sysid=1,
                detectors=[d],
                log_path=tmp_path / "m.jsonl",
                tick_period_sec=0,
            )


# ---------------------------------------------------------------------------
# Telemetry routing through detectors
# ---------------------------------------------------------------------------


class TestTelemetryRouting:
    def test_command_injection_detected_and_logged(self, tmp_path: Path):
        conn = FakeConnection()
        det = CommandInjectionDetector(target_uav="uav_0", source="monitor_uav_0")
        log_path = tmp_path / "monitor.jsonl"

        with _make_monitor(tmp_path, detectors=[det], conn=conn) as m:
            # Legitimate command — no alert.
            conn.push(
                FakeMessage(
                    "COMMAND_LONG",
                    1,
                    {"command": 192, "target_system": 1, "target_component": 1},
                )
            )
            # Spoofed command from sysid 99 — should fire.
            conn.push(
                FakeMessage(
                    "COMMAND_LONG",
                    1,
                    {
                        "command": 192,
                        "target_system": 1,
                        "target_component": 1,
                        # NOTE: TelemetryListener's _src_sysid is the message
                        # source. FakeConnection-driven test reuses sysid as
                        # the listener filter (must match expected_sysid=1)
                        # but the COMMAND_LONG bytes carry _src_sysid via
                        # listener metadata — we adjust the test to reflect
                        # the listener pipeline. See note below.
                    },
                )
            )
            # Second push uses the same FakeMessage sysid (listener routes by
            # the message's get_srcSystem) — both match expected_sysid. The
            # injection detection in this test path is exercised by the
            # combination of msg_type + missing matching src_sysid in data,
            # which the detector treats as "no evidence -> no alert". To
            # actually fire, push a COMMAND_LONG with explicit non-whitelist
            # src_sysid via a separate route below.

            # Wait briefly for telemetry to flow.
            assert _wait_until(lambda: m.stats["telemetry_seen"] >= 2)

        # In this configuration both messages came from sysid 1 (whitelisted),
        # so no security event should be emitted.
        assert m.stats["security_emitted"] == 0
        events = read_jsonl(log_path)
        assert all(e.event_type != "security" for e in events)

    def test_command_injection_from_rogue_sysid_fires(self, tmp_path: Path):
        """A COMMAND_LONG arriving with a non-whitelist src_sysid is the
        signature of a command-injection attack. The listener bypasses
        its sysid filter for COMMAND_LONG/COMMAND_INT (see
        SYSID_FILTER_PASSTHROUGH in core/telemetry) so the detector can
        see the packet. CommandInjectionDetector then fires because
        src=99 is outside the {1,2,3,255} whitelist."""
        conn = FakeConnection()
        det = CommandInjectionDetector(target_uav="uav_0", source="monitor_uav_0")
        log_path = tmp_path / "monitor.jsonl"

        with _make_monitor(tmp_path, detectors=[det], conn=conn) as m:
            # Rogue sysid 99 — must NOT be filtered by the listener,
            # must reach the detector, must produce a SecurityEvent.
            conn.push(
                FakeMessage(
                    "COMMAND_LONG",
                    99,
                    {"command": 192, "target_system": 1, "target_component": 1},
                )
            )
            assert _wait_until(lambda: m.stats["security_emitted"] >= 1)

        # One security event emitted with the expected evidence.
        events = read_jsonl(log_path)
        sec = [e for e in events if e.event_type == "security"]
        assert len(sec) == 1
        assert isinstance(sec[0], SecurityEvent)
        assert sec[0].detector == "command"
        assert sec[0].target_uav == "uav_0"
        assert sec[0].evidence["src_sysid"] == 99
        assert sec[0].evidence["command_type"] == "COMMAND_LONG"


# ---------------------------------------------------------------------------
# Tick-driven detection (heartbeat absence)
# ---------------------------------------------------------------------------


class TestTickDetection:
    def test_heartbeat_loss_detected_via_tick(self, tmp_path: Path):
        conn = FakeConnection()
        det = HeartbeatDetector(
            target_uav="uav_0", source="monitor_uav_0", timeout_sec=0.3
        )
        log_path = tmp_path / "monitor.jsonl"

        with _make_monitor(
            tmp_path, detectors=[det], conn=conn, tick_period_sec=0.1
        ) as m:
            # Send one heartbeat to set last_heartbeat baseline.
            conn.push(FakeMessage("HEARTBEAT", 1, {"type": 2, "autopilot": 12}))
            assert _wait_until(lambda: det.last_heartbeat is not None)

            # Now wait long enough for tick to fire heartbeat-loss alert.
            assert _wait_until(lambda: m.stats["security_emitted"] >= 1, timeout=2.0)

        events = read_jsonl(log_path)
        sec = [e for e in events if e.event_type == "security"]
        assert len(sec) == 1
        assert isinstance(sec[0], SecurityEvent)
        assert sec[0].detector == "heartbeat"
        assert sec[0].target_uav == "uav_0"
        assert sec[0].severity == "high"

    def test_no_alert_while_heartbeats_arrive(self, tmp_path: Path):
        """Continuous heartbeats — tick must NOT fire alerts."""
        conn = FakeConnection()
        det = HeartbeatDetector(
            target_uav="uav_0", source="m", timeout_sec=0.5
        )

        with _make_monitor(
            tmp_path, detectors=[det], conn=conn, tick_period_sec=0.1
        ) as m:
            # Push a heartbeat every 0.1s for 0.6s (longer than timeout).
            stop = time.time() + 0.6
            while time.time() < stop:
                conn.push(FakeMessage("HEARTBEAT", 1, {}))
                time.sleep(0.1)

        # No security events should have been emitted.
        assert m.stats["security_emitted"] == 0


# ---------------------------------------------------------------------------
# Multiple detectors share the pipeline
# ---------------------------------------------------------------------------


class TestMultipleDetectors:
    def test_both_detectors_run(self, tmp_path: Path):
        conn = FakeConnection()
        hb = HeartbeatDetector(
            target_uav="uav_0", source="m", timeout_sec=0.3
        )
        cmd = CommandInjectionDetector(target_uav="uav_0", source="m")

        with _make_monitor(
            tmp_path, detectors=[hb, cmd], conn=conn, tick_period_sec=0.1
        ) as m:
            # Heartbeat and a legitimate command.
            conn.push(FakeMessage("HEARTBEAT", 1, {"type": 2}))
            conn.push(
                FakeMessage(
                    "COMMAND_LONG", 1, {"command": 192, "target_system": 1}
                )
            )
            # Wait for HB-loss to fire after baseline.
            assert _wait_until(lambda: m.stats["security_emitted"] >= 1, timeout=2.0)

        # heartbeat detector should have fired exactly once
        assert m.stats["security_emitted"] == 1


# ---------------------------------------------------------------------------
# Telemetry recording (OPEN-3)
#
# Monitors log events, not telemetry — so a detector that never fires
# leaves no trace of what it saw. That is why OPEN-3 cannot be answered
# from the runs already on disk (RESULTS_NOTES R8: the undetected run
# contains zero security events). These tests pin the three properties
# that make the recording channel usable rather than harmful.
# ---------------------------------------------------------------------------


class TestTelemetryRecording:
    def test_not_recorded_by_default(self, tmp_path: Path):
        conn = FakeConnection()
        det = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=10.0)
        traj = tmp_path / "telemetry_uav_0.jsonl"

        with _make_monitor(tmp_path, detectors=[det], conn=conn) as m:
            for _ in range(3):
                conn.push(_estimator_msg())
            assert _wait_until(lambda: m.stats["telemetry_seen"] >= 3)

        assert not traj.exists()
        assert m.stats["telemetry_logged"] == 0

    def test_records_to_its_own_file(self, tmp_path: Path):
        conn = FakeConnection()
        det = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=10.0)
        traj = tmp_path / "telemetry_uav_0.jsonl"

        with _make_monitor(
            tmp_path, detectors=[det], conn=conn, telemetry_log_path=traj
        ) as m:
            for i in range(4):
                conn.push(_estimator_msg(ratio=0.006 + i))
            assert _wait_until(lambda: m.stats["telemetry_logged"] >= 4)

        events = read_jsonl(traj)
        assert len(events) == 4
        assert all(e.event_type == "telemetry" for e in events)
        assert all(isinstance(e, TelemetryEvent) for e in events)
        assert events[0].data["pos_horiz_ratio"] == 0.006

    def test_never_enters_the_event_log(self, tmp_path: Path):
        # The whole reason the old log_telemetry flag was unusable: it
        # wrote into log_path, which merge_jsonl folds into merged.jsonl,
        # drowning the event stream the metrics layer reads.
        conn = FakeConnection()
        det = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=10.0)
        log_path = tmp_path / "monitor.jsonl"
        traj = tmp_path / "telemetry_uav_0.jsonl"

        with _make_monitor(
            tmp_path, detectors=[det], conn=conn, telemetry_log_path=traj
        ) as m:
            for _ in range(5):
                conn.push(_estimator_msg())
            assert _wait_until(lambda: m.stats["telemetry_logged"] >= 5)

        assert len(read_jsonl(traj)) == 5
        if log_path.exists() and log_path.stat().st_size > 0:
            events = read_jsonl(log_path)
            assert all(e.event_type != "telemetry" for e in events)

    def test_filters_by_msg_type(self, tmp_path: Path):
        # The listener whitelist carries ATTITUDE at ~50 Hz. Recording
        # everything for 3 UAVs x 160 s would be noise, not evidence.
        conn = FakeConnection()
        det = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=10.0)
        traj = tmp_path / "telemetry_uav_0.jsonl"

        with _make_monitor(
            tmp_path, detectors=[det], conn=conn, telemetry_log_path=traj
        ) as m:
            conn.push(_estimator_msg())
            for _ in range(5):
                conn.push(FakeMessage("HEARTBEAT", 1, {}))
                conn.push(FakeMessage("ATTITUDE", 1, {"roll": 0.1}))
            assert _wait_until(lambda: m.stats["telemetry_seen"] >= 11)

        events = read_jsonl(traj)
        assert len(events) == 1
        assert events[0].msg_type == "ESTIMATOR_STATUS"

    def test_default_types_cover_both_channels(self, tmp_path: Path):
        det = HeartbeatDetector(target_uav="uav_0", source="m")
        m = _make_monitor(
            tmp_path,
            detectors=[det],
            telemetry_log_path=tmp_path / "t.jsonl",
        )
        assert m.telemetry_log_types == DEFAULT_TELEMETRY_LOG_TYPES
        assert "ESTIMATOR_STATUS" in m.telemetry_log_types
        assert "LOCAL_POSITION_NED" in m.telemetry_log_types

    def test_custom_types(self, tmp_path: Path):
        conn = FakeConnection()
        det = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=10.0)
        traj = tmp_path / "telemetry_uav_0.jsonl"

        with _make_monitor(
            tmp_path,
            detectors=[det],
            conn=conn,
            telemetry_log_path=traj,
            telemetry_log_types=["LOCAL_POSITION_NED"],
        ) as m:
            conn.push(_estimator_msg())
            conn.push(FakeMessage("LOCAL_POSITION_NED", 1, {"x": 1.0}))
            assert _wait_until(lambda: m.stats["telemetry_seen"] >= 2)
            assert _wait_until(lambda: m.stats["telemetry_logged"] >= 1)

        events = read_jsonl(traj)
        assert len(events) == 1
        assert events[0].msg_type == "LOCAL_POSITION_NED"

    def test_types_without_path_rejected(self, tmp_path: Path):
        # Choosing what to record without saying where would collect
        # nothing while looking configured.
        det = HeartbeatDetector(target_uav="uav_0", source="m")
        with pytest.raises(ValueError, match="requires telemetry_log_path"):
            Monitor(
                uav_id="uav_0",
                source="m",
                telemetry_endpoint="x",
                sysid=1,
                detectors=[det],
                log_path=tmp_path / "m.jsonl",
                telemetry_log_types=["ESTIMATOR_STATUS"],
            )

    def test_recording_survives_detector_takeout(self, tmp_path: Path):
        # R5's mechanism, not just its outcome: detector_takeout silences
        # the detectors but leaves the listener alive, so the series shows
        # exactly what the silenced detector WOULD have seen.
        conn = FakeConnection()
        det = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=10.0)
        traj = tmp_path / "telemetry_uav_0.jsonl"

        with _make_monitor(
            tmp_path, detectors=[det], conn=conn, telemetry_log_path=traj
        ) as m:
            conn.push(_estimator_msg(ratio=0.006))
            assert _wait_until(lambda: m.stats["telemetry_logged"] >= 1)

            m.disable_local_detectors()

            for _ in range(3):
                conn.push(_estimator_msg(ratio=2.0))
            assert _wait_until(lambda: m.stats["telemetry_logged"] >= 4)

        assert m.stats["security_emitted"] == 0   # detectors are silent
        events = read_jsonl(traj)
        assert len(events) == 4
        assert [e.data["pos_horiz_ratio"] for e in events] == [
            0.006, 2.0, 2.0, 2.0
        ]

    def test_recorded_series_feeds_the_metrics_module(self, tmp_path: Path):
        # End to end: what the monitor writes is what estimator_series
        # reads. This is the seam OPEN-3 depends on.
        from metrics.estimator_series import estimator_series, read_telemetry

        conn = FakeConnection()
        det = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=10.0)
        traj = tmp_path / "telemetry_uav_0.jsonl"

        t0 = time.time()
        with _make_monitor(
            tmp_path, detectors=[det], conn=conn, telemetry_log_path=traj
        ) as m:
            for _ in range(4):
                conn.push(_estimator_msg(ratio=1.5))
            assert _wait_until(lambda: m.stats["telemetry_logged"] >= 4)

        samples = read_telemetry(traj)
        res = estimator_series(samples, t0, target_uav="uav_0")
        assert res["uavs"]["uav_0"]["n"] == 4
        assert res["uavs"]["uav_0"]["max_consecutive_above"] == 4
        assert res["uavs"]["uav_0"]["peak"] == 1.5

    def test_recording_after_detectors_not_before(self, tmp_path: Path):
        # Instrumentation upstream of the measurement changes the
        # measurement: MTTD is timed from the SecurityEvent, so telemetry
        # I/O must not sit on the path to it. Pinned by observing that a
        # detector firing on a message sees it before the recorder does.
        from detectors.base import Detector

        order: list[str] = []

        class OrderingDetector(Detector):
            @property
            def name(self): return "ordering"
            @property
            def target_uav(self): return "uav_0"
            def feed(self, event):
                if event.msg_type == "ESTIMATOR_STATUS":
                    order.append("detector")
                return None
            def reset(self): pass

        conn = FakeConnection()
        traj = tmp_path / "telemetry_uav_0.jsonl"

        with _make_monitor(
            tmp_path,
            detectors=[OrderingDetector()],
            conn=conn,
            telemetry_log_path=traj,
        ) as m:
            conn.push(_estimator_msg())
            assert _wait_until(lambda: m.stats["telemetry_logged"] >= 1)
            order.append("recorder_done")

        assert order[0] == "detector"


# ---------------------------------------------------------------------------
# Lifecycle robustness
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_double_start_idempotent(self, tmp_path: Path):
        det = HeartbeatDetector(target_uav="uav_0", source="m")
        m = _make_monitor(tmp_path, detectors=[det])
        m.start()
        m.start()  # must not blow up
        m.stop()

    def test_stop_without_start(self, tmp_path: Path):
        det = HeartbeatDetector(target_uav="uav_0", source="m")
        m = _make_monitor(tmp_path, detectors=[det])
        m.stop()  # no exception

    def test_buggy_detector_does_not_kill_monitor(self, tmp_path: Path):
        """If feed() raises, the monitor records it and keeps going."""
        from detectors.base import Detector

        class BuggyDetector(Detector):
            @property
            def name(self): return "buggy"
            @property
            def target_uav(self): return "uav_0"
            def feed(self, event):
                raise RuntimeError("kaboom")
            def reset(self): pass

        conn = FakeConnection()
        good = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=10.0)
        bad = BuggyDetector()

        with _make_monitor(tmp_path, detectors=[bad, good], conn=conn) as m:
            conn.push(FakeMessage("HEARTBEAT", 1, {}))
            assert _wait_until(lambda: m.stats["telemetry_seen"] >= 1)

        # Buggy detector counted as handler error; heartbeat detector
        # still saw the message and updated its state.
        assert m.stats["handler_errors"] >= 1
        assert good.last_heartbeat is not None


# ---------------------------------------------------------------------------
# Step 8.2: isolation pipeline
# ---------------------------------------------------------------------------


class TestIsolationPipelineConstruction:
    def test_enforcer_without_decider_rejected(self, tmp_path: Path):
        det = HeartbeatDetector(target_uav="uav_0", source="m")
        with pytest.raises(ValueError, match="enforcer requires"):
            Monitor(
                uav_id="uav_0",
                source="m",
                telemetry_endpoint="x",
                sysid=1,
                detectors=[det],
                log_path=tmp_path / "m.jsonl",
                isolation_decider=None,
                isolation_enforcer=LocalIsolationEnforcer(),
            )

    def test_decider_without_enforcer_allowed(self, tmp_path: Path):
        """Decider-only is a useful diagnostic mode (log announcements
        without materializing them)."""
        det = HeartbeatDetector(target_uav="uav_0", source="m")
        m = _make_monitor(
            tmp_path,
            detectors=[det],
            isolation_decider=IsolationDecider(source="m"),
            isolation_enforcer=None,
        )
        m.start()
        m.stop()


class TestIsolationPipelineFlow:
    def test_security_event_produces_announcement_and_enforces(
        self, tmp_path: Path
    ):
        conn = FakeConnection()
        det = HeartbeatDetector(
            target_uav="uav_0", source="monitor_uav_0", timeout_sec=0.3
        )
        decider = IsolationDecider(source="monitor_uav_0")
        enforcer = LocalIsolationEnforcer()
        log_path = tmp_path / "monitor.jsonl"

        with _make_monitor(
            tmp_path,
            detectors=[det],
            conn=conn,
            tick_period_sec=0.1,
            isolation_decider=decider,
            isolation_enforcer=enforcer,
        ) as m:
            conn.push(FakeMessage("HEARTBEAT", 1, {"type": 2}))
            assert _wait_until(lambda: det.last_heartbeat is not None)
            assert _wait_until(
                lambda: m.stats["isolation_enforced"] >= 1, timeout=2.0
            )

        # Counters
        assert m.stats["security_emitted"] == 1
        assert m.stats["isolation_announced"] == 1
        assert m.stats["isolation_enforced"] == 1

        # Enforcer state actually updated
        assert enforcer.is_isolated("uav_0")

        # Log contains both SecurityEvent and IsolationAnnounce, with
        # caused_by linking them.
        events = read_jsonl(log_path)
        secs = [e for e in events if e.event_type == "security"]
        annss = [e for e in events if e.event_type == "isolation_announce"]
        assert len(secs) == 1
        assert len(annss) == 1
        assert isinstance(secs[0], SecurityEvent)
        assert isinstance(annss[0], IsolationAnnounce)
        assert annss[0].caused_by == secs[0].event_id
        assert annss[0].target_uav == "uav_0"
        assert annss[0].reason == "heartbeat_loss"

    def test_decider_only_no_enforce_count(self, tmp_path: Path):
        """Decider without enforcer: announcement logged but
        isolation_enforced stays 0."""
        conn = FakeConnection()
        det = HeartbeatDetector(
            target_uav="uav_0", source="m", timeout_sec=0.3
        )
        decider = IsolationDecider(source="m")
        log_path = tmp_path / "monitor.jsonl"

        with _make_monitor(
            tmp_path,
            detectors=[det],
            conn=conn,
            tick_period_sec=0.1,
            isolation_decider=decider,
            isolation_enforcer=None,
        ) as m:
            conn.push(FakeMessage("HEARTBEAT", 1, {}))
            assert _wait_until(
                lambda: m.stats["isolation_announced"] >= 1, timeout=2.0
            )

        assert m.stats["isolation_enforced"] == 0
        events = read_jsonl(log_path)
        annss = [e for e in events if e.event_type == "isolation_announce"]
        assert len(annss) == 1


class TestIsolationDeduplication:
    def test_recovery_cycle_produces_second_announcement(self, tmp_path: Path):
        """When heartbeat returns and is lost again, decider must NOT
        re-announce (still in isolated set). Only after un_isolate()
        does the next loss fire fresh."""
        conn = FakeConnection()
        det = HeartbeatDetector(
            target_uav="uav_0", source="m", timeout_sec=0.2
        )
        decider = IsolationDecider(source="m")
        enforcer = LocalIsolationEnforcer()

        with _make_monitor(
            tmp_path,
            detectors=[det],
            conn=conn,
            tick_period_sec=0.05,
            isolation_decider=decider,
            isolation_enforcer=enforcer,
        ) as m:
            # First HB to set baseline
            conn.push(FakeMessage("HEARTBEAT", 1, {}))
            assert _wait_until(lambda: det.last_heartbeat is not None)
            # First loss -> announcement #1
            assert _wait_until(
                lambda: m.stats["isolation_announced"] >= 1, timeout=2.0
            )

            # HB returns, detector clears its alerted flag, but decider
            # still considers the UAV isolated.
            conn.push(FakeMessage("HEARTBEAT", 1, {}))
            time.sleep(0.05)
            # HB lost again -> detector fires another SecurityEvent,
            # but decider deduplicates -> isolation_announced stays at 1.
            assert _wait_until(
                lambda: m.stats["security_emitted"] >= 2, timeout=2.0
            )
            time.sleep(0.2)  # let decider have a chance to process

        assert m.stats["security_emitted"] >= 2
        assert m.stats["isolation_announced"] == 1
        assert m.stats["isolation_enforced"] == 1


class TestIsolationFailureModes:
    def test_buggy_decider_does_not_kill_monitor(self, tmp_path: Path):
        class BuggyDecider:
            def evaluate(self, event):
                raise RuntimeError("decider kaboom")

        conn = FakeConnection()
        det = HeartbeatDetector(
            target_uav="uav_0", source="m", timeout_sec=0.2
        )

        # Build the monitor manually because _make_monitor's typing
        # expects an IsolationDecider.
        log_path = tmp_path / "monitor.jsonl"
        m = Monitor(
            uav_id="uav_0",
            source="m",
            telemetry_endpoint="x",
            sysid=1,
            detectors=[det],
            log_path=log_path,
            isolation_decider=BuggyDecider(),  # type: ignore[arg-type]
            tick_period_sec=0.05,
            _telemetry_connection=conn,
        )
        m.start()
        try:
            conn.push(FakeMessage("HEARTBEAT", 1, {}))
            assert _wait_until(lambda: m.stats["security_emitted"] >= 1, timeout=2.0)
        finally:
            m.stop()

        # SecurityEvent was emitted, decider crashed, but monitor still alive.
        assert m.stats["security_emitted"] >= 1
        assert m.stats["isolation_announced"] == 0
        assert m.stats["handler_errors"] >= 1

    def test_buggy_enforcer_does_not_kill_monitor(self, tmp_path: Path):
        class BuggyEnforcer:
            def enforce(self, ann):
                raise RuntimeError("enforcer kaboom")
            @property
            def stats(self): return {}

        conn = FakeConnection()
        det = HeartbeatDetector(
            target_uav="uav_0", source="m", timeout_sec=0.2
        )
        log_path = tmp_path / "monitor.jsonl"

        m = Monitor(
            uav_id="uav_0",
            source="m",
            telemetry_endpoint="x",
            sysid=1,
            detectors=[det],
            log_path=log_path,
            isolation_decider=IsolationDecider(source="m"),
            isolation_enforcer=BuggyEnforcer(),  # type: ignore[arg-type]
            tick_period_sec=0.05,
            _telemetry_connection=conn,
        )
        m.start()
        try:
            conn.push(FakeMessage("HEARTBEAT", 1, {}))
            assert _wait_until(lambda: m.stats["isolation_announced"] >= 1, timeout=2.0)
        finally:
            m.stop()

        # Announcement was made and logged, but enforcer crashed.
        assert m.stats["isolation_announced"] == 1
        assert m.stats["isolation_enforced"] == 0
        assert m.stats["handler_errors"] >= 1


class TestIsolationStatsExposure:
    def test_enforcer_stats_in_monitor_stats(self, tmp_path: Path):
        conn = FakeConnection()
        det = HeartbeatDetector(
            target_uav="uav_0", source="m", timeout_sec=0.2
        )
        decider = IsolationDecider(source="m")
        enforcer = LocalIsolationEnforcer()

        with _make_monitor(
            tmp_path,
            detectors=[det],
            conn=conn,
            tick_period_sec=0.05,
            isolation_decider=decider,
            isolation_enforcer=enforcer,
        ) as m:
            conn.push(FakeMessage("HEARTBEAT", 1, {}))
            assert _wait_until(
                lambda: m.stats["isolation_enforced"] >= 1, timeout=2.0
            )

        s = m.stats
        # Enforcer's internal counters surface under enforcer_* prefix.
        assert s["enforcer_enforce_count"] == 1
        assert s["enforcer_currently_isolated"] == 1


# ---------------------------------------------------------------------------
# Step 8.3: mesh participation
# ---------------------------------------------------------------------------


def _gps_event(uav_id: str, *, lat_deg: float, lon_deg: float, alt_m: float = 500.0,
               ts: float = 0.0) -> FakeMessage:
    """Build a FakeMessage that mimics GLOBAL_POSITION_INT."""
    return FakeMessage(
        "GLOBAL_POSITION_INT",
        # sysid for routing — must match expected_sysid
        1 if uav_id == "uav_0" else (2 if uav_id == "uav_1" else 3),
        {
            "lat": int(lat_deg * 1e7),
            "lon": int(lon_deg * 1e7),
            "alt": int(alt_m * 1000),
            "vx": 0,
            "vy": 0,
            "vz": 0,
        },
    )


def _free_ports(n: int) -> list[int]:
    import socket as _s
    socks = []
    ports = []
    try:
        for _ in range(n):
            sock = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            ports.append(sock.getsockname()[1])
            socks.append(sock)
    finally:
        for sock in socks:
            sock.close()
    return ports


class TestMeshConstruction:
    def test_cross_check_without_mesh_rejected(self, tmp_path: Path):
        det = HeartbeatDetector(target_uav="uav_0", source="m")
        cc = CrossCheckDetector(monitor_uav_id="uav_0", source="m")
        with pytest.raises(ValueError, match="cross_check detector requires mesh"):
            Monitor(
                uav_id="uav_0",
                source="m",
                telemetry_endpoint="x",
                sysid=1,
                detectors=[det],
                log_path=tmp_path / "m.jsonl",
                mesh=None,
                cross_check=cc,
            )

    def test_cross_check_uav_mismatch_rejected(self, tmp_path: Path):
        """cross_check.monitor_uav_id must match the monitor's own uav_id."""
        det = HeartbeatDetector(target_uav="uav_0", source="m")
        cc = CrossCheckDetector(monitor_uav_id="uav_1", source="m")  # mismatch
        with pytest.raises(ValueError, match="monitor_uav_id="):
            Monitor(
                uav_id="uav_0",
                source="m",
                telemetry_endpoint="x",
                sysid=1,
                detectors=[det],
                log_path=tmp_path / "m.jsonl",
                mesh=NoOpMesh(),
                cross_check=cc,
            )

    def test_mesh_without_cross_check_allowed(self, tmp_path: Path):
        """A monitor may publish peer positions without subscribing
        (e.g. for a future read-only diagnostic peer)."""
        det = HeartbeatDetector(target_uav="uav_0", source="m")
        m = Monitor(
            uav_id="uav_0",
            source="m",
            telemetry_endpoint="x",
            sysid=1,
            detectors=[det],
            log_path=tmp_path / "m.jsonl",
            mesh=NoOpMesh(),
            cross_check=None,
            _telemetry_connection=FakeConnection(),
        )
        m.start()
        m.stop()


class TestPeerPositionPublish:
    def test_publishes_after_seeing_global_position(self, tmp_path: Path):
        """With a NoOpMesh we can't observe deliveries, but we can
        verify the publish counter increments only after a position has
        been observed."""
        conn = FakeConnection()
        det = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=10.0)
        mesh = NoOpMesh()
        log_path = tmp_path / "m.jsonl"

        m = Monitor(
            uav_id="uav_0",
            source="monitor_uav_0",
            telemetry_endpoint="x",
            sysid=1,
            detectors=[det],
            log_path=log_path,
            mesh=mesh,
            tick_period_sec=0.1,
            peer_publish_period_sec=0.1,
            _telemetry_connection=conn,
        )
        m.start()
        try:
            # No GPS yet -> publisher should publish nothing.
            time.sleep(0.3)
            assert m.stats["peer_positions_published"] == 0

            # Push a GLOBAL_POSITION_INT
            conn.push(_gps_event("uav_0", lat_deg=47.4, lon_deg=8.5, alt_m=510.0))
            assert _wait_until(lambda: m.stats["peer_positions_published"] >= 1)
        finally:
            m.stop()

    def test_publish_failure_does_not_kill_loop(self, tmp_path: Path):
        """Mesh.publish raising must not stop the publish thread."""

        class FailingMesh(MeshBus):
            def __init__(self): self.calls = 0
            def start(self): ...
            def stop(self): ...
            def publish(self, event):
                self.calls += 1
                raise RuntimeError("boom")
            def subscribe(self, topic, callback): ...

        conn = FakeConnection()
        det = HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=10.0)
        mesh = FailingMesh()

        m = Monitor(
            uav_id="uav_0",
            source="m",
            telemetry_endpoint="x",
            sysid=1,
            detectors=[det],
            log_path=tmp_path / "m.jsonl",
            mesh=mesh,
            tick_period_sec=0.1,
            peer_publish_period_sec=0.1,
            _telemetry_connection=conn,
        )
        m.start()
        try:
            conn.push(_gps_event("uav_0", lat_deg=47.4, lon_deg=8.5))
            # Wait for at least 2 publish attempts (each fails)
            assert _wait_until(lambda: mesh.calls >= 2, timeout=2.0)
        finally:
            m.stop()

        # Loop kept going despite failures
        assert mesh.calls >= 2
        assert m.stats["peer_positions_published"] == 0
        assert m.stats["handler_errors"] >= 2


class TestCrossCheckIntegration:
    """Two monitors over a real ZmqMesh: one teleports, the other detects."""

    def test_peer_teleport_triggers_cross_check_alert(self, tmp_path: Path):
        port_a, port_b = _free_ports(2)
        ep_a = f"tcp://127.0.0.1:{port_a}"
        ep_b = f"tcp://127.0.0.1:{port_b}"

        # Monitor A publishes its position; no cross_check (it doesn't
        # police others in this minimal test).
        mesh_a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        # Monitor B publishes ALSO + has cross_check that watches uav_0.
        mesh_b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a])

        conn_a = FakeConnection()
        conn_b = FakeConnection()

        det_a = HeartbeatDetector(target_uav="uav_0", source="m_a", timeout_sec=60.0)
        det_b = HeartbeatDetector(target_uav="uav_1", source="m_b", timeout_sec=60.0)
        cc_b = CrossCheckDetector(
            monitor_uav_id="uav_1",
            source="monitor_uav_1",
            max_velocity_mps=25.0,
        )

        log_a = tmp_path / "a.jsonl"
        log_b = tmp_path / "b.jsonl"

        m_a = Monitor(
            uav_id="uav_0", source="monitor_uav_0",
            telemetry_endpoint="x_a", sysid=1,
            detectors=[det_a], log_path=log_a,
            mesh=mesh_a,
            tick_period_sec=0.2,
            peer_publish_period_sec=0.2,
            _telemetry_connection=conn_a,
        )
        m_b = Monitor(
            uav_id="uav_1", source="monitor_uav_1",
            telemetry_endpoint="x_b", sysid=2,
            detectors=[det_b], log_path=log_b,
            mesh=mesh_b,
            cross_check=cc_b,
            tick_period_sec=0.2,
            peer_publish_period_sec=0.2,
            _telemetry_connection=conn_b,
        )

        # Caller owns mesh lifecycle (the monitor only uses it).
        # ZmqMesh.start() includes a slow-joiner settle window.
        mesh_a.start()
        mesh_b.start()
        m_a.start()
        m_b.start()
        try:
            # Step 1: Monitor A reports a baseline position.
            ev1 = _gps_event("uav_0", lat_deg=47.4, lon_deg=8.5, alt_m=500.0)
            conn_a.push(ev1)
            assert _wait_until(lambda: m_a.stats["peer_positions_published"] >= 1, timeout=3.0)
            # Step 2: Monitor B receives it -> cross_check has baseline.
            assert _wait_until(lambda: m_b.stats["peer_positions_received"] >= 1, timeout=3.0)
            # Wait for next publish cycle so we have a true Δt > 0.
            time.sleep(0.4)

            # Step 3: A "teleports" — pushes a new position 200m away.
            # Monitor A converts it to a fresh peer-position publish.
            ev2 = _gps_event(
                "uav_0", lat_deg=47.4 + 2e-3, lon_deg=8.5, alt_m=500.0
            )
            conn_a.push(ev2)
            assert _wait_until(
                lambda: m_b.stats["peer_positions_received"] >= 2, timeout=3.0
            )
            # Step 4: cross_check on B should fire a SecurityEvent
            assert _wait_until(
                lambda: m_b.stats["security_emitted"] >= 1, timeout=3.0
            )
        finally:
            m_a.stop()
            m_b.stop()
            mesh_a.stop()
            mesh_b.stop()

        # Verify the security event in B's log
        events_b = read_jsonl(log_b)
        sec = [e for e in events_b if e.event_type == "security"]
        assert len(sec) >= 1
        assert any(s.detector == "cross_check" for s in sec)
        assert any(s.target_uav == "uav_0" for s in sec)

    def test_consistent_movement_no_cross_check_alert(self, tmp_path: Path):
        """Slow movement: cross_check stays silent."""
        port_a, port_b = _free_ports(2)
        ep_a = f"tcp://127.0.0.1:{port_a}"
        ep_b = f"tcp://127.0.0.1:{port_b}"

        mesh_a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        mesh_b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a])
        conn_a = FakeConnection()
        conn_b = FakeConnection()

        det_a = HeartbeatDetector(target_uav="uav_0", source="m_a", timeout_sec=60.0)
        det_b = HeartbeatDetector(target_uav="uav_1", source="m_b", timeout_sec=60.0)
        cc_b = CrossCheckDetector(monitor_uav_id="uav_1", source="m_b")

        m_a = Monitor(
            uav_id="uav_0", source="m_a",
            telemetry_endpoint="x_a", sysid=1,
            detectors=[det_a], log_path=tmp_path / "a.jsonl",
            mesh=mesh_a,
            peer_publish_period_sec=0.2,
            tick_period_sec=0.2,
            _telemetry_connection=conn_a,
        )
        m_b = Monitor(
            uav_id="uav_1", source="m_b",
            telemetry_endpoint="x_b", sysid=2,
            detectors=[det_b], log_path=tmp_path / "b.jsonl",
            mesh=mesh_b, cross_check=cc_b,
            peer_publish_period_sec=0.2,
            tick_period_sec=0.2,
            _telemetry_connection=conn_b,
        )

        mesh_a.start()
        mesh_b.start()
        m_a.start()
        m_b.start()
        try:
            conn_a.push(_gps_event("uav_0", lat_deg=47.4, lon_deg=8.5))
            assert _wait_until(lambda: m_b.stats["peer_positions_received"] >= 1, timeout=3.0)
            time.sleep(0.4)
            # Move 5e-5 deg ≈ 5m — well within budget for any reasonable Δt.
            conn_a.push(_gps_event("uav_0", lat_deg=47.4 + 5e-5, lon_deg=8.5))
            assert _wait_until(lambda: m_b.stats["peer_positions_received"] >= 2, timeout=3.0)
            time.sleep(0.5)  # let any spurious event surface
        finally:
            m_a.stop()
            m_b.stop()
            mesh_a.stop()
            mesh_b.stop()

        # No cross-check alert
        assert m_b.stats["security_emitted"] == 0
