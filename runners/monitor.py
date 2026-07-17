"""
Single-UAV monitor process — observation + isolation + mesh
(steps 8.1 + 8.2 + 8.3).

A Monitor wires together one TelemetryListener, a set of Detector
instances, and one EventLogger. It routes incoming telemetry events to
every detector via feed(), and on a fixed cadence calls tick() on every
detector so absence-of-event signals (heartbeat timeout) can fire.

Beyond observation, the monitor optionally carries:
  - IsolationDecider + IsolationEnforcer (8.2). Every SecurityEvent
    emitted by a detector flows through:
        SecurityEvent
          -> IsolationDecider.evaluate()
          -> IsolationAnnounce
          -> IsolationEnforcer.enforce()
          -> log
  - MeshBus + CrossCheckDetector (8.3). Architecture C only:
      * peer-position publisher: a daemon thread publishes
        PeerPositionAnnounce on the mesh every peer_publish_period_sec,
        sourced from the last observed GLOBAL_POSITION_INT.
      * mesh subscriber: incoming PeerPositionAnnounce is fed to the
        CrossCheckDetector; SecurityEvents it produces flow through
        the same _emit_security pipeline (decider -> enforcer -> log).

Architectural pinning
---------------------
- Architecture A: GS process instantiates three Monitors (one per
  watched UAV) — each with LocalIsolationEnforcer, no mesh.
- Architecture B: each UAV monitor process has one Monitor with
  LocalIsolationEnforcer, no mesh.
- Architecture C: each UAV monitor process has one Monitor with
  MeshAnnouncingIsolationEnforcer, a CrossCheckDetector, and a real
  ZmqMesh.

What this step does NOT include yet:
  - Coordinator with recovery requests (step 8.4)

Telemetry recording (OPEN-3)
----------------------------
Optionally the monitor records the raw telemetry it fed to its
detectors, to `telemetry_log_path`. This exists because monitors log
events, not telemetry: a detector that never fires leaves no trace of
what it saw, which is exactly why OPEN-3 is unanswerable for the runs
already on disk (RESULTS_NOTES R8 — one run detected nothing and
contains zero security events, so there is nothing to inspect).

Three properties this channel must have, and why:

  - **Its own file, never `log_path`.** The previous `log_telemetry`
    flag wrote into the monitor's event log, which `merge_jsonl` folds
    into `merged.jsonl` — drowning the event stream the metrics layer
    reads. Same reasoning that keeps `trajectory.jsonl` out of the merge.
  - **Recorded AFTER the detectors run**, not before. The old flag sat
    on the path to `SecurityEvent`, so its I/O would have been added to
    MTTD — moving the very quantity being measured. The runs_v3 baseline
    is MTTD 3.113 +/- 0.677 s; instrumentation must leave it there.
  - **Filtered by msg_type**, default ESTIMATOR_STATUS only. The
    listener whitelist includes ATTITUDE at ~50 Hz; recording all of it
    for 3 UAVs x 160 s would be noise, not evidence.

Scope: this channel lives inside the system under test. Under
`monitor_takeout` it dies with the monitor, so its availability is
architecture-dependent and NOTHING in table 3.13 may be computed from
it (thesis 3.5.5). It is diagnostic. Ground truth for metrics stays with
Gazebo — see metrics/flight_check.py.

Under `detector_takeout` the opposite holds, usefully:
disable_local_detectors() empties the detector list but the listener
keeps running, so the series shows what the silenced detector WOULD have
seen — direct evidence of R5's mechanism rather than only its
consequence.

Threading model
---------------
Up to four daemon threads coexist:
  1. TelemetryListener — receives MAVLink, calls _on_telemetry.
  2. Tick — fires every tick_period_sec, calls tick() on detectors.
  3. Peer-position publisher (mesh-only) — every
     peer_publish_period_sec publishes the last known position.
  4. Mesh receiver (inside ZmqMesh) — calls _on_peer_position.

Synchronization:
  - detector_lock serializes feed() and tick() over Detector state.
    _on_peer_position also takes detector_lock when delegating to the
    cross-check detector and through the downstream pipeline.
  - position_lock protects _last_position which is written from the
    listener thread and read from the peer-publish thread. Separate
    from detector_lock so peer-publish never blocks the listener.
  - EventLogger is internally locked, so the telemetry recorder is safe
    on the listener thread without further synchronization.

Mesh failures
-------------
mesh.publish() raising in the peer-publish loop is counted in
handler_errors but does not stop the loop. Mesh delivery is
best-effort — under packet loss or transport failure, the experiment
metrics still reflect what actually happened locally on each peer.

Mesh lifecycle ownership
------------------------
The monitor does NOT call mesh.start() or mesh.stop(). The caller is
responsible for the mesh lifecycle. This is so a single mesh instance
can be shared across components (a coordinator subscriber, multiple
publishers, etc.) without the monitor making lifecycle assumptions.
Tests and the experiment runner must mesh.start() before monitor.start()
and mesh.stop() after monitor.stop().
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Iterable, Optional

from core.events import (
    IsolationAnnounce,
    PeerPositionAnnounce,
    SecurityEvent,
    TelemetryEvent,
)
from core.logger import EventLogger
from core.mesh import MeshBus
from core.telemetry import TelemetryListener
from decision.isolation import IsolationDecider
from detectors.base import Detector
from detectors.cross_check import CrossCheckDetector
from enforcement.isolation import IsolationEnforcer


DEFAULT_TELEMETRY_LOG_TYPES: frozenset[str] = frozenset(
    {"ESTIMATOR_STATUS", "LOCAL_POSITION_NED", "GPS_RAW_INT"}
)
"""What gets recorded when telemetry_log_path is set.

