"""Tests for mesh channel delay (instrumentation item 4b).

Delay is a constant per-frame deferral of DISPATCH, applied on the receiver
thread without blocking the poll loop. Properties under test:

  - default delay_sec=0.0 is a strict no-op (inline dispatch, prompt);
  - delay defers the callback but NOT the delivered tally (the frame crossed
    the wire on time — only subscribers see it late);
  - FIFO order is preserved under constant delay;
  - delay composes with loss (an erased frame is never queued or dispatched);
  - a negative delay is rejected.

Timing tests use a generous 0.6 s delay and loose bounds to stay robust.
"""

from __future__ import annotations

import socket
import time

import pytest

from core.events import SecurityEvent
from core.mesh import ZmqMesh


def _free_ports(n: int) -> list[int]:
    socks = []
    ports = []
    try:
        for _ in range(n):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", 0))
            ports.append(s.getsockname()[1])
            socks.append(s)
    finally:
        for s in socks:
            s.close()
    return ports


def _wait_until(predicate, timeout_sec: float = 3.0, poll_sec: float = 0.02) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(poll_sec)
    return predicate()


def _sec(detector="gps"):
    return SecurityEvent(source="a", detector=detector, target_uav="uav_2")


class TestChannelDelay:
    def test_default_delay_is_zero_and_dispatches_inline(self):
        """No delay configured: behaviour is unchanged, delivery is prompt."""
        pa, pb = _free_ports(2)
        ep_a, ep_b = f"tcp://127.0.0.1:{pa}", f"tcp://127.0.0.1:{pb}"
        got: list = []
        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a])
        assert b._delay_sec == 0.0
        try:
            a.start()
            b.start()
            b.subscribe("security", lambda e: got.append(e))
            a.publish(_sec())
            assert _wait_until(lambda: len(got) == 1, timeout_sec=1.0)
        finally:
            a.stop()
            b.stop()

    def test_delay_defers_dispatch_but_not_the_delivered_tally(self):
        pa, pb = _free_ports(2)
        ep_a, ep_b = f"tcp://127.0.0.1:{pa}", f"tcp://127.0.0.1:{pb}"
        got: list = []
        delay = 0.6
        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a], delay_sec=delay)
        n = 3
        try:
            a.start()
            b.start()
            b.subscribe("security", lambda e: got.append(e))
            for _ in range(n):
                a.publish(_sec())
            t0 = time.monotonic()

            # The frames arrive and are counted immediately (delivered tally),
            # but the subscriber has NOT seen them yet — dispatch is deferred.
            assert _wait_until(
                lambda: b.mesh_counters()["delivered"]["total"]["msgs"] == n
            )
            assert got == []

            # After the delay they all arrive.
            assert _wait_until(lambda: len(got) == n, timeout_sec=2.5)
            elapsed = time.monotonic() - t0
            assert elapsed >= 0.3  # actually deferred, not instant
            # Nothing was dropped (no loss configured).
            assert b.mesh_counters()["dropped"]["total"]["msgs"] == 0
        finally:
            a.stop()
            b.stop()

    def test_delay_preserves_fifo_order(self):
        pa, pb = _free_ports(2)
        ep_a, ep_b = f"tcp://127.0.0.1:{pa}", f"tcp://127.0.0.1:{pb}"
        got: list = []
        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a], delay_sec=0.4)
        sent = [_sec(detector=f"d{i}") for i in range(5)]
        try:
            a.start()
            b.start()
            b.subscribe("security", lambda e: got.append(e))
            for ev in sent:
                a.publish(ev)
            assert _wait_until(lambda: len(got) == len(sent), timeout_sec=2.5)
            assert [e.event_id for e in got] == [e.event_id for e in sent]
        finally:
            a.stop()
            b.stop()

    def test_delay_composes_with_loss(self):
        """An erased frame is never queued nor dispatched, even with a delay."""
        pa, pb = _free_ports(2)
        ep_a, ep_b = f"tcp://127.0.0.1:{pa}", f"tcp://127.0.0.1:{pb}"
        got: list = []
        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(
            self_endpoint=ep_b,
            peer_endpoints=[ep_a],
            loss_prob=1.0,
            delay_sec=0.3,
        )
        n = 5
        try:
            a.start()
            b.start()
            b.subscribe("security", lambda e: got.append(e))
            for _ in range(n):
                a.publish(_sec())
            assert _wait_until(
                lambda: b.mesh_counters()["dropped"]["total"]["msgs"] == n
            )
            time.sleep(0.5)  # well past the delay
            assert got == []
            assert b.mesh_counters()["delivered"]["total"]["msgs"] == 0
        finally:
            a.stop()
            b.stop()

    def test_negative_delay_rejected(self):
        with pytest.raises(ValueError, match="delay_sec"):
            ZmqMesh(
                self_endpoint="tcp://127.0.0.1:5599",
                peer_endpoints=[],
                delay_sec=-0.1,
            )
