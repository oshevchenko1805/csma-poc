"""Tests for core.mesh: NoOpMesh + ZmqMesh real pub/sub."""

from __future__ import annotations

import socket
import time

import pytest

from core.events import (
    IsolationAnnounce,
    RecoveryAck,
    RecoveryRequest,
    SecurityEvent,
    TelemetryEvent,
)
from core.mesh import MeshBus, NoOpMesh, ZmqMesh, topic_for


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------


def _free_ports(n: int) -> list[int]:
    """Pick n free TCP ports on localhost."""
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


def _wait_until(predicate, timeout_sec: float = 2.0, poll_sec: float = 0.05) -> bool:
    """Poll predicate until True or timeout. Returns whether it became True."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(poll_sec)
    return predicate()


# ----------------------------------------------------------------------------
# Topic mapping
# ----------------------------------------------------------------------------


class TestTopicMapping:
    def test_security_topic(self):
        ev = SecurityEvent(source="m", detector="gps", target_uav="uav_2")
        assert topic_for(ev) == "security"

    def test_isolation_topic(self):
        ev = IsolationAnnounce(
            source="m", target_uav="uav_2", reason="x", decided_by="m"
        )
        assert topic_for(ev) == "isolation"

    def test_recovery_request_topic(self):
        ev = RecoveryRequest(
            source="c", target_uav="uav_2", action="restart_process", requester="c"
        )
        assert topic_for(ev) == "recovery_req"

    def test_recovery_ack_topic(self):
        ev = RecoveryAck(
            source="e", target_uav="uav_2", action="restart_process",
            success=True, executor="e",
        )
        assert topic_for(ev) == "recovery_ack"

    def test_peer_position_topic(self):
        from core.events import PeerPositionAnnounce
        ev = PeerPositionAnnounce(
            source="monitor_uav_0",
            uav_id="uav_0",
            lat=47.4,
            lon=8.5,
            alt=500.0,
            sample_timestamp=1700000000.0,
        )
        assert topic_for(ev) == "peer_position"

    def test_telemetry_does_not_propagate(self):
        ev = TelemetryEvent(source="m", uav_id="uav_0", msg_type="HEARTBEAT")
        with pytest.raises(ValueError, match="not designed to propagate"):
            topic_for(ev)


# ----------------------------------------------------------------------------
# NoOpMesh
# ----------------------------------------------------------------------------


class TestNoOpMesh:
    def test_lifecycle_no_errors(self):
        bus = NoOpMesh()
        bus.start()
        bus.stop()

    def test_context_manager(self):
        with NoOpMesh() as bus:
            assert isinstance(bus, MeshBus)

    def test_publish_does_not_raise(self):
        with NoOpMesh() as bus:
            bus.publish(SecurityEvent(source="m", detector="gps", target_uav="uav_0"))

    def test_subscribe_never_fires(self):
        received: list = []
        with NoOpMesh() as bus:
            bus.subscribe("security", lambda e: received.append(e))
            bus.publish(SecurityEvent(source="m", detector="gps", target_uav="uav_0"))
            time.sleep(0.1)
        assert received == []


# ----------------------------------------------------------------------------
# ZmqMesh — real pub/sub between peers in the same process
# ----------------------------------------------------------------------------


class TestZmqMesh:
    def test_two_peers_exchange_security_event(self):
        port_a, port_b = _free_ports(2)
        ep_a = f"tcp://127.0.0.1:{port_a}"
        ep_b = f"tcp://127.0.0.1:{port_b}"

        received_by_b: list = []

        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a])

        try:
            a.start()
            b.start()
            b.subscribe("security", lambda e: received_by_b.append(e))

            ev = SecurityEvent(
                source="monitor_a",
                detector="gps",
                target_uav="uav_2",
                evidence={"residual": 1.5},
            )
            a.publish(ev)

            assert _wait_until(lambda: len(received_by_b) == 1)
            got = received_by_b[0]
            assert got.event_id == ev.event_id
            assert got.detector == "gps"
            assert got.target_uav == "uav_2"
            assert got.evidence == {"residual": 1.5}
            # type is preserved through the round-trip
            assert isinstance(got, SecurityEvent)
        finally:
            a.stop()
            b.stop()

    def test_topic_filter_isolates_subscribers(self):
        """Subscriber for one topic must not see events from another topic."""
        port_a, port_b = _free_ports(2)
        ep_a = f"tcp://127.0.0.1:{port_a}"
        ep_b = f"tcp://127.0.0.1:{port_b}"

        sec_received: list = []
        iso_received: list = []

        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a])

        try:
            a.start()
            b.start()
            b.subscribe("security", lambda e: sec_received.append(e))
            b.subscribe("isolation", lambda e: iso_received.append(e))

            a.publish(SecurityEvent(source="a", detector="gps", target_uav="uav_2"))
            a.publish(
                IsolationAnnounce(
                    source="a", target_uav="uav_2", reason="x", decided_by="a"
                )
            )

            assert _wait_until(
                lambda: len(sec_received) == 1 and len(iso_received) == 1
            )
            assert isinstance(sec_received[0], SecurityEvent)
            assert isinstance(iso_received[0], IsolationAnnounce)
        finally:
            a.stop()
            b.stop()

    def test_three_peers_full_mesh(self):
        """Realistic 3-UAV mesh: A publishes, both B and C receive."""
        port_a, port_b, port_c = _free_ports(3)
        ep_a = f"tcp://127.0.0.1:{port_a}"
        ep_b = f"tcp://127.0.0.1:{port_b}"
        ep_c = f"tcp://127.0.0.1:{port_c}"

        rb: list = []
        rc: list = []

        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b, ep_c])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a, ep_c])
        c = ZmqMesh(self_endpoint=ep_c, peer_endpoints=[ep_a, ep_b])

        try:
            for bus in (a, b, c):
                bus.start()
            b.subscribe("security", lambda e: rb.append(e))
            c.subscribe("security", lambda e: rc.append(e))

            a.publish(
                SecurityEvent(
                    source="monitor_a", detector="gps", target_uav="uav_2"
                )
            )

            assert _wait_until(lambda: len(rb) == 1 and len(rc) == 1)
        finally:
            for bus in (a, b, c):
                bus.stop()

    def test_multiple_callbacks_same_topic(self):
        port_a, port_b = _free_ports(2)
        ep_a = f"tcp://127.0.0.1:{port_a}"
        ep_b = f"tcp://127.0.0.1:{port_b}"

        cb1_seen: list = []
        cb2_seen: list = []

        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a])

        try:
            a.start()
            b.start()
            b.subscribe("security", lambda e: cb1_seen.append(e))
            b.subscribe("security", lambda e: cb2_seen.append(e))

            a.publish(
                SecurityEvent(source="a", detector="gps", target_uav="uav_2")
            )

            assert _wait_until(
                lambda: len(cb1_seen) == 1 and len(cb2_seen) == 1
            )
        finally:
            a.stop()
            b.stop()

    def test_buggy_callback_does_not_kill_receiver(self):
        """If one callback raises, the next event still gets through."""
        port_a, port_b = _free_ports(2)
        ep_a = f"tcp://127.0.0.1:{port_a}"
        ep_b = f"tcp://127.0.0.1:{port_b}"

        ok_received: list = []

        def bad_callback(_):
            raise RuntimeError("subscriber bug")

        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a])

        try:
            a.start()
            b.start()
            b.subscribe("security", bad_callback)
            b.subscribe("security", lambda e: ok_received.append(e))

            a.publish(SecurityEvent(source="a", detector="gps", target_uav="uav_2"))
            a.publish(SecurityEvent(source="a", detector="heartbeat", target_uav="uav_1"))

            assert _wait_until(lambda: len(ok_received) == 2)
        finally:
            a.stop()
            b.stop()

    def test_publish_before_start_raises(self):
        bus = ZmqMesh(
            self_endpoint="tcp://127.0.0.1:5599",
            peer_endpoints=[],
        )
        with pytest.raises(RuntimeError, match="before start"):
            bus.publish(SecurityEvent(source="x", detector="gps", target_uav="uav_0"))

    def test_telemetry_publish_rejected(self):
        """TelemetryEvent must not be publishable on the mesh."""
        port_a = _free_ports(1)[0]
        bus = ZmqMesh(
            self_endpoint=f"tcp://127.0.0.1:{port_a}",
            peer_endpoints=[],
        )
        try:
            bus.start()
            with pytest.raises(ValueError, match="not designed to propagate"):
                bus.publish(
                    TelemetryEvent(source="m", uav_id="uav_0", msg_type="HEARTBEAT")
                )
        finally:
            bus.stop()
