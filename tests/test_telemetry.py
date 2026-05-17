"""
Unit tests for core.telemetry.

These tests inject a FakeConnection in place of pymavlink, so they verify
listener logic (sysid filter, type filter, sanitization, callback dispatch,
lifecycle) without needing a live MAVLink endpoint.

A live PX4 SITL smoke-test lives in scripts/smoke_telemetry.py and is run
manually.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

import pytest

from core.events import TelemetryEvent
from core.telemetry import (
    DEFAULT_MSG_WHITELIST,
    TelemetryListener,
    _sanitize_dict,
    _sanitize_value,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeMessage:
    """Minimum pymavlink-message lookalike."""

    def __init__(self, type_name: str, sysid: int, fields: Optional[dict] = None):
        self._type = type_name
        self._sysid = sysid
        self._fields = dict(fields or {})

    def get_type(self) -> str:
        return self._type

    def get_srcSystem(self) -> int:
        return self._sysid

    def to_dict(self) -> dict:
        return dict(self._fields)


class FakeConnection:
    """
    Replacement for pymavlink.mavutil.mavlink_connection().

    Supports recv_match() with type filter and timeout-blocking semantics.
    Thread-safe so the listener thread can read while tests push messages.
    """

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
                    # Drop messages outside the filter (mirrors real pymavlink
                    # behavior of skipping rather than buffering).
                    self._q.popleft()
                    continue
            if not blocking or time.time() >= deadline:
                return None
            time.sleep(0.005)

    def close(self) -> None:
        self._closed = True


# ---------------------------------------------------------------------------
# sanitization
# ---------------------------------------------------------------------------


class TestSanitize:
    def test_primitives_pass_through(self):
        assert _sanitize_value(1) == 1
        assert _sanitize_value(1.5) == 1.5
        assert _sanitize_value("hi") == "hi"
        assert _sanitize_value(True) is True
        assert _sanitize_value(None) is None

    def test_bytes_decoded_and_trimmed(self):
        assert _sanitize_value(b"hello\x00\x00\x00") == "hello"

    def test_lists_and_tuples_become_lists(self):
        assert _sanitize_value([1, 2, 3]) == [1, 2, 3]
        assert _sanitize_value((1, 2, b"x\x00")) == [1, 2, "x"]

    def test_nested_dict(self):
        d = {"a": 1, "b": {"c": b"x\x00", "d": [1, 2]}}
        assert _sanitize_dict(d) == {"a": 1, "b": {"c": "x", "d": [1, 2]}}

    def test_unknown_type_falls_back_to_repr(self):
        class Weird:
            def __repr__(self):
                return "<weird>"
        assert _sanitize_value(Weird()) == "<weird>"


# ---------------------------------------------------------------------------
# TelemetryListener
# ---------------------------------------------------------------------------


def _wait_until(predicate, timeout: float = 2.0, poll: float = 0.02) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(poll)
    return predicate()


class TestTelemetryListener:
    def test_emits_event_for_whitelisted_message(self):
        conn = FakeConnection()
        received: list[TelemetryEvent] = []

        listener = TelemetryListener(
            endpoint="udpin:127.0.0.1:14540",
            expected_sysid=1,
            uav_id="uav_0",
            source="monitor_uav_0",
            callback=received.append,
            _connection=conn,
            recv_timeout_sec=0.05,
        )

        with listener:
            conn.push(FakeMessage("HEARTBEAT", 1, {"type": 2, "autopilot": 12}))
            assert _wait_until(lambda: len(received) == 1)

        ev = received[0]
        assert isinstance(ev, TelemetryEvent)
        assert ev.uav_id == "uav_0"
        assert ev.source == "monitor_uav_0"
        assert ev.msg_type == "HEARTBEAT"
        assert ev.data == {"type": 2, "autopilot": 12, "_src_sysid": 1}

    def test_filters_by_sysid(self):
        conn = FakeConnection()
        received: list[TelemetryEvent] = []

        listener = TelemetryListener(
            endpoint="udpin:127.0.0.1:14540",
            expected_sysid=2,
            uav_id="uav_1",
            source="monitor_uav_1",
            callback=received.append,
            _connection=conn,
            recv_timeout_sec=0.05,
        )

        with listener:
            # Wrong sysid — must be filtered out.
            conn.push(FakeMessage("HEARTBEAT", 1, {"type": 2}))
            conn.push(FakeMessage("HEARTBEAT", 3, {"type": 2}))
            # Correct sysid — must be emitted.
            conn.push(FakeMessage("HEARTBEAT", 2, {"type": 2}))
            assert _wait_until(lambda: len(received) == 1)

        assert listener.stats["emitted"] == 1
        assert listener.stats["filtered_sysid"] == 2

    def test_command_messages_pass_sysid_filter(self):
        """COMMAND_LONG/COMMAND_INT bypass the listener's sysid filter so
        command-injection attack packets (which by definition use a
        non-whitelist src_sysid) reach the detector. Other message types
        are still filtered strictly."""
        conn = FakeConnection()
        received: list[TelemetryEvent] = []

        listener = TelemetryListener(
            endpoint="x",
            expected_sysid=1,
            uav_id="uav_0",
            source="m",
            callback=received.append,
            _connection=conn,
            recv_timeout_sec=0.05,
        )

        with listener:
            # Rogue sysid on a HEARTBEAT — filtered (control).
            conn.push(FakeMessage("HEARTBEAT", 99, {}))
            # Rogue sysid on COMMAND_LONG — passes through.
            conn.push(
                FakeMessage(
                    "COMMAND_LONG",
                    99,
                    {"command": 192, "target_system": 1, "target_component": 1},
                )
            )
            # Rogue sysid on COMMAND_INT — also passes through.
            conn.push(
                FakeMessage(
                    "COMMAND_INT",
                    77,
                    {"command": 16, "target_system": 1, "target_component": 1},
                )
            )
            assert _wait_until(lambda: len(received) == 2)

        # HEARTBEAT was filtered, both COMMAND_* were emitted.
        msg_types = sorted(ev.msg_type for ev in received)
        assert msg_types == ["COMMAND_INT", "COMMAND_LONG"]
        # Each carries the rogue _src_sysid for the detector to evaluate.
        by_type = {ev.msg_type: ev for ev in received}
        assert by_type["COMMAND_LONG"].data["_src_sysid"] == 99
        assert by_type["COMMAND_INT"].data["_src_sysid"] == 77
        # Stats reflect: HEARTBEAT filtered_sysid=1, two commands emitted.
        assert listener.stats["filtered_sysid"] == 1
        assert listener.stats["emitted"] == 2

    def test_default_whitelist_used_when_none(self):
        conn = FakeConnection()
        received: list[TelemetryEvent] = []

        listener = TelemetryListener(
            endpoint="x",
            expected_sysid=1,
            uav_id="uav_0",
            source="m",
            callback=received.append,
            _connection=conn,
            recv_timeout_sec=0.05,
        )
        assert listener.msg_whitelist == DEFAULT_MSG_WHITELIST

        with listener:
            conn.push(FakeMessage("ESTIMATOR_STATUS", 1, {"vel_ratio": 0.4}))
            assert _wait_until(lambda: len(received) == 1)

    def test_custom_whitelist_restricts(self):
        conn = FakeConnection()
        received: list[TelemetryEvent] = []

        listener = TelemetryListener(
            endpoint="x",
            expected_sysid=1,
            uav_id="uav_0",
            source="m",
            msg_whitelist={"HEARTBEAT"},  # only this
            callback=received.append,
            _connection=conn,
            recv_timeout_sec=0.05,
        )

        with listener:
            conn.push(FakeMessage("HEARTBEAT", 1, {}))
            conn.push(FakeMessage("ATTITUDE", 1, {}))
            conn.push(FakeMessage("HEARTBEAT", 1, {}))
            # FakeConnection drops outside-filter messages, so only HEARTBEATs
            # ever reach the listener.
            assert _wait_until(lambda: len(received) == 2)

        for ev in received:
            assert ev.msg_type == "HEARTBEAT"

    def test_sanitizes_bytes_field(self):
        conn = FakeConnection()
        received: list[TelemetryEvent] = []

        listener = TelemetryListener(
            endpoint="x",
            expected_sysid=1,
            uav_id="uav_0",
            source="m",
            msg_whitelist={"STATUSTEXT"},
            callback=received.append,
            _connection=conn,
            recv_timeout_sec=0.05,
        )

        with listener:
            conn.push(
                FakeMessage(
                    "STATUSTEXT",
                    1,
                    {"severity": 6, "text": b"Takeoff detected\x00\x00\x00"},
                )
            )
            assert _wait_until(lambda: len(received) == 1)

        ev = received[0]
        assert ev.data["text"] == "Takeoff detected"
        assert ev.data["severity"] == 6

    def test_callback_exception_does_not_kill_loop(self):
        conn = FakeConnection()
        good: list[TelemetryEvent] = []

        first_call = {"count": 0}

        def cb(event: TelemetryEvent) -> None:
            first_call["count"] += 1
            if first_call["count"] == 1:
                raise RuntimeError("first callback bug")
            good.append(event)

        listener = TelemetryListener(
            endpoint="x",
            expected_sysid=1,
            uav_id="uav_0",
            source="m",
            callback=cb,
            _connection=conn,
            recv_timeout_sec=0.05,
        )

        with listener:
            conn.push(FakeMessage("HEARTBEAT", 1, {}))
            conn.push(FakeMessage("HEARTBEAT", 1, {}))
            conn.push(FakeMessage("HEARTBEAT", 1, {}))
            assert _wait_until(lambda: len(good) == 2)

        assert listener.stats["callback_errors"] == 1
        assert listener.stats["emitted"] == 3

    def test_double_start_is_idempotent(self):
        conn = FakeConnection()
        listener = TelemetryListener(
            endpoint="x",
            expected_sysid=1,
            uav_id="uav_0",
            source="m",
            _connection=conn,
            recv_timeout_sec=0.05,
        )
        listener.start()
        listener.start()  # must not blow up
        listener.stop()

    def test_stop_without_start_is_idempotent(self):
        listener = TelemetryListener(
            endpoint="x",
            expected_sysid=1,
            uav_id="uav_0",
            source="m",
            _connection=FakeConnection(),
        )
        listener.stop()  # must not blow up

    def test_stats_tracked_correctly(self):
        conn = FakeConnection()
        listener = TelemetryListener(
            endpoint="x",
            expected_sysid=1,
            uav_id="uav_0",
            source="m",
            msg_whitelist={"HEARTBEAT"},
            _connection=conn,
            recv_timeout_sec=0.05,
        )
        with listener:
            conn.push(FakeMessage("HEARTBEAT", 1, {}))  # emit
            conn.push(FakeMessage("HEARTBEAT", 2, {}))  # wrong sysid
            conn.push(FakeMessage("HEARTBEAT", 1, {}))  # emit
            assert _wait_until(lambda: listener.stats["emitted"] == 2)

        s = listener.stats
        assert s["emitted"] == 2
        assert s["filtered_sysid"] == 1
        assert s["received"] == 3

    def test_no_callback_does_not_crash(self):
        """Listener still records stats even without a callback."""
        conn = FakeConnection()
        listener = TelemetryListener(
            endpoint="x",
            expected_sysid=1,
            uav_id="uav_0",
            source="m",
            _connection=conn,
            recv_timeout_sec=0.05,
        )
        with listener:
            conn.push(FakeMessage("HEARTBEAT", 1, {}))
            assert _wait_until(lambda: listener.stats["emitted"] == 1)
