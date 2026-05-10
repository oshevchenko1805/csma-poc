"""Tests for enforcement.isolation."""

from __future__ import annotations

from typing import Callable

import pytest

from core.events import BaseEvent, IsolationAnnounce
from core.mesh import MeshBus
from enforcement.isolation import (
    IsolationEnforcer,
    LocalIsolationEnforcer,
    MeshAnnouncingIsolationEnforcer,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeMesh(MeshBus):
    """Records publish() calls; raises on demand to simulate failure."""

    def __init__(self, raise_on_publish: bool = False) -> None:
        self.published: list[BaseEvent] = []
        self.raise_on_publish = raise_on_publish

    def start(self) -> None: ...
    def stop(self) -> None: ...

    def publish(self, event: BaseEvent) -> None:
        if self.raise_on_publish:
            raise RuntimeError("simulated mesh failure")
        self.published.append(event)

    def subscribe(self, topic: str, callback: Callable) -> None: ...


def _announcement(
    *, target_uav: str = "uav_2", reason: str = "heartbeat_loss"
) -> IsolationAnnounce:
    return IsolationAnnounce(
        source="monitor_uav_0",
        target_uav=target_uav,
        reason=reason,
        decided_by="monitor_uav_0",
    )


# ---------------------------------------------------------------------------
# Local
# ---------------------------------------------------------------------------


class TestLocalIsolationEnforcer:
    def test_enforce_marks_isolated(self):
        e = LocalIsolationEnforcer()
        assert e.enforce(_announcement(target_uav="uav_2")) is True
        assert e.is_isolated("uav_2")
        assert "uav_2" in e.isolated_uavs

    def test_enforce_empty_target_rejected(self):
        e = LocalIsolationEnforcer()
        ann = IsolationAnnounce(
            source="m", target_uav="", reason="x", decided_by="m"
        )
        assert e.enforce(ann) is False
        assert e.isolated_uavs == frozenset()

    def test_enforce_idempotent(self):
        """Second enforce on same UAV: True, but no double-counting."""
        e = LocalIsolationEnforcer()
        e.enforce(_announcement(target_uav="uav_2"))
        result = e.enforce(_announcement(target_uav="uav_2"))
        assert result is True
        assert e.stats["enforce_count"] == 1
        assert e.stats["enforce_idempotent"] == 1

    def test_lift_removes_isolation(self):
        e = LocalIsolationEnforcer()
        e.enforce(_announcement(target_uav="uav_2"))
        assert e.lift("uav_2") is True
        assert not e.is_isolated("uav_2")
        assert e.stats["lift_count"] == 1

    def test_lift_unknown_returns_false(self):
        e = LocalIsolationEnforcer()
        assert e.lift("never_isolated") is False
        assert e.stats["lift_count"] == 0

    def test_independent_per_uav(self):
        e = LocalIsolationEnforcer()
        e.enforce(_announcement(target_uav="uav_1"))
        e.enforce(_announcement(target_uav="uav_2"))
        assert e.isolated_uavs == frozenset({"uav_1", "uav_2"})
        assert e.stats["enforce_count"] == 2

        e.lift("uav_1")
        assert e.is_isolated("uav_2")
        assert not e.is_isolated("uav_1")

    def test_reset_clears_all(self):
        e = LocalIsolationEnforcer()
        e.enforce(_announcement(target_uav="uav_1"))
        e.enforce(_announcement(target_uav="uav_2"))
        e.lift("uav_1")
        e.reset()
        assert e.isolated_uavs == frozenset()
        assert e.stats == {
            "enforce_count": 0,
            "enforce_idempotent": 0,
            "lift_count": 0,
            "currently_isolated": 0,
        }

    def test_stats_currently_isolated(self):
        e = LocalIsolationEnforcer()
        assert e.stats["currently_isolated"] == 0
        e.enforce(_announcement(target_uav="uav_1"))
        e.enforce(_announcement(target_uav="uav_2"))
        assert e.stats["currently_isolated"] == 2
        e.lift("uav_1")
        assert e.stats["currently_isolated"] == 1

    def test_implements_interface(self):
        e = LocalIsolationEnforcer()
        assert isinstance(e, IsolationEnforcer)


# ---------------------------------------------------------------------------
# Mesh-announcing
# ---------------------------------------------------------------------------


class TestMeshAnnouncingIsolationEnforcer:
    def test_enforce_marks_and_publishes(self):
        mesh = FakeMesh()
        e = MeshAnnouncingIsolationEnforcer(mesh=mesh)

        ann = _announcement(target_uav="uav_2")
        assert e.enforce(ann) is True

        assert e.is_isolated("uav_2")
        # Exactly one publish, with the same event_id (peers must see the
        # same announcement, not a different one).
        assert len(mesh.published) == 1
        assert mesh.published[0].event_id == ann.event_id

    def test_idempotent_does_not_republish(self):
        mesh = FakeMesh()
        e = MeshAnnouncingIsolationEnforcer(mesh=mesh)

        e.enforce(_announcement(target_uav="uav_2"))
        e.enforce(_announcement(target_uav="uav_2"))  # second call
        e.enforce(_announcement(target_uav="uav_2"))  # third call

        assert len(mesh.published) == 1
        assert e.stats["mesh_publish_count"] == 1
        assert e.stats["enforce_idempotent"] == 2

    def test_publish_failure_keeps_local_state_consistent(self):
        """If mesh.publish raises, local isolation still applies and the
        error is counted."""
        mesh = FakeMesh(raise_on_publish=True)
        e = MeshAnnouncingIsolationEnforcer(mesh=mesh)

        result = e.enforce(_announcement(target_uav="uav_2"))
        assert result is True  # action carried out from caller's POV
        assert e.is_isolated("uav_2")  # local state coherent
        assert mesh.published == []
        assert e.stats["mesh_publish_count"] == 0
        assert e.stats["mesh_publish_errors"] == 1

    def test_lift_does_not_publish(self):
        """Lifting is a local operation — no mesh announcement.
        Recovery is signalled via RecoveryAck on its own topic."""
        mesh = FakeMesh()
        e = MeshAnnouncingIsolationEnforcer(mesh=mesh)
        e.enforce(_announcement(target_uav="uav_2"))
        assert len(mesh.published) == 1

        assert e.lift("uav_2") is True
        assert len(mesh.published) == 1  # unchanged

    def test_independent_per_uav(self):
        mesh = FakeMesh()
        e = MeshAnnouncingIsolationEnforcer(mesh=mesh)
        e.enforce(_announcement(target_uav="uav_1"))
        e.enforce(_announcement(target_uav="uav_2"))
        assert e.isolated_uavs == frozenset({"uav_1", "uav_2"})
        assert len(mesh.published) == 2

    def test_reset_clears_local_and_mesh_counters(self):
        mesh = FakeMesh()
        e = MeshAnnouncingIsolationEnforcer(mesh=mesh)
        e.enforce(_announcement(target_uav="uav_2"))
        e.reset()
        assert e.isolated_uavs == frozenset()
        s = e.stats
        assert s["mesh_publish_count"] == 0
        assert s["mesh_publish_errors"] == 0
        assert s["enforce_count"] == 0

    def test_implements_interface(self):
        e = MeshAnnouncingIsolationEnforcer(mesh=FakeMesh())
        assert isinstance(e, IsolationEnforcer)

    def test_empty_target_rejected_no_publish(self):
        mesh = FakeMesh()
        e = MeshAnnouncingIsolationEnforcer(mesh=mesh)
        ann = IsolationAnnounce(
            source="m", target_uav="", reason="x", decided_by="m"
        )
        assert e.enforce(ann) is False
        assert mesh.published == []


# ---------------------------------------------------------------------------
# Behavioural equivalence between Local and MeshAnnouncing for state ops
# ---------------------------------------------------------------------------


class TestBehavioralEquivalence:
    """The two enforcers must agree on local-state semantics."""

    def test_both_track_same_state_for_same_inputs(self):
        local = LocalIsolationEnforcer()
        mesh_enf = MeshAnnouncingIsolationEnforcer(mesh=FakeMesh())

        for uav_id in ("uav_1", "uav_2", "uav_2"):  # second uav_2 idempotent
            ann = _announcement(target_uav=uav_id)
            local.enforce(ann)
            mesh_enf.enforce(ann)

        assert local.isolated_uavs == mesh_enf.isolated_uavs

        for uav_id in ("uav_1", "never_seen"):
            assert local.lift(uav_id) == mesh_enf.lift(uav_id)

        assert local.isolated_uavs == mesh_enf.isolated_uavs
