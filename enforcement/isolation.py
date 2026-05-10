"""
Isolation enforcement.

A decision module produces an IsolationAnnounce. An enforcement module
turns it into an actual side effect — marking state, publishing on the
mesh, sending a MAVLink command, etc.

Two implementations are provided. The third is *not* a separate class:
Architecture A's "ground station command" is the same local-state action
as Architecture B; the architectural difference is *where* the enforcer
runs, not what it does in code. We instantiate LocalIsolationEnforcer at
the GS process for A and at each per-UAV monitor for B.

  LocalIsolationEnforcer
      Used in Architectures A and B. Tracks isolated UAVs in a local
      set. Lifting and re-isolating are explicit operations. No
      cross-process communication.

  MeshAnnouncingIsolationEnforcer
      Used in Architecture C. Same local-state behaviour as
      LocalIsolationEnforcer, plus publishes the IsolationAnnounce on
      the mesh so peers learn about the isolation. This is what enables
      coordinated cross-checks and the elected coordinator to issue a
      RecoveryRequest.

PoC simplification (Chapter 4)
------------------------------
A real deployment of "isolation" would also drop or filter MAVLink
traffic from/to the isolated UAV at the network layer (e.g. via an
MAVLink router rule, or by reconfiguring the companion computer's
firewall). In the PoC we mark the UAV in local state and rely on the
host monitor to act on that state when handling subsequent events
(e.g. monitor consumes is_isolated() to decide whether to forward
peer position announcements). Documented explicitly.

Mesh publish failures
---------------------
If mesh.publish() raises, we still mark the UAV as isolated locally —
otherwise we would have an inconsistent view across the system. The
exception is logged-and-swallowed and the enforce call returns True.
The host monitor's stats include mesh_publish_errors so this is
visible in post-hoc analysis.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.events import IsolationAnnounce
from core.mesh import MeshBus


class IsolationEnforcer(ABC):
    """Common interface for isolation enforcement."""

    @abstractmethod
    def enforce(self, announcement: IsolationAnnounce) -> bool:
        """
        Apply isolation for the announcement's target UAV.

        Returns True if the action was carried out successfully (state
        is updated and any required propagation has been attempted).
        Idempotent: enforcing on an already-isolated UAV returns True
        without producing duplicate side effects.
        """

    @abstractmethod
    def lift(self, uav_id: str) -> bool:
        """
        Lift isolation. Returns True if the UAV was previously isolated
        and is now lifted; False if it was not isolated.

        Lifting deliberately does NOT propagate over the mesh in v1 —
        recovery is signalled by RecoveryAck on its own topic.
        """

    @abstractmethod
    def is_isolated(self, uav_id: str) -> bool: ...

    @abstractmethod
    def reset(self) -> None: ...

    @property
    @abstractmethod
    def isolated_uavs(self) -> frozenset[str]: ...

    @property
    @abstractmethod
    def stats(self) -> dict[str, int]:
        """Counters for diagnostics: enforce_count, lift_count, etc."""


# ---------------------------------------------------------------------------
# Local
# ---------------------------------------------------------------------------


class LocalIsolationEnforcer(IsolationEnforcer):
    """
    Track isolation in local state. No cross-process side effects.

    Used by Architecture A (running on the ground-station process) and
    Architecture B (one instance per UAV monitor process).
    """

    def __init__(self) -> None:
        self._isolated: set[str] = set()
        self._enforce_count: int = 0
        self._enforce_idempotent: int = 0
        self._lift_count: int = 0

    def enforce(self, announcement: IsolationAnnounce) -> bool:
        if not announcement.target_uav:
            return False
        if announcement.target_uav in self._isolated:
            self._enforce_idempotent += 1
            return True
        self._isolated.add(announcement.target_uav)
        self._enforce_count += 1
        return True

    def lift(self, uav_id: str) -> bool:
        if uav_id not in self._isolated:
            return False
        self._isolated.remove(uav_id)
        self._lift_count += 1
        return True

    def is_isolated(self, uav_id: str) -> bool:
        return uav_id in self._isolated

    def reset(self) -> None:
        self._isolated.clear()
        self._enforce_count = 0
        self._enforce_idempotent = 0
        self._lift_count = 0

    @property
    def isolated_uavs(self) -> frozenset[str]:
        return frozenset(self._isolated)

    @property
    def stats(self) -> dict[str, int]:
        return {
            "enforce_count": self._enforce_count,
            "enforce_idempotent": self._enforce_idempotent,
            "lift_count": self._lift_count,
            "currently_isolated": len(self._isolated),
        }


# ---------------------------------------------------------------------------
# Mesh-announcing
# ---------------------------------------------------------------------------


class MeshAnnouncingIsolationEnforcer(IsolationEnforcer):
    """
    Local-state isolation PLUS a mesh publish on each fresh enforcement.

    Used by Architecture C. Composition over inheritance: holds a
    LocalIsolationEnforcer for state and a MeshBus for propagation.
    """

    def __init__(self, mesh: MeshBus) -> None:
        self._local = LocalIsolationEnforcer()
        self._mesh = mesh
        self._mesh_publish_count: int = 0
        self._mesh_publish_errors: int = 0

    def enforce(self, announcement: IsolationAnnounce) -> bool:
        if not announcement.target_uav:
            return False

        # Do the local marking first. If publish fails, state is still
        # consistent and the post-hoc analyzer can see the discrepancy
        # via mesh_publish_errors > 0.
        was_already_isolated = self._local.is_isolated(announcement.target_uav)
        ok = self._local.enforce(announcement)
        if not ok:
            return False

        # Publish only on the FIRST enforcement, not on idempotent retries.
        # The original announcement event_id stays consistent across peers.
        if not was_already_isolated:
            try:
                self._mesh.publish(announcement)
                self._mesh_publish_count += 1
            except Exception:
                self._mesh_publish_errors += 1
                # Swallow — we keep local state coherent. The error count
                # surfaces the failure to the metrics layer.

        return True

    def lift(self, uav_id: str) -> bool:
        # No mesh announcement on lift — recovery is signalled via
        # RecoveryAck on its own topic.
        return self._local.lift(uav_id)

    def is_isolated(self, uav_id: str) -> bool:
        return self._local.is_isolated(uav_id)

    def reset(self) -> None:
        self._local.reset()
        self._mesh_publish_count = 0
        self._mesh_publish_errors = 0

    @property
    def isolated_uavs(self) -> frozenset[str]:
        return self._local.isolated_uavs

    @property
    def stats(self) -> dict[str, int]:
        s = dict(self._local.stats)
        s["mesh_publish_count"] = self._mesh_publish_count
        s["mesh_publish_errors"] = self._mesh_publish_errors
        return s
