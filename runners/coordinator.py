"""
Coordinator — mesh-driven recovery orchestration (step 8.4).

The Coordinator is Architecture C's value-add at runtime: it implements
the elected-coordinator pattern for distributed recovery without a
single point of failure.

Roles
-----
Each UAV-monitor process runs ONE Coordinator. A Coordinator plays
three concurrent roles, all driven by mesh subscriptions:

  Election listener   (always)
      Subscribed to `peer_position`. Tracks last-seen wall-clock per
      peer sysid. The coordinator at any moment is the peer with the
      lowest sysid among the alive set (peers seen within
      liveness_timeout_sec). Self is always alive — there is no need
      to publish heartbeats just for election; the peer-position
      stream serves as both liveness and coordination signal.

  Coordinator role    (only when self is the elected one)
      Subscribed to `isolation`. On each IsolationAnnounce, runs the
      RecoveryDecider; if a RecoveryRequest is produced, publishes it
      on the mesh so the target UAV's process picks it up.

  Target role         (when target_uav matches our UAV)
      Subscribed to `recovery_req`. On a request addressed to our
      UAV, drives the RecoveryExecutor and publishes a RecoveryAck.

Common
------
All Coordinators are subscribed to `recovery_ack` for global cleanup:
on each ack the local RecoveryDecider's `mark_recovered` is called
(so the next IsolationAnnounce for the same UAV produces a fresh
RecoveryRequest), and an optional `on_recovery_completed(uav_id,
success)` callback is invoked. The host monitor wires that callback
to lift its local IsolationEnforcer and un_isolate its IsolationDecider.

Async dispatch (PoC simplification)
-----------------------------------
RecoveryExecutor.execute is async (necessary for MAVSDK-driven
handlers). The mesh receiver thread is synchronous. To bridge them
the Coordinator currently runs each recovery via `asyncio.run()`,
which creates a short-lived event loop per request. This is fine for
sync handlers (subprocess.Popen, iptables) and acceptable for PoC.

When step 8.5 plugs in a real MAVSDK handler with a persistent gRPC
connection, this design needs to switch to a long-lived loop in a
dedicated thread (asyncio.run_coroutine_threadsafe). That refactor is
local to this module — public API is unchanged. Documented.

Election semantics edge cases
-----------------------------
- Empty alive set: defensive fallback to "lowest-of-all-configured".
  In practice self is always alive so this branch is unreachable in
  the running coordinator; it is here so is_coordinator is always
  total (never raises).
- Only self alive: self is coordinator. This is the early-startup
  state before peer_position from anyone else has arrived.
- Coordinator failover: when the previous coordinator goes silent,
  the next-lowest sysid takes over on its very next is_coordinator
  check. There is no announcement / handoff — it's purely a state
  read. This is deliberately simple: the dissertation can extend it
  with a quorum-style mechanism without changing this module's
  external surface.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Callable, Optional

from core.events import (
    IsolationAnnounce,
    PeerPositionAnnounce,
    RecoveryAck,
    RecoveryRequest,
)
from core.mesh import MeshBus
from decision.recovery import RecoveryDecider
from enforcement.recovery import RecoveryExecutor


RecoveryCompletedCallback = Callable[[str, bool], None]
"""Signature: (target_uav, success) -> None"""


class Coordinator:
    """Mesh-driven recovery coordinator for Architecture C."""

    DEFAULT_LIVENESS_TIMEOUT_SEC: float = 5.0

    def __init__(
        self,
        *,
        source: str,
        our_sysid: int,
        all_sysids: list[int],
        sysid_to_uav: dict[int, str],
        target_uav: str,
        mesh: MeshBus,
        recovery_decider: RecoveryDecider,
        recovery_executor: RecoveryExecutor,
        liveness_timeout_sec: float = DEFAULT_LIVENESS_TIMEOUT_SEC,
        on_recovery_completed: Optional[RecoveryCompletedCallback] = None,
    ) -> None:
        if our_sysid not in all_sysids:
            raise ValueError(
                f"our_sysid={our_sysid} not in all_sysids={sorted(all_sysids)}"
            )
        if liveness_timeout_sec <= 0:
            raise ValueError("liveness_timeout_sec must be positive")
        if not sysid_to_uav:
            raise ValueError("sysid_to_uav must not be empty")
        # Sanity: all_sysids must be a subset of sysid_to_uav keys.
        missing = set(all_sysids) - set(sysid_to_uav.keys())
        if missing:
            raise ValueError(
                f"all_sysids contains sysids without a uav mapping: {sorted(missing)}"
            )

        self._source = source
        self._our_sysid = our_sysid
        self._all_sysids: list[int] = list(all_sysids)
        self._sysid_to_uav: dict[int, str] = dict(sysid_to_uav)
        self._uav_to_sysid: dict[str, int] = {
            v: k for k, v in sysid_to_uav.items()
        }
        self._target_uav = target_uav
        self._mesh = mesh
        self._decider = recovery_decider
        self._executor = recovery_executor
        self._liveness_timeout = liveness_timeout_sec
        self._on_recovery_completed = on_recovery_completed

        # Liveness map: peer sysid -> last-seen wall-clock seconds.
        # Self is implicitly alive — never written here.
        self._last_seen: dict[int, float] = {}
        # Peers whose UAV has been announced as isolated. Excluded
        # from election even if their mesh peer_position is still
        # arriving. Removed by a successful RecoveryAck.
        self._isolated_sysids: set[int] = set()
        self._liveness_lock = threading.Lock()

        # Subscribe at construction. Callbacks fire after mesh.start()
        # (which is the caller's responsibility — see Monitor docstring).
        mesh.subscribe("peer_position", self._on_peer_position)
        mesh.subscribe("isolation", self._on_isolation_announce)
        mesh.subscribe("recovery_req", self._on_recovery_request)
        mesh.subscribe("recovery_ack", self._on_recovery_ack)

        # Diagnostics counters.
        self._n_peer_positions_seen: int = 0
        self._n_isolations_seen: int = 0
        self._n_recovery_requests_issued: int = 0
        self._n_recovery_requests_executed: int = 0
        self._n_recovery_acks_received: int = 0
        self._n_handler_errors: int = 0
        self._n_skipped_not_coordinator: int = 0
        self._n_skipped_not_target: int = 0

        self._started: bool = False

    # ----- lifecycle -----

    def start(self) -> None:
        # Coordinator does not own any threads — it lives entirely on
        # the mesh receiver thread. start/stop exist for symmetry with
        # other components and to gate future async-loop work.
        self._started = True

    def stop(self) -> None:
        self._started = False

    # ----- election -----

    @property
    def is_coordinator(self) -> bool:
        """True iff our sysid is the smallest among currently-alive
        non-isolated peers.

        An isolated peer (a UAV whose IsolationAnnounce has been
        received but no successful RecoveryAck yet) is excluded from
        the election. This includes self: if our own UAV is isolated
        we relinquish the coordinator role to the next-lowest
        non-isolated peer. This closes the trivial recursion where a
        UAV under attack could attempt to coordinate its own recovery.
        """
        with self._liveness_lock:
            # Fast path: if we are isolated, we cannot coordinate.
            if self._our_sysid in self._isolated_sysids:
                return False
            now = time.time()
            alive_peers = {
                sysid
                for sysid, ts in self._last_seen.items()
                if (now - ts) <= self._liveness_timeout
            }
            isolated = set(self._isolated_sysids)
        # Self is always alive in the mesh sense; isolated set already
        # subtracted above for the fast-path on self.
        alive = (alive_peers | {self._our_sysid}) - isolated
        candidates = [s for s in self._all_sysids if s in alive]
        if not candidates:
            # Every configured sysid is dead or isolated. Fleet is
            # fully disabled — no eligible coordinator.
            return False
        return self._our_sysid == min(candidates)

    @property
    def alive_sysids(self) -> frozenset[int]:
        """Snapshot of sysids considered alive AND non-isolated."""
        with self._liveness_lock:
            now = time.time()
            alive = {
                sysid
                for sysid, ts in self._last_seen.items()
                if (now - ts) <= self._liveness_timeout
            }
            isolated = set(self._isolated_sysids)
        return frozenset((alive | {self._our_sysid}) - isolated)

    @property
    def isolated_sysids(self) -> frozenset[int]:
        """Snapshot of sysids currently marked as isolated."""
        with self._liveness_lock:
            return frozenset(self._isolated_sysids)

    # ----- diagnostics -----

    @property
    def stats(self) -> dict[str, int]:
        return {
            "peer_positions_seen": self._n_peer_positions_seen,
            "isolations_seen": self._n_isolations_seen,
            "recovery_requests_issued": self._n_recovery_requests_issued,
            "recovery_requests_executed": self._n_recovery_requests_executed,
            "recovery_acks_received": self._n_recovery_acks_received,
            "handler_errors": self._n_handler_errors,
            "skipped_not_coordinator": self._n_skipped_not_coordinator,
            "skipped_not_target": self._n_skipped_not_target,
        }

    # ----- mesh callbacks -----

    def _on_peer_position(self, ann) -> None:
        if not isinstance(ann, PeerPositionAnnounce):
            return
        self._n_peer_positions_seen += 1
        sysid = self._uav_to_sysid.get(ann.uav_id)
        if sysid is None or sysid == self._our_sysid:
            return  # ignore self-announcements (mesh broadcast loopback) and unknown peers
        with self._liveness_lock:
            self._last_seen[sysid] = time.time()

    def _on_isolation_announce(self, ann) -> None:
        if not isinstance(ann, IsolationAnnounce):
            return
        self._n_isolations_seen += 1
        # Mark target as isolated BEFORE checking is_coordinator:
        # marking self-as-target may flip the election outcome (we lose
        # coordinator status to the next-lowest non-isolated peer).
        # This is the mechanism by which the coordinator role transfers
        # when the currently-elected coordinator's own UAV gets isolated.
        target_sysid = self._uav_to_sysid.get(ann.target_uav)
        if target_sysid is not None:
            with self._liveness_lock:
                self._isolated_sysids.add(target_sysid)
        if not self.is_coordinator:
            self._n_skipped_not_coordinator += 1
            return
        try:
            request = self._decider.evaluate(ann)
        except Exception:
            self._n_handler_errors += 1
            return
        if request is None:
            return
        try:
            self._mesh.publish(request)
            self._n_recovery_requests_issued += 1
        except Exception:
            self._n_handler_errors += 1

    def _on_recovery_request(self, req) -> None:
        if not isinstance(req, RecoveryRequest):
            return
        if req.target_uav != self._target_uav:
            self._n_skipped_not_target += 1
            return
        # Execute the (async) action handler synchronously by spinning
        # up a short-lived event loop. PoC simplification — see module
        # docstring.
        try:
            ack = asyncio.run(self._executor.execute(req))
        except Exception as exc:
            self._n_handler_errors += 1
            ack = RecoveryAck(
                source=self._source,
                target_uav=req.target_uav,
                action=req.action,
                success=False,
                executor=self._source,
                error=f"executor_run_failed:{exc}",
                caused_by=req.event_id,
            )
        self._n_recovery_requests_executed += 1
        try:
            self._mesh.publish(ack)
        except Exception:
            self._n_handler_errors += 1

    def _on_recovery_ack(self, ack) -> None:
        if not isinstance(ack, RecoveryAck):
            return
        self._n_recovery_acks_received += 1
        # Successful recovery lifts the isolation flag, restoring the
        # peer's election eligibility. Failed recovery keeps the peer
        # isolated — a subsequent retry is needed to lift it.
        if ack.success:
            target_sysid = self._uav_to_sysid.get(ack.target_uav)
            if target_sysid is not None:
                with self._liveness_lock:
                    self._isolated_sysids.discard(target_sysid)
        try:
            self._decider.mark_recovered(ack.target_uav)
        except Exception:
            self._n_handler_errors += 1
        if self._on_recovery_completed is not None:
            try:
                self._on_recovery_completed(ack.target_uav, ack.success)
            except Exception:
                self._n_handler_errors += 1