Three channels, measured live on this build (smoke_telemetry, uav_0):

ESTIMATOR_STATUS (0.9 Hz) carries `pos_horiz_ratio`, the EKF residual
GpsSpoofingDetector fires on. ~160 samples per trial per UAV, kept in
full. This is the series OPEN-3 needs.

LOCAL_POSITION_NED (29.4 Hz) carries the position PX4 BELIEVES it is at
— what GPS spoofing corrupts. Paired against the Gazebo pose it gives
true-vs-believed divergence: how far the attack moved the autopilot's
world model, as opposed to how far the airframe actually moved (R4).
Its frame is fixed by the MAVLink spec (x=north, y=east, z=down), which
makes it the instrument that SETTLES the Gazebo axis question rather
than another assumption about it. Origin is EKF start, NOT the Gazebo
world origin: uav_1 and uav_2 launch at +5 m and +10 m, so that offset
must be subtracted or a healthy UAV reads 5 m of divergence.

GPS_RAW_INT (29.8 Hz) carries the GPS input — the spoof itself. With the
other two it closes the triangle truth -> falsified input -> belief, and
`pos_horiz_ratio` is precisely the residual between input and
prediction. Expected to show the SIM_GPS_OFF_N offset because GZBridge
generates the simulated GPS, but that is a hypothesis until a baseline
and an attack run are compared. Geodetic (lat/lon in 1e7 deg), so
comparing it to NED metres needs the EKF origin — not simply three
series side by side.

Volume: the two 30 Hz channels are ~14k samples per trial per UAV,
~2.8 MB of gitignored .jsonl. The summary carries computed divergence at
~1 Hz instead — a pair is rate-limited by its slower side and the Gazebo
recorder runs at 4.6 Hz.

