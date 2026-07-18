"""
Mesh-bus abstraction for security event propagation between UAV peers.

Two implementations:
  - NoOpMesh: drops publishes, never fires callbacks. Used in Architectures
    A and B, where peers do not exchange security context. This makes the
    architecture difference a deployment fact (a config flag swaps the
    implementation) rather than an `if architecture` in domain code.
  - ZmqMesh: ZeroMQ PUB/SUB over TCP loopback. Each peer binds one PUB
    socket for outbound publishes and connects one SUB socket to every
    other peer's PUB endpoint. This is brokerless and peer-to-peer, which
    matches the distributed mesh semantics in the dissertation.

PoC caveat (Chapter 4): ZeroMQ over TCP is not a FANET radio mesh. It
approximates the propagation semantics (peer-to-peer, no central broker)
but not the physical channel. Communication-disruption attacks are
modelled at the network layer (iptables / socket close), not at RF.

Cost instrumentation (instrumentation item 3)
---------------------------------------------
Every MeshBus exposes `mesh_counters()`: a snapshot of how many messages
and application-payload bytes crossed the bus, split into `published`
(offered load at this peer) and `delivered` (frames that arrived on this
peer's SUB socket), each broken down per topic plus a derived total.

The counters are pure observation: incrementing them changes neither the
delivery path nor its timing. NoOpMesh (and the ABC default) report zeros,
so Architectures A and B carry zero mesh cost by construction — which is
the whole point of the trade-off ("C detects, at a cost of X messages that
A and B never pay").

"Bytes" here are the application frame we form ourselves
(`len(topic) + len(payload)`), NOT TCP/IP/Ethernet overhead — that cannot
be measured cleanly at this layer and is out of scope. Report it as a
lower bound on on-wire cost.

Channel degradation (instrumentation item 4)
--------------------------------------------
ZmqMesh can drop delivered frames to emulate a lossy FANET channel. The
loss is an independent Bernoulli erasure applied per received frame at
each receiver (so one publish may reach one peer and not another) — an
erasure-channel approximation, NOT a full RF model (no reordering or
corruption). TCP itself never loses frames; the drop is synthetic.

This is distinct from the comm_disruption ATTACK, which is adversarial and
modelled at the network layer (iptables / socket close). Item 4 models the
ambient, non-adversarial channel quality the mesh runs over; the attack
sits on top of it. Dropped frames are tallied separately (`dropped`), so
realized loss = dropped / (delivered + dropped) is measurable from
run_summary. Default loss_prob 0.0 is a strict no-op.

ZmqMesh can also add a constant per-frame delivery delay (`delay_sec`) to
emulate channel latency. It is applied AFTER the arrival tally (the frame
crossed the wire on time; only its dispatch to subscribers is deferred),
by queueing the frame in the receiver thread and dispatching it once due —
so the poll loop never blocks and throughput is preserved. Default 0.0 is
a strict no-op (inline dispatch, no queue). NOTE (thesis Ch.5): mesh
latency of tens-to-hundreds of ms sits well below this PoC's dominant
latencies — the ~1 Hz ESTIMATOR_STATUS detector floor and the seconds-long
PX4 restart — so delay is expected to be a low-impact axis; a flat sweep
is itself the honest finding that the mesh is not the bottleneck.
"""

from __future__ import annotations

import json
import random
import threading
import time
from collections import deque
from abc import ABC, abstractmethod
from typing import Callable, Optional

from core.events import BaseEvent, event_from_json


# ----------------------------------------------------------------------------
# Topic derivation
# ----------------------------------------------------------------------------
#
# Only events that are meant to propagate between peers map to a topic.
# TelemetryEvent and MissionEvent are deliberately *not* in this map — they
# stay local to the producing process. This is enforced at publish time.

_TOPIC_BY_EVENT_TYPE: dict[str, str] = {
    "security": "security",
    "isolation_announce": "isolation",
    "recovery_request": "recovery_req",
    "recovery_ack": "recovery_ack",
    "peer_position": "peer_position",
}


def topic_for(event: BaseEvent) -> str:
    """Map an event to its mesh topic, or raise for events that don't propagate."""
    et = event.event_type
    if et not in _TOPIC_BY_EVENT_TYPE:
        raise ValueError(
            f"Event type {et!r} is not designed to propagate over mesh"
        )
    return _TOPIC_BY_EVENT_TYPE[et]


EventCallback = Callable[[BaseEvent], None]


