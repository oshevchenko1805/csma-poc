"""Tests for mesh cost counters (instrumentation item 3).

Two properties are under test:

  1. Accuracy — publish counts every frame this peer offers; the receiver
     counts every well-formed frame that arrives on its SUB socket. Both
     are per-topic with a derived total, in application-payload bytes
     (len(topic) + len(payload)).

  2. Non-perturbation ("identity") — turning on the counters must not
     change the delivery path or its semantics. The existing test_mesh.py
     suite is the before-state (delivery, topic filtering, buggy-callback
     survival all still pass unchanged). Here we add the specific
     invariants the counters could plausibly break:
       - delivery is counted per FRAME, not per callback (two subscribers
         on one topic => delivered.msgs == 1);
       - a frame with no subscriber is still delivered/counted;
       - stop() does not reset the tallies;
       - NoOpMesh (A/B baseline) and the ABC default report all zeros.
"""

from __future__ import annotations

import random
import socket
import time

import pytest

from core.events import IsolationAnnounce, SecurityEvent
from core.mesh import NoOpMesh, ZmqMesh, topic_for


# ----------------------------------------------------------------------------
# helpers (mirrors tests/test_mesh.py)
# ----------------------------------------------------------------------------


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


def _wait_until(predicate, timeout_sec: float = 2.0, poll_sec: float = 0.05) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(poll_sec)
    return predicate()


def _frame_bytes(event) -> int:
    """Expected wire size the counter should attribute to this event."""
    topic = topic_for(event)
    return len(topic.encode("utf-8")) + len(event.to_json().encode("utf-8"))


# ----------------------------------------------------------------------------
# Zero baselines: NoOpMesh and the ABC default
# ----------------------------------------------------------------------------


class TestZeroBaselines:
    def test_noop_mesh_counters_are_zero_even_after_publish(self):
        with NoOpMesh() as bus:
            bus.subscribe("security", lambda e: None)
            for _ in range(5):
                bus.publish(
                    SecurityEvent(source="m", detector="gps", target_uav="uav_0")
                )
            counters = bus.mesh_counters()

        zero_bucket = {"per_topic": {}, "total": {"msgs": 0, "bytes": 0}}
        assert counters["endpoint"] is None
        assert counters["published"] == zero_bucket
        assert counters["delivered"] == zero_bucket
        assert counters["dropped"] == zero_bucket

    def test_snapshot_shape_is_stable(self):
        """Every bus returns the same top-level shape, so the metrics layer
        can fold A/B and C uniformly."""
        counters = NoOpMesh().mesh_counters()
        assert set(counters) == {"endpoint", "published", "delivered", "dropped"}
        for bucket in ("published", "delivered", "dropped"):
            assert set(counters[bucket]) == {"per_topic", "total"}
            assert set(counters[bucket]["total"]) == {"msgs", "bytes"}


# ----------------------------------------------------------------------------
# Publish-side accuracy
# ----------------------------------------------------------------------------


class TestPublishCounts:
    def test_publish_counts_per_topic_and_total(self):
        port = _free_ports(1)[0]
        bus = ZmqMesh(self_endpoint=f"tcp://127.0.0.1:{port}", peer_endpoints=[])

        sec1 = SecurityEvent(source="a", detector="gps", target_uav="uav_2")
        sec2 = SecurityEvent(source="a", detector="heartbeat", target_uav="uav_1")
        iso1 = IsolationAnnounce(
            source="a", target_uav="uav_2", reason="x", decided_by="a"
        )

        try:
            bus.start()
            bus.publish(sec1)
            bus.publish(sec2)
            bus.publish(iso1)
            counters = bus.mesh_counters()
        finally:
            bus.stop()

        pub = counters["published"]
        assert pub["per_topic"]["security"]["msgs"] == 2
        assert pub["per_topic"]["security"]["bytes"] == _frame_bytes(sec1) + _frame_bytes(sec2)
        assert pub["per_topic"]["isolation"]["msgs"] == 1
        assert pub["per_topic"]["isolation"]["bytes"] == _frame_bytes(iso1)

        assert pub["total"]["msgs"] == 3
        assert pub["total"]["bytes"] == (
            _frame_bytes(sec1) + _frame_bytes(sec2) + _frame_bytes(iso1)
        )

        # Nothing was received on this lone peer.
        assert counters["delivered"]["total"] == {"msgs": 0, "bytes": 0}
        assert counters["endpoint"] == f"tcp://127.0.0.1:{port}"

    def test_failed_publish_is_not_counted(self):
        """publish() of a non-propagating event raises before send_multipart,
        so nothing is tallied."""
        from core.events import TelemetryEvent

        port = _free_ports(1)[0]
        bus = ZmqMesh(self_endpoint=f"tcp://127.0.0.1:{port}", peer_endpoints=[])
        try:
            bus.start()
            try:
                bus.publish(
                    TelemetryEvent(source="m", uav_id="uav_0", msg_type="HEARTBEAT")
                )
            except ValueError:
                pass
            counters = bus.mesh_counters()
        finally:
            bus.stop()

        assert counters["published"]["total"] == {"msgs": 0, "bytes": 0}


