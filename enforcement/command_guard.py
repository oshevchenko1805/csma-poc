"""
CommandGuard — in-path MAVLink command firewall (sysid allow-list).

A small UDP relay that sits in front of a UAV's command ingress. Every
frame the attacker (or anyone) sends to the guard's listen port is
inspected: its MAVLink source system id is read straight from the frame
header, and the frame is either forwarded to the autopilot or dropped.

Two states:
  - transparent (default): forward every frame. This is how the guard
    behaves in Architectures A and B, which have no recovery pipeline to
    ever change it, and in Architecture C before a detection fires.
  - filtering: drop frames whose sysid is NOT in the allow-list. Turned
    on in Architecture C when the recovery pipeline dispatches the
    `filter_commands` action (FilterCommandsHandler flips this guard).

Why this is a real control, not a port trick
--------------------------------------------
The decision is made on the MAVLink *sysid carried in the frame*, not on
the port. A frame from a whitelisted sysid is forwarded even while
filtering is active; a frame from a non-whitelisted sysid is dropped.
That is exactly what a companion-computer MAVLink firewall / MAVLink2
signing gate does in a real deployment. The allow-list check is provable
in isolation (see tests): feed sysid 1 -> forwarded, sysid 99 -> dropped.

The guard is deployed identically in all three architectures (it is
testbed infrastructure on the injection ingress). What differs is only
whether an automated recovery pipeline actuates its filtering — a
deployment/config difference, so the "architecture difference is
deployment" invariant holds.

Threading
---------
Runs its own daemon thread with a blocking UDP socket (short recv
timeout so stop() is responsive). No asyncio, no subprocess, no iptables
— so there is no OS-level state that can leak between runs. start() and
stop() are idempotent; stop() closes the socket and joins the thread.

start_filtering() only sets a threading.Event, so it is safe to call
from the mesh-receiver thread that runs the recovery handler.

Frame parsing
-------------
MAVLink v1 frame: byte[0]=0xFE, byte[3]=sysid.
MAVLink v2 frame: byte[0]=0xFD, byte[5]=sysid.
pymavlink emits v2 by default. A frame we cannot parse is forwarded
(fail-open): the guard must never silently swallow traffic it does not
understand, which would be a worse failure than a missed drop.
"""

from __future__ import annotations

import socket
import threading
from typing import FrozenSet, Optional

# MAVLink source systems that are legitimate members of the swarm plus
# the ground control station (255). Matches the attack's whitelist so the
# guard and the CommandInjectionDetector agree on what "authorised" means.
DEFAULT_WHITELIST: FrozenSet[int] = frozenset({1, 2, 3, 255})

MAVLINK_V1_MAGIC = 0xFE
MAVLINK_V2_MAGIC = 0xFD


def parse_sysid(frame: bytes) -> Optional[int]:
    """Read the MAVLink source sysid from a raw frame. None if unparseable."""
    if not frame:
        return None
    magic = frame[0]
    if magic == MAVLINK_V2_MAGIC and len(frame) >= 6:
        return frame[5]
    if magic == MAVLINK_V1_MAGIC and len(frame) >= 4:
        return frame[3]
    return None


class CommandGuard:
    """UDP relay that forwards MAVLink frames and can drop by sysid."""

    DEFAULT_RECV_TIMEOUT_SEC: float = 0.5
    DEFAULT_BUFFER_BYTES: int = 4096

    def __init__(
        self,
        *,
        listen_port: int,
        forward_port: int,
        listen_host: str = "127.0.0.1",
        forward_host: str = "127.0.0.1",
        whitelist: FrozenSet[int] = DEFAULT_WHITELIST,
        recv_timeout_sec: float = DEFAULT_RECV_TIMEOUT_SEC,
    ) -> None:
        if listen_port <= 0 or forward_port <= 0:
            raise ValueError("ports must be positive")
        if recv_timeout_sec <= 0:
            raise ValueError("recv_timeout_sec must be positive")
        self._listen_addr = (listen_host, listen_port)
        self._forward_addr = (forward_host, forward_port)
        self._whitelist = frozenset(whitelist)
        self._recv_timeout = recv_timeout_sec

        self._sock: Optional[socket.socket] = None
        self._out_sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._filtering = threading.Event()

        # Diagnostics (single-writer: the relay thread).
        self._n_forwarded = 0
        self._n_dropped = 0

    # ----- lifecycle -----

    def start(self) -> None:
        """Bind the listen socket and spawn the relay thread. Idempotent."""
        if self._thread is not None:
            return
        self._stop.clear()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(self._listen_addr)
        sock.settimeout(self._recv_timeout)
        self._sock = sock
        self._out_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._thread = threading.Thread(
            target=self._loop, name=f"command_guard_{self._listen_addr[1]}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the relay thread and close sockets. Idempotent."""
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=2.0)
        self._thread = None
        for s in (self._sock, self._out_sock):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        self._sock = None
        self._out_sock = None

    # ----- filtering control -----

    def start_filtering(self) -> None:
        """Begin dropping non-whitelisted sysids. Threadsafe, idempotent."""
        self._filtering.set()

    def stop_filtering(self) -> None:
        self._filtering.clear()

    @property
    def is_filtering(self) -> bool:
        return self._filtering.is_set()

    # ----- diagnostics -----

    @property
    def forwarded(self) -> int:
        return self._n_forwarded

    @property
    def dropped(self) -> int:
        return self._n_dropped

    # ----- internals -----

    def _loop(self) -> None:
        assert self._sock is not None
        assert self._out_sock is not None
        while not self._stop.is_set():
            try:
                frame, _src = self._sock.recvfrom(self.DEFAULT_BUFFER_BYTES)
            except socket.timeout:
                continue
            except OSError:
                break  # socket closed under us during stop()
            if self._should_drop(frame):
                self._n_dropped += 1
                continue
            try:
                self._out_sock.sendto(frame, self._forward_addr)
                self._n_forwarded += 1
            except OSError:
                # Forward target transiently unavailable; treat like a
                # lost packet rather than killing the relay.
                pass

    def _should_drop(self, frame: bytes) -> bool:
        if not self._filtering.is_set():
            return False
        sysid = parse_sysid(frame)
        if sysid is None:
            return False  # fail-open on unparseable frames
        return sysid not in self._whitelist
