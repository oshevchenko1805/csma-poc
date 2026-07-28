"""Tests for enforcement.command_guard.CommandGuard.

The relay is real UDP but entirely local and fast: we bind a receiver on
the forward port, send frames at the guard's listen port, and assert what
comes out the other side. This proves the guard filters on MAVLink sysid,
not on port — the whole point of it being a real control.
"""

from __future__ import annotations

import socket
import time

import pytest

from enforcement.command_guard import CommandGuard, parse_sysid


def _v2_frame(sysid: int, payload: bytes = b"\x00\x00") -> bytes:
    # Minimal MAVLink v2 frame: magic 0xFD, then len, incompat, compat,
    # seq, sysid at byte[5], compid, msgid(3)... payload. We only need the
    # first 6 bytes to be well-formed for sysid parsing.
    return bytes([0xFD, len(payload), 0, 0, 0, sysid & 0xFF, 1, 0, 0, 0]) + payload


def _v1_frame(sysid: int, payload: bytes = b"\x00\x00") -> bytes:
    # MAVLink v1: magic 0xFE, len, seq, sysid at byte[3], compid, msgid.
    return bytes([0xFE, len(payload), 0, sysid & 0xFF, 1, 0]) + payload


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestParseSysid:
    def test_v2(self):
        assert parse_sysid(_v2_frame(99)) == 99
        assert parse_sysid(_v2_frame(1)) == 1

    def test_v1(self):
        assert parse_sysid(_v1_frame(42)) == 42

    def test_unparseable(self):
        assert parse_sysid(b"") is None
        assert parse_sysid(b"\x00\x01") is None
        assert parse_sysid(b"\xfd\x00") is None  # too short for v2 sysid


class _Sink:
    """A UDP receiver standing in for the autopilot's command port."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(1.0)

    @property
    def port(self) -> int:
        return self.sock.getsockname()[1]

    def recv_all(self, deadline_sec: float = 0.5) -> list[bytes]:
        out: list[bytes] = []
        end = time.time() + deadline_sec
        while time.time() < end:
            try:
                self.sock.settimeout(max(0.01, end - time.time()))
                out.append(self.sock.recvfrom(4096)[0])
            except socket.timeout:
                break
        return out

    def close(self) -> None:
        self.sock.close()


def _send(port: int, frame: bytes) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(frame, ("127.0.0.1", port))
    s.close()


@pytest.fixture
def guarded():
    sink = _Sink()
    listen = _free_port()
    g = CommandGuard(listen_port=listen, forward_port=sink.port)
    g.start()
    time.sleep(0.05)  # let the thread bind + enter recv
    yield g, listen, sink
    g.stop()
    sink.close()


class TestTransparentByDefault:
    def test_forwards_everything_when_not_filtering(self, guarded):
        g, listen, sink = guarded
        _send(listen, _v2_frame(99))
        _send(listen, _v2_frame(1))
        got = sink.recv_all()
        assert len(got) == 2
        assert g.forwarded == 2
        assert g.dropped == 0


class TestFilteringBySysid:
    def test_drops_non_whitelisted_forwards_whitelisted(self, guarded):
        g, listen, sink = guarded
        g.start_filtering()
        _send(listen, _v2_frame(99))   # attacker -> dropped
        _send(listen, _v2_frame(1))    # legit    -> forwarded
        _send(listen, _v2_frame(255))  # GCS      -> forwarded
        got = sink.recv_all()
        # Only the two whitelisted frames make it through.
        assert len(got) == 2
        assert g.dropped == 1
        assert g.forwarded == 2

    def test_stop_filtering_restores_transparency(self, guarded):
        g, listen, sink = guarded
        g.start_filtering()
        _send(listen, _v2_frame(99))
        sink.recv_all()
        assert g.dropped == 1
        g.stop_filtering()
        _send(listen, _v2_frame(99))
        got = sink.recv_all()
        assert len(got) == 1  # now forwarded
        assert g.forwarded == 1


class TestLifecycleIdempotent:
    def test_double_start_and_stop(self, guarded):
        g, listen, sink = guarded
        g.start()  # second start is a no-op
        _send(listen, _v2_frame(1))
        sink.recv_all()
        assert g.forwarded == 1
        g.stop()
        g.stop()  # idempotent