# ----------------------------------------------------------------------------
# Delivery-side accuracy + non-perturbation
# ----------------------------------------------------------------------------


class TestDeliveryCounts:
    def test_delivery_counts_match_received_frame(self):
        port_a, port_b = _free_ports(2)
        ep_a, ep_b = f"tcp://127.0.0.1:{port_a}", f"tcp://127.0.0.1:{port_b}"

        got: list = []
        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a])
        ev = SecurityEvent(source="a", detector="gps", target_uav="uav_2")

        try:
            a.start()
            b.start()
            b.subscribe("security", lambda e: got.append(e))
            a.publish(ev)

            # Delivery still works exactly as before (identity of behaviour).
            assert _wait_until(lambda: len(got) == 1)
            assert got[0].event_id == ev.event_id

            deliv = b.mesh_counters()["delivered"]
            assert deliv["per_topic"]["security"]["msgs"] == 1
            assert deliv["per_topic"]["security"]["bytes"] == _frame_bytes(ev)
            assert deliv["total"] == {"msgs": 1, "bytes": _frame_bytes(ev)}

            # Publisher's own delivered tally stays empty (it doesn't receive
            # its own PUB), and its published tally holds the one frame.
            assert a.mesh_counters()["delivered"]["total"]["msgs"] == 0
            assert a.mesh_counters()["published"]["total"]["msgs"] == 1
        finally:
            a.stop()
            b.stop()

    def test_delivery_counted_per_frame_not_per_callback(self):
        """Two subscribers on one topic => the frame is still counted ONCE.
        Delivery cost is a network property, not app-internal fan-out."""
        port_a, port_b = _free_ports(2)
        ep_a, ep_b = f"tcp://127.0.0.1:{port_a}", f"tcp://127.0.0.1:{port_b}"

        cb1, cb2 = [], []
        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a])

        try:
            a.start()
            b.start()
            b.subscribe("security", lambda e: cb1.append(e))
            b.subscribe("security", lambda e: cb2.append(e))
            a.publish(SecurityEvent(source="a", detector="gps", target_uav="uav_2"))

            assert _wait_until(lambda: len(cb1) == 1 and len(cb2) == 1)
            assert b.mesh_counters()["delivered"]["per_topic"]["security"]["msgs"] == 1
        finally:
            a.stop()
            b.stop()

    def test_frame_with_no_subscriber_is_still_delivered_and_counted(self):
        """A frame that arrives on SUB is counted even if nobody subscribed
        to its topic — it crossed the wire regardless."""
        port_a, port_b = _free_ports(2)
        ep_a, ep_b = f"tcp://127.0.0.1:{port_a}", f"tcp://127.0.0.1:{port_b}"

        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a])

        try:
            a.start()
            b.start()
            # b subscribes to nothing.
            a.publish(SecurityEvent(source="a", detector="gps", target_uav="uav_2"))

            assert _wait_until(
                lambda: b.mesh_counters()["delivered"]["total"]["msgs"] == 1
            )
        finally:
            a.stop()
            b.stop()

    def test_stop_does_not_reset_counters(self):
        port_a, port_b = _free_ports(2)
        ep_a, ep_b = f"tcp://127.0.0.1:{port_a}", f"tcp://127.0.0.1:{port_b}"

        got: list = []
        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a])

        try:
            a.start()
            b.start()
            b.subscribe("security", lambda e: got.append(e))
            a.publish(SecurityEvent(source="a", detector="gps", target_uav="uav_2"))
            assert _wait_until(lambda: len(got) == 1)
        finally:
            a.stop()
            b.stop()

        # After stop(), the snapshot is still readable and non-zero.
        assert a.mesh_counters()["published"]["total"]["msgs"] == 1
        assert b.mesh_counters()["delivered"]["total"]["msgs"] == 1


