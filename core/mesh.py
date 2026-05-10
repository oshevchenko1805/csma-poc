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
"""

from __future__ import annotations

import json
import threading
import time
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
    is architecture-agnostic.
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

    Threading model:
        A daemon thread runs a poll loop on the SUB socket. Incoming
        messages are dispatched to subscribers by topic. Callbacks run on
        the receiver thread, so they must be thread-safe with respect to
        any state they touch.

        A buggy callback that raises an exception is logged-and-swallowed
        — one bad subscriber must not bring down the entire bus.
    """

    def __init__(
        self,
        self_endpoint: str,
        peer_endpoints: list[str],
        slow_joiner_delay_sec: float = 0.3,
    ) -> None:
        self.self_endpoint = self_endpoint
        self.peer_endpoints = list(peer_endpoints)
        self.slow_joiner_delay_sec = slow_joiner_delay_sec

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
        self._started = False

    # ----- pub/sub API -----

    def publish(self, event: BaseEvent) -> None:
        if not self._started or self._pub is None:
            raise RuntimeError("ZmqMesh.publish called before start()")
        topic = topic_for(event)
        payload = event.to_json().encode("utf-8")
        self._pub.send_multipart([topic.encode("utf-8"), payload])

    def subscribe(self, topic: str, callback: EventCallback) -> None:
        with self._cb_lock:
            self._callbacks.setdefault(topic, []).append(callback)

    # ----- receiver thread -----

    def _receive_loop(self) -> None:
        assert self._sub is not None
        poller = self._zmq.Poller()
        poller.register(self._sub, self._zmq.POLLIN)

        while not self._stop_event.is_set():
            try:
                socks = dict(poller.poll(timeout=200))  # ms
            except self._zmq.ZMQError:
                # Context terminating during shutdown.
                break

            if self._sub not in socks:
                continue

            try:
                parts = self._sub.recv_multipart(flags=self._zmq.NOBLOCK)
            except self._zmq.Again:
                continue
            except self._zmq.ZMQError:
                break

            if len(parts) != 2:
                continue  # malformed frame

            topic_b, payload_b = parts
            try:
                topic = topic_b.decode("utf-8")
                event = event_from_json(payload_b.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                # Don't crash a peer because someone sent garbage.
                continue

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