# ----------------------------------------------------------------------------
# Cost-counter helpers (instrumentation item 3)
# ----------------------------------------------------------------------------
#
# Snapshot shape (both `published` and `delivered` follow it):
#
#     {
#       "per_topic": {"security": {"msgs": N, "bytes": B}, ...},
#       "total":     {"msgs": N_sum, "bytes": B_sum},
#     }
#
# and the full counter is:
#
#     {"endpoint": <str|None>,
#      "published": <bucket>, "delivered": <bucket>, "dropped": <bucket>}
#
# `dropped` counts frames erased by the item-4 loss model (zero unless
# loss is enabled), kept separate from `delivered` so the two never mix.


def _empty_bucket() -> dict:
    return {"per_topic": {}, "total": {"msgs": 0, "bytes": 0}}


def zero_mesh_counters(endpoint: Optional[str] = None) -> dict:
    """A counter snapshot with everything at zero (A/B baseline)."""
    return {
        "endpoint": endpoint,
        "published": _empty_bucket(),
        "delivered": _empty_bucket(),
        "dropped": _empty_bucket(),
    }


def _bucket_from_raw(raw: dict[str, dict[str, int]]) -> dict:
    """Turn a {topic: {msgs, bytes}} tally into a bucket with a derived total."""
    per_topic = {t: dict(v) for t, v in raw.items()}
    total_msgs = sum(v["msgs"] for v in per_topic.values())
    total_bytes = sum(v["bytes"] for v in per_topic.values())
    return {
        "per_topic": per_topic,
        "total": {"msgs": total_msgs, "bytes": total_bytes},
    }


# ----------------------------------------------------------------------------
# Interface
# ----------------------------------------------------------------------------


class MeshBus(ABC):
    """
    Common interface for a mesh transport.

    Lifecycle: __init__ -> start() -> publish/subscribe ... -> stop().
    Also usable as a context manager.
    """

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def publish(self, event: BaseEvent) -> None: ...

    @abstractmethod
    def subscribe(self, topic: str, callback: EventCallback) -> None: ...

    def mesh_counters(self) -> dict:
        """Cost snapshot. Default is all-zeros; ZmqMesh overrides.

        A concrete default (rather than an abstractmethod) so NoOpMesh — and
        any future transport that carries no measurable cost — reports zeros
        without boilerplate, letting the metrics layer fold every bus in a
        fleet uniformly.
        """
        return zero_mesh_counters(endpoint=None)

    def __enter__(self) -> "MeshBus":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()


# ----------------------------------------------------------------------------
# No-op
# ----------------------------------------------------------------------------


class NoOpMesh(MeshBus):
    """
    Stub used in Architectures A and B (mesh disabled by config).

    publish() drops silently; subscribe() registers a callback that will
    never be invoked. The interface is identical to ZmqMesh so domain code
    is architecture-agnostic. Inherits the all-zeros mesh_counters() from
    MeshBus: no traffic crosses it, so its cost is zero by construction.
    """

    def __init__(self) -> None:
        self._started: bool = False

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def publish(self, event: BaseEvent) -> None:
        return  # mesh disabled — no propagation

    def subscribe(self, topic: str, callback: EventCallback) -> None:
        return  # no deliveries will ever happen


# ----------------------------------------------------------------------------
# ZeroMQ
# ----------------------------------------------------------------------------