Everything else in the listener whitelist is either irrelevant to a
detector or too fast to be worth storing (ATTITUDE 97.6 Hz,
GLOBAL_POSITION_INT 49.1 Hz).
"""


class Monitor:
    """Single-UAV monitor: observation + optional isolation pipeline."""

    DEFAULT_TICK_PERIOD_SEC: float = 1.0
    DEFAULT_RECV_TIMEOUT_SEC: float = 0.5
    DEFAULT_PEER_PUBLISH_PERIOD_SEC: float = 1.0

    def __init__(
        self,
        *,
        uav_id: str,
        source: str,
        telemetry_endpoint: str,
        sysid: int,
        detectors: list[Detector],
        log_path: Path,
        isolation_decider: Optional[IsolationDecider] = None,
        isolation_enforcer: Optional[IsolationEnforcer] = None,
        mesh: Optional[MeshBus] = None,
        cross_check: Optional[CrossCheckDetector] = None,
        tick_period_sec: float = DEFAULT_TICK_PERIOD_SEC,
        peer_publish_period_sec: float = DEFAULT_PEER_PUBLISH_PERIOD_SEC,
        telemetry_log_path: Optional[Path] = None,
        telemetry_log_types: Optional[Iterable[str]] = None,
        failure_domain: str = "",
        recv_timeout_sec: float = DEFAULT_RECV_TIMEOUT_SEC,
        _telemetry_connection=None,  # test hook
    ) -> None:
        if tick_period_sec <= 0:
            raise ValueError("tick_period_sec must be positive")
        if peer_publish_period_sec <= 0:
            raise ValueError("peer_publish_period_sec must be positive")
        if not detectors:
            raise ValueError("at least one detector required")

        # Cross-field invariant: enforcer requires decider. The reverse
        # is fine — a decider without an enforcer means "log
        # IsolationAnnounces but don't materialize them" (a useful
        # diagnostic mode).
        if isolation_enforcer is not None and isolation_decider is None:
            raise ValueError(
                "isolation_enforcer requires isolation_decider to be set"
            )

        # Choosing what to record without saying where is a silent no-op;
        # fail loudly instead of collecting nothing and looking healthy.
        if telemetry_log_types is not None and telemetry_log_path is None:
            raise ValueError(
                "telemetry_log_types requires telemetry_log_path to be set"
            )

        # cross_check requires a mesh (it operates on PeerPositionAnnounce
        # which only travel over the mesh). The reverse — mesh without
        # cross_check — is allowed: the monitor will publish peer
        # positions even if it doesn't subscribe to anyone else's.
        if cross_check is not None and mesh is None:
            raise ValueError("cross_check detector requires mesh to be set")
        if cross_check is not None and cross_check.monitor_uav_id != uav_id:
            raise ValueError(
                f"cross_check.monitor_uav_id={cross_check.monitor_uav_id!r} "
                f"does not match monitor uav_id={uav_id!r}"
            )

        self._uav_id = uav_id
        self._source = source
        self._failure_domain = failure_domain or uav_id
        self._tick_period = tick_period_sec
        self._peer_publish_period = peer_publish_period_sec

        self._detectors: list[Detector] = list(detectors)
        for d in self._detectors:
            if d.target_uav != uav_id:
                raise ValueError(
                    f"detector {d.name!r} targets {d.target_uav!r}, "
                    f"monitor watches {uav_id!r}"
                )

        self._isolation_decider = isolation_decider
        self._isolation_enforcer = isolation_enforcer
        self._mesh = mesh
        self._cross_check = cross_check

        self._logger = EventLogger(log_path)

        # Separate file, separate logger: telemetry must never reach
        # merged.jsonl (see module docstring).
        self._telemetry_log_types: frozenset[str] = (
            frozenset(telemetry_log_types)
            if telemetry_log_types is not None
            else DEFAULT_TELEMETRY_LOG_TYPES
        )
        self._telemetry_logger: Optional[EventLogger] = (
            EventLogger(telemetry_log_path)
            if telemetry_log_path is not None
            else None
        )

        self._listener = TelemetryListener(
            endpoint=telemetry_endpoint,
            expected_sysid=sysid,
            uav_id=uav_id,
            source=source,
            callback=self._on_telemetry,
            recv_timeout_sec=recv_timeout_sec,
            _connection=_telemetry_connection,
        )

        self._detector_lock = threading.Lock()
        self._position_lock = threading.Lock()
        self._last_position: Optional[tuple[float, float, float, float]] = None
        # (lat_deg, lon_deg, alt_m, sample_ts)

        self._tick_thread: Optional[threading.Thread] = None
        self._peer_pub_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started: bool = False

        # Subscribe to peer-position topic ONCE at construction so the
        # subscription is established before start(). Mesh implementations
        # are expected to buffer subscriptions until start().
        if self._cross_check is not None and self._mesh is not None:
            self._mesh.subscribe("peer_position", self._on_peer_position)

        # Diagnostics counters.
        self._n_telemetry_seen: int = 0
        self._n_telemetry_logged: int = 0
        self._n_security_emitted: int = 0
        self._n_isolation_announced: int = 0
        self._n_isolation_enforced: int = 0
        self._n_peer_positions_published: int = 0
        self._n_peer_positions_received: int = 0
        self._n_handler_errors: int = 0

    # ----- lifecycle -----

    def start(self) -> None:
        if self._started:
            return
        self._stop_event.clear()
        self._listener.start()
        self._tick_thread = threading.Thread(
            target=self._tick_loop,
            name=f"monitor-tick-{self._uav_id}",
            daemon=True,
        )
        self._tick_thread.start()
        if self._mesh is not None:
            self._peer_pub_thread = threading.Thread(
                target=self._peer_publish_loop,
                name=f"monitor-peerpub-{self._uav_id}",
                daemon=True,
            )
            self._peer_pub_thread.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._stop_event.set()
        self._listener.stop()
        if self._tick_thread is not None:
            self._tick_thread.join(timeout=self._tick_period * 4)
            self._tick_thread = None
        if self._peer_pub_thread is not None:
            self._peer_pub_thread.join(timeout=self._peer_publish_period * 4)
            self._peer_pub_thread = None
        self._logger.close()
        # Closed after the listener has stopped, so the last sample is
        # flushed before the runner reads this file back for the summary.
        if self._telemetry_logger is not None:
            try:
                self._telemetry_logger.close()
            except Exception:
                pass
        self._started = False

    def disable_local_detectors(self) -> None:
        """Silence this monitor's local, telemetry-driven detectors while
        leaving the monitor otherwise alive (listener, tick, peer-position
        publishing and mesh cross-check all keep running).

        Models a threat where an adversary compromises node-local
        intrusion detection on a UAV, yet the UAV keeps broadcasting its
        telemetry/position (it must, to hold formation). Used by the
        detector_takeout attack. Idempotent.

        After this call feed()/tick() over the local detectors are
        no-ops, so the monitor emits no SecurityEvents from its own
        telemetry. In Architecture C neighbours can still catch this UAV
        via cross_check on the still-published peer positions; in A/B
        there is no such second opinion.

        Telemetry recording is deliberately NOT disabled: the listener is
        untouched by this attack, so the recorded series shows exactly
        what the silenced detector would have seen. That is the mechanism
        of R5, not just its outcome.
        """
        with self._detector_lock:
            self._detectors = []

    def __enter__(self) -> "Monitor":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    # ----- diagnostics -----

    @property
    def stats(self) -> dict[str, int]:
        s = {
            "telemetry_seen": self._n_telemetry_seen,
            "telemetry_logged": self._n_telemetry_logged,
            "security_emitted": self._n_security_emitted,
            "isolation_announced": self._n_isolation_announced,
            "isolation_enforced": self._n_isolation_enforced,
            "peer_positions_published": self._n_peer_positions_published,
            "peer_positions_received": self._n_peer_positions_received,
            "handler_errors": self._n_handler_errors,
        }
        for k, v in self._listener.stats.items():
            s[f"listener_{k}"] = v
        if self._isolation_enforcer is not None:
            for k, v in self._isolation_enforcer.stats.items():
                s[f"enforcer_{k}"] = v
        return s

    @property
    def uav_id(self) -> str:
        return self._uav_id

    @property
    def failure_domain(self) -> str:
        return self._failure_domain

    @property
    def telemetry_log_types(self) -> frozenset[str]:
        return self._telemetry_log_types

    @property
    def isolation_decider(self) -> Optional[IsolationDecider]:
        return self._isolation_decider

    @property
    def isolation_enforcer(self) -> Optional[IsolationEnforcer]:
        return self._isolation_enforcer

    # ----- callbacks -----

    def _on_telemetry(self, event: TelemetryEvent) -> None:
        self._n_telemetry_seen += 1

        # Cache last GPS position for peer-position publishing. Done
        # outside detector_lock so the listener thread is never blocked
        # by the peer-publish thread.
        if event.msg_type == "GLOBAL_POSITION_INT":
            self._update_last_position(event)

        with self._detector_lock:
            for d in self._detectors:
                try:
                    result = d.feed(event)
                except Exception:
                    self._n_handler_errors += 1
                    continue
                if result is not None:
                    self._emit_security(result)

        # Recorded LAST, deliberately: everything above is on the path to
        # a SecurityEvent, and MTTD is measured from it. Instrumentation
        # that sits upstream of the measurement changes the measurement.
        self._record_telemetry(event)

    def _on_peer_position(self, announcement) -> None:
        """Mesh subscriber callback. Runs on the mesh receiver thread."""
        # Defensive type check: subscribe() in tests may deliver
        # unexpected payloads.
        if not isinstance(announcement, PeerPositionAnnounce):
            return
        self._n_peer_positions_received += 1
        if self._cross_check is None:
            return
        with self._detector_lock:
            try:
                result = self._cross_check.feed_peer_position(announcement)
            except Exception:
                self._n_handler_errors += 1
                return
            if result is not None:
                self._emit_security(result)

    def _tick_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._tick_period)
            if self._stop_event.is_set():
                break
            now = time.time()
            with self._detector_lock:
                for d in self._detectors:
                    try:
                        result = d.tick(now)
                    except Exception:
                        self._n_handler_errors += 1
                        continue
                    if result is not None:
                        self._emit_security(result)

    def _peer_publish_loop(self) -> None:
        """Publish PeerPositionAnnounce on the mesh on a fixed cadence."""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._peer_publish_period)
            if self._stop_event.is_set():
                break
            self._publish_peer_position()

    def _update_last_position(self, event: TelemetryEvent) -> None:
        """Convert GLOBAL_POSITION_INT to (lat, lon, alt, sample_ts)."""
        try:
            lat_e7 = event.data["lat"]
            lon_e7 = event.data["lon"]
            alt_mm = event.data.get("alt", 0)
            lat = float(lat_e7) / 1e7
            lon = float(lon_e7) / 1e7
            alt = float(alt_mm) / 1000.0
        except (KeyError, TypeError, ValueError):
            return
        sample_ts = event.timestamp
        with self._position_lock:
            self._last_position = (lat, lon, alt, sample_ts)

    def _publish_peer_position(self) -> None:
        if self._mesh is None:
            return
        with self._position_lock:
            if self._last_position is None:
                return
            lat, lon, alt, sample_ts = self._last_position

        announcement = PeerPositionAnnounce(
            source=self._source,
            uav_id=self._uav_id,
            lat=lat,
            lon=lon,
            alt=alt,
            sample_timestamp=sample_ts,
        )
        try:
            self._mesh.publish(announcement)
            self._n_peer_positions_published += 1
        except Exception:
            self._n_handler_errors += 1

    # ----- pipeline -----

    def _emit_security(self, event: SecurityEvent) -> None:
        """SecurityEvent -> log -> decider -> enforcer."""
        self._n_security_emitted += 1
        self._safe_log(event)

        if self._isolation_decider is None:
            return
        try:
            announcement = self._isolation_decider.evaluate(event)
        except Exception:
            self._n_handler_errors += 1
            return
        if announcement is None:
            return

        self._n_isolation_announced += 1
        self._safe_log(announcement)

        if self._isolation_enforcer is None:
            return
        try:
            ok = self._isolation_enforcer.enforce(announcement)
        except Exception:
            self._n_handler_errors += 1
            return
        if ok:
            self._n_isolation_enforced += 1

    def _record_telemetry(self, event: TelemetryEvent) -> None:
        """Append one raw sample to the diagnostic telemetry file."""
        if self._telemetry_logger is None:
            return
        if event.msg_type not in self._telemetry_log_types:
            return
        try:
            self._telemetry_logger.log(event)
            self._n_telemetry_logged += 1
        except Exception:
            # A diagnostic file is not worth failing a flight over — the
            # same contract the mesh publisher and the trajectory
            # recorder already follow.
            self._n_handler_errors += 1

    def _safe_log(self, event) -> None:
        try:
            self._logger.log(event)
        except Exception:
            self._n_handler_errors += 1