# ----------------------------------------------------------------------------
# Channel loss (instrumentation item 4) — receive-side Bernoulli erasure
# ----------------------------------------------------------------------------


class TestChannelLoss:
    def test_default_loss_is_zero_and_delivers_all(self):
        """loss_prob defaults to 0.0: every frame delivered, nothing dropped.
        This is the identity guarantee — the baseline behaviour is unchanged
        (the RNG is never even sampled)."""
        port_a, port_b = _free_ports(2)
        ep_a, ep_b = f"tcp://127.0.0.1:{port_a}", f"tcp://127.0.0.1:{port_b}"

        got: list = []
        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a])
        n = 20

        try:
            a.start()
            b.start()
            b.subscribe("security", lambda e: got.append(e))
            for _ in range(n):
                a.publish(
                    SecurityEvent(source="a", detector="gps", target_uav="uav_2")
                )
            assert _wait_until(lambda: len(got) == n)
            deliv = b.mesh_counters()["delivered"]["total"]
            assert deliv["msgs"] == n
            assert b.mesh_counters()["dropped"]["total"] == {"msgs": 0, "bytes": 0}
        finally:
            a.stop()
            b.stop()

    def test_full_loss_drops_every_frame(self):
        """loss_prob=1.0: every received frame is erased. Nothing is
        dispatched; each arrival is counted as dropped, not delivered."""
        port_a, port_b = _free_ports(2)
        ep_a, ep_b = f"tcp://127.0.0.1:{port_a}", f"tcp://127.0.0.1:{port_b}"

        got: list = []
        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(self_endpoint=ep_b, peer_endpoints=[ep_a], loss_prob=1.0)
        n = 15

        try:
            a.start()
            b.start()
            b.subscribe("security", lambda e: got.append(e))
            for _ in range(n):
                a.publish(
                    SecurityEvent(source="a", detector="gps", target_uav="uav_2")
                )
            assert _wait_until(
                lambda: b.mesh_counters()["dropped"]["total"]["msgs"] == n
            )
            assert b.mesh_counters()["delivered"]["total"] == {"msgs": 0, "bytes": 0}
            # Nothing was ever dispatched to the subscriber.
            time.sleep(0.1)
            assert got == []
            # Publisher's own offered-load count is unaffected by the peer's loss.
            assert a.mesh_counters()["published"]["total"]["msgs"] == n
        finally:
            a.stop()
            b.stop()

    def test_partial_loss_is_seed_deterministic(self):
        """loss_prob=0.5 with a fixed seed and a single publisher (one TCP
        connection preserves send order) => the drop decisions are exactly
        those of random.Random(seed) over the arrival sequence."""
        port_a, port_b = _free_ports(2)
        ep_a, ep_b = f"tcp://127.0.0.1:{port_a}", f"tcp://127.0.0.1:{port_b}"

        seed, n, p = 12345, 40, 0.5
        got: list = []
        a = ZmqMesh(self_endpoint=ep_a, peer_endpoints=[ep_b])
        b = ZmqMesh(
            self_endpoint=ep_b, peer_endpoints=[ep_a], loss_prob=p, rng_seed=seed
        )

        try:
            a.start()
            b.start()
            b.subscribe("security", lambda e: got.append(e))
            for _ in range(n):
                a.publish(
                    SecurityEvent(source="a", detector="gps", target_uav="uav_2")
                )
            # All n frames must arrive (dropped + delivered) before we compare.
            assert _wait_until(
                lambda: (
                    b.mesh_counters()["dropped"]["total"]["msgs"]
                    + b.mesh_counters()["delivered"]["total"]["msgs"]
                )
                == n
            )
            # Expected drops = the same RNG's decision stream over n frames.
            rng = random.Random(seed)
            expected_drops = sum(rng.random() < p for _ in range(n))

            counters = b.mesh_counters()
            assert counters["dropped"]["total"]["msgs"] == expected_drops
            assert counters["delivered"]["total"]["msgs"] == n - expected_drops
            assert len(got) == n - expected_drops
            # A genuine partial: neither all nor nothing (guards the seed choice).
            assert 0 < expected_drops < n
        finally:
            a.stop()
            b.stop()

    def test_invalid_loss_prob_rejected(self):
        for bad in (-0.1, 1.5):
            with pytest.raises(ValueError, match="loss_prob"):
                ZmqMesh(
                    self_endpoint="tcp://127.0.0.1:5599",
                    peer_endpoints=[],
                    loss_prob=bad,
                )