class ZmqMesh(MeshBus):
    """
    Brokerless ZeroMQ PUB/SUB transport.

    Parameters
    ----------
    self_endpoint           The bind address for this peer's PUB socket,
                            e.g. 'tcp://127.0.0.1:5550'.
    peer_endpoints          PUB endpoints of all other peers; this peer's
                            SUB socket connects to each of them.
    slow_joiner_delay_sec   ZMQ PUB/SUB has a known slow-joiner problem:
                            messages published before SUB has finished
                            attaching are silently dropped. Sleep this long
                            after start() before publishing.
    loss_prob               Probability [0.0, 1.0] of erasing each received
                            frame (item 4). 0.0 (default) is a strict
                            no-op: the RNG is never sampled and delivery is
                            unchanged. Erased frames are tallied in
                            `dropped`, not `delivered`.
    rng_seed                Seed for the loss RNG. Makes UNIT TESTS
                            deterministic; it does NOT make live runs
                            bit-identical (TCP arrival timing is not
                            deterministic). Reproducibility of a treatment
                            comes from N repetitions at a fixed loss_prob.
    delay_sec               Constant per-frame delivery delay (item 4b).
                            0.0 (default) is a strict no-op: frames are
                            dispatched inline, no queue is used. >0 queues
                            each frame and dispatches it once due, on the
                            receiver thread, without blocking the poll loop.

    Threading model:
        A daemon thread runs a poll loop on the SUB socket. Incoming
        messages are dispatched to subscribers by topic. Callbacks run on
        the receiver thread, so they must be thread-safe with respect to
        any state they touch.

        A buggy callback that raises an exception is logged-and-swallowed
        — one bad subscriber must not bring down the entire bus.

    Cost counters:
        `publish()` tallies each frame it puts on the wire (per topic);
        the receiver thread tallies each well-formed frame that arrives on
        the SUB socket. Both are guarded by `_counter_lock` because publish
        runs on domain threads and delivery on the receiver thread. The
        tallies are never reset by stop(), so `mesh_counters()` is readable
        after the run for folding into run_summary.
    """

    def __init__(
        self,
        self_endpoint: str,
        peer_endpoints: list[str],
        slow_joiner_delay_sec: float = 0.3,
        loss_prob: float = 0.0,
        rng_seed: Optional[int] = None,
        delay_sec: float = 0.0,
    ) -> None:
        self.self_endpoint = self_endpoint
        self.peer_endpoints = list(peer_endpoints)
        self.slow_joiner_delay_sec = slow_joiner_delay_sec

        self._loss_prob = float(loss_prob)
        if not 0.0 <= self._loss_prob <= 1.0:
            raise ValueError("loss_prob must be in [0.0, 1.0]")
        # Dedicated RNG, touched ONLY by the receiver thread (one thread),
        # so it needs no lock. See class docstring on what the seed does
        # and does not guarantee.
        self._rng = random.Random(rng_seed)

        self._delay_sec = float(delay_sec)
        if self._delay_sec < 0.0:
            raise ValueError("delay_sec must be >= 0.0")
        # Queue of (due_monotonic, topic, event) for delayed dispatch.
        # Touched ONLY by the receiver thread, so no lock. Never used while
        # delay_sec == 0.0 (frames dispatch inline).
        self._delay_queue: "deque" = deque()

        # Late import so NoOpMesh users on minimal envs don't need pyzmq.
        import zmq

        self._zmq = zmq

        self._ctx: Optional["zmq.Context"] = None
        self._pub: Optional["zmq.Socket"] = None
        self._sub: Optional["zmq.Socket"] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._callbacks: dict[str, list[EventCallback]] = {}
        self._cb_lock = threading.Lock()
        self._started: bool = False

        # Cost counters. {topic: {"msgs": int, "bytes": int}}. Guarded by
        # _counter_lock; publish runs on domain threads, delivery on the
        # receiver thread.
        self._counter_lock = threading.Lock()
        self._pub_tally: dict[str, dict[str, int]] = {}
        self._delivered_tally: dict[str, dict[str, int]] = {}
        self._dropped_tally: dict[str, dict[str, int]] = {}

    # ----- lifecycle -----

    def start(self) -> None:
        if self._started:
            return

        self._ctx = self._zmq.Context.instance()

        self._pub = self._ctx.socket(self._zmq.PUB)
        self._pub.bind(self.self_endpoint)

        self._sub = self._ctx.socket(self._zmq.SUB)
        for ep in self.peer_endpoints:
            self._sub.connect(ep)
        # Receive everything; topic dispatch happens in callbacks.
        self._sub.setsockopt(self._zmq.SUBSCRIBE, b"")

        # PUB/SUB needs a brief settle window after bind/connect.
        time.sleep(self.slow_joiner_delay_sec)

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._receive_loop,
            name=f"zmq-mesh-recv-{self.self_endpoint}",
            daemon=True,
        )
        self._thread.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._sub is not None:
            self._sub.close(linger=0)
            self._sub = None
        if self._pub is not None:
            self._pub.close(linger=0)
            self._pub = None
        # We deliberately don't terminate the shared zmq.Context.instance(),
        # because other ZmqMesh instances in the same process may still use it.
        # Counters are deliberately NOT reset here: mesh_counters() must stay
        # readable after the run for folding into run_summary.
        self._started = False

    # ----- pub/sub API -----

    def publish(self, event: BaseEvent) -> None:
        if not self._started or self._pub is None:
            raise RuntimeError("ZmqMesh.publish called before start()")
        topic = topic_for(event)
        topic_b = topic.encode("utf-8")
        payload = event.to_json().encode("utf-8")
        self._pub.send_multipart([topic_b, payload])
        # Count only after a successful send: if topic_for had raised, nothing
        # went on the wire, so nothing is counted.
        self._tally(self._pub_tally, topic, len(topic_b) + len(payload))

    def subscribe(self, topic: str, callback: EventCallback) -> None:
        with self._cb_lock:
            self._callbacks.setdefault(topic, []).append(callback)

    # ----- cost counters -----

    def _tally(
        self, tally: dict[str, dict[str, int]], topic: str, nbytes: int
    ) -> None:
        with self._counter_lock:
            slot = tally.setdefault(topic, {"msgs": 0, "bytes": 0})
            slot["msgs"] += 1
            slot["bytes"] += nbytes

    def mesh_counters(self) -> dict:
        with self._counter_lock:
            pub_raw = {t: dict(v) for t, v in self._pub_tally.items()}
            deliv_raw = {t: dict(v) for t, v in self._delivered_tally.items()}
            drop_raw = {t: dict(v) for t, v in self._dropped_tally.items()}
        return {
            "endpoint": self.self_endpoint,
            "published": _bucket_from_raw(pub_raw),
            "delivered": _bucket_from_raw(deliv_raw),
            "dropped": _bucket_from_raw(drop_raw),
        }

    # ----- receiver thread -----

    def _receive_loop(self) -> None:
        assert self._sub is not None
        poller = self._zmq.Poller()
        poller.register(self._sub, self._zmq.POLLIN)

        # Finer poll cadence when a delay is active so queued frames mature on
        # time; the default (delayless) path keeps the original 200 ms cadence
        # and thus the exact same idle behaviour as before.
        poll_timeout_ms = 20 if self._delay_sec > 0.0 else 200

        while not self._stop_event.is_set():
            try:
                socks = dict(poller.poll(timeout=poll_timeout_ms))  # ms
            except self._zmq.ZMQError:
                # Context terminating during shutdown.
                break

            if self._sub in socks:
                try:
                    parts = self._sub.recv_multipart(flags=self._zmq.NOBLOCK)
                except self._zmq.Again:
                    parts = None
                except self._zmq.ZMQError:
                    break
                if parts is not None:
                    self._handle_frame(parts)

            # Drain matured delayed frames every iteration — even when no new
            # frame arrived this cycle, or a queued one would wait for the
            # next arrival. No-op (and no queue) while delay_sec == 0.0.
            if self._delay_sec > 0.0:
                self._drain_due()

        # Frames still queued at stop() are discarded: the run is over.

    def _handle_frame(self, parts: list) -> None:
        """Decode one received frame, apply loss, count it, and either
        dispatch it now or queue it for delayed dispatch."""
        if len(parts) != 2:
            return  # malformed frame

        topic_b, payload_b = parts
        try:
            topic = topic_b.decode("utf-8")
            event = event_from_json(payload_b.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            # Don't crash a peer because someone sent garbage.
            return

        nbytes = len(topic_b) + len(payload_b)

        # Channel loss (item 4a): independent Bernoulli erasure per received
        # frame. Guarded so loss_prob == 0.0 is a strict no-op — the RNG is
        # never even sampled. An erased frame is tallied as `dropped` (not
        # delivered) and never dispatched, so realized loss is measurable and
        # self-verifying (delivered falls below published x fanout). rng lives
        # on this thread only, so no lock needed.
        if self._loss_prob > 0.0 and self._rng.random() < self._loss_prob:
            self._tally(self._dropped_tally, topic, nbytes)
            return

        # Count the frame that actually arrived on the wire, BEFORE any delay:
        # delivery cost is a property of the network and the frame crossed the
        # wire on time; delay only defers when subscribers see it.
        self._tally(self._delivered_tally, topic, nbytes)

        # Channel delay (item 4b): 0.0 dispatches inline (bit-for-bit as
        # before); >0 queues for the drain loop to release once due.
        if self._delay_sec > 0.0:
            self._delay_queue.append(
                (time.monotonic() + self._delay_sec, topic, event)
            )
        else:
            self._dispatch(topic, event)

    def _drain_due(self) -> None:
        """Dispatch every queued frame whose delay has elapsed.

        Constant delay + arrival-order appends make due times monotonic, so
        the head of the deque is always the earliest — FIFO holds without a
        heap.
        """
        now = time.monotonic()
        q = self._delay_queue
        while q and q[0][0] <= now:
            _, topic, event = q.popleft()
            self._dispatch(topic, event)

    def _dispatch(self, topic: str, event: BaseEvent) -> None:
        """Deliver one event to every subscriber on its topic."""
        with self._cb_lock:
            callbacks = list(self._callbacks.get(topic, []))
        for cb in callbacks:
            try:
                cb(event)
            except Exception:
                # A buggy callback must not kill the receiver thread.
                # Subscribers are expected to handle and log their own
                # errors; we intentionally swallow here.
                pass
