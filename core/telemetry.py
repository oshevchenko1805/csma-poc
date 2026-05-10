"""
MAVLink telemetry listener for the CSMA PoC.

A TelemetryListener binds to one MAVLink UDP endpoint, filters messages
by source system ID, decodes whitelisted message types, and dispatches
them as TelemetryEvent to a callback.

Threading model:
    A daemon thread runs a recv loop with a short blocking timeout on
    the pymavlink connection. The callback runs on this thread, so any
    state it touches must be thread-safe. A buggy callback that raises
    is logged-and-swallowed, the loop continues — same contract as the
    mesh receiver.

Design choices:
    - One listener per UAV endpoint. Architecture A runs three listeners
      in the GS process; B and C run one listener per UAV monitor process.
    - Source-system-ID filtering happens at the listener so the same
      broadcast endpoint can be used safely if needed.
    - A message-type whitelist is pushed down into pymavlink's recv_match
      so the long tail of PX4 internal topics never even reaches Python
      code. This keeps storage and detector logic on signal, not noise.
    - to_dict() output is sanitized for JSON: bytes -> ascii str, numpy
      scalars unwrapped via .item(), unknown types fall back to repr.
      PyMAVLink messages occasionally carry bytes fields (e.g.
      STATUSTEXT.text) that would otherwise break json.dumps.
    - Connection injection (`_connection` kwarg) makes the listener
      unit-testable without a live MAVLink endpoint.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from core.events import TelemetryEvent


# Default whitelist: messages relevant to the three attack cases plus
# minimum operational telemetry. Edit per-listener if you want more/less.
DEFAULT_MSG_WHITELIST: frozenset[str] = frozenset(
    {
        # liveness
        "HEARTBEAT",
        # position / velocity / attitude
        "GLOBAL_POSITION_INT",
        "LOCAL_POSITION_NED",
        "ATTITUDE",
        # GPS spoofing detection
        "GPS_RAW_INT",
        "ESTIMATOR_STATUS",
        # command-injection detection
        "COMMAND_LONG",
        "COMMAND_INT",
        "COMMAND_ACK",
        # operational state
        "SYS_STATUS",
        "STATUSTEXT",
    }
)


TelemetryCallback = Callable[[TelemetryEvent], None]


# ---------------------------------------------------------------------------
# JSON-safe sanitization for pymavlink message fields
# ---------------------------------------------------------------------------


def _sanitize_value(v: Any) -> Any:
    """Convert a single value to a JSON-serializable form."""
    if isinstance(v, bool):  # must come before int (bool is int subclass)
        return v
    if isinstance(v, (int, float, str)) or v is None:
        return v
    if isinstance(v, bytes):
        # STATUSTEXT.text and similar
        return v.decode("ascii", errors="replace").rstrip("\x00")
    if isinstance(v, (list, tuple)):
        return [_sanitize_value(x) for x in v]
    if isinstance(v, dict):
        return _sanitize_dict(v)
    # numpy scalars expose .item()
    item = getattr(v, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    return repr(v)


def _sanitize_dict(d: dict[str, Any]) -> dict[str, Any]:
    return {str(k): _sanitize_value(v) for k, v in d.items()}


# ---------------------------------------------------------------------------
# TelemetryListener
# ---------------------------------------------------------------------------


class TelemetryListener:
    """
    Listens on one MAVLink endpoint and emits TelemetryEvents.

    Parameters
    ----------
    endpoint         pymavlink connection string. For PX4 SITL the
                     companion-computer port: 'udpin:127.0.0.1:14540'.
    expected_sysid   Only messages whose src system ID matches will be
                     forwarded. PX4 SITL instance i has sysid i+1 by
                     default (instance 0 -> sysid 1).
    uav_id           Logical UAV identifier used in the emitted events
                     (e.g. 'uav_0').
    source           Process identifier used as TelemetryEvent.source
                     (e.g. 'monitor_uav_0', 'monitor_gs').
    msg_whitelist    Set of MAVLink message-type names to forward.
                     Defaults to DEFAULT_MSG_WHITELIST.
    callback         Invoked once per accepted event on the recv thread.
    recv_timeout_sec recv_match() blocking timeout. Shorter = faster
                     shutdown, higher CPU overhead.
    _connection      Test hook: inject a pre-built connection object
                     instead of letting the listener call
                     pymavlink.mavutil.mavlink_connection().
    """

    def __init__(
        self,
        endpoint: str,
        expected_sysid: int,
        uav_id: str,
        source: str,
        *,
        msg_whitelist: Optional[set[str]] = None,
        callback: Optional[TelemetryCallback] = None,
        recv_timeout_sec: float = 0.5,
        _connection: Any = None,
    ) -> None:
        self.endpoint = endpoint
        self.expected_sysid = expected_sysid
        self.uav_id = uav_id
        self.source = source
        self.msg_whitelist: frozenset[str] = (
            frozenset(msg_whitelist) if msg_whitelist is not None
            else DEFAULT_MSG_WHITELIST
        )
        self.callback = callback
        self.recv_timeout_sec = recv_timeout_sec

        self._injected_connection = _connection
        self._conn: Any = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started: bool = False

        # Stats useful for diagnostics and tests.
        self._n_received: int = 0
        self._n_filtered_sysid: int = 0
        self._n_filtered_type: int = 0
        self._n_emitted: int = 0
        self._n_callback_errors: int = 0

    # ----- lifecycle -----

    def start(self) -> None:
        if self._started:
            return
        self._conn = self._open_connection()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._receive_loop,
            name=f"telemetry-{self.uav_id}",
            daemon=True,
        )
        self._thread.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.recv_timeout_sec * 4)
        if self._conn is not None:
            try:
                close = getattr(self._conn, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass
            self._conn = None
        self._started = False

    def __enter__(self) -> "TelemetryListener":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    # ----- introspection -----

    @property
    def stats(self) -> dict[str, int]:
        return {
            "received": self._n_received,
            "filtered_sysid": self._n_filtered_sysid,
            "filtered_type": self._n_filtered_type,
            "emitted": self._n_emitted,
            "callback_errors": self._n_callback_errors,
        }

    # ----- internals -----

    def _open_connection(self) -> Any:
        if self._injected_connection is not None:
            return self._injected_connection
        from pymavlink import mavutil
        return mavutil.mavlink_connection(self.endpoint)

    def _receive_loop(self) -> None:
        whitelist_arg = list(self.msg_whitelist)
        while not self._stop_event.is_set():
            try:
                msg = self._conn.recv_match(
                    type=whitelist_arg,
                    blocking=True,
                    timeout=self.recv_timeout_sec,
                )
            except Exception:
                # Connection issue; brief sleep and retry until stop().
                time.sleep(0.1)
                continue
            if msg is None:
                continue

            self._n_received += 1

            # Defensive double-check (should be redundant given recv_match filter).
            msg_type = msg.get_type()
            if msg_type not in self.msg_whitelist:
                self._n_filtered_type += 1
                continue

            try:
                src_sys = msg.get_srcSystem()
            except AttributeError:
                src_sys = -1
            if src_sys != self.expected_sysid:
                self._n_filtered_sysid += 1
                continue

            try:
                fields = _sanitize_dict(msg.to_dict())
            except Exception:
                # If a particular message can't be serialized, skip it
                # rather than killing the loop.
                self._n_filtered_type += 1
                continue

            # Stash the message origin's system ID alongside the payload.
            # Detectors that care about message provenance (e.g. command
            # injection by sysid whitelist) read this from event.data.
            # Underscore prefix marks it as metadata, not a real MAVLink
            # field.
            fields["_src_sysid"] = src_sys

            event = TelemetryEvent(
                source=self.source,
                uav_id=self.uav_id,
                msg_type=msg_type,
                data=fields,
            )
            self._n_emitted += 1

            if self.callback is not None:
                try:
                    self.callback(event)
                except Exception:
                    self._n_callback_errors += 1
                    # Swallow — same contract as ZmqMesh receiver.

