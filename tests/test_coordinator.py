"""Tests for runners.coordinator."""

from __future__ import annotations

import socket as _socket
import time
from typing import Callable

import pytest

from core.events import (
    IsolationAnnounce,
    PeerPositionAnnounce,
    RecoveryAck,
    RecoveryRequest,
)
from core.mesh import MeshBus, ZmqMesh
from decision.recovery import RecoveryAction, RecoveryDecider
from enforcement.recovery import ActionHandler, RecoveryExecutor
from runners.coordinator import Coordinator


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeMesh(MeshBus):
    """Records publishes; lets the test fire callbacks directly."""

    def __init__(self) -> None:
        self.published: list = []
        self._subs: dict[str, list[Callable]] = {}

    def start(self) -> None: ...
    def stop(self) -> None: ...

    def publish(self, event) -> None:
        self.published.append(event)

    def subscribe(self, topic: str, callback: Callable) -> None:
        self._subs.setdefault(topic, []).append(callback)

    def deliver(self, topic: str, event) -> None:
        for cb in self._subs.get(topic, []):
            cb(event)


class _AlwaysOkHandler(ActionHandler):
    async def execute(self, request):
        return True, None


def _isolation(target_uav: str = "uav_2", reason: str = "heartbeat_loss") -> IsolationAnnounce:
    return IsolationAnnounce(
        source="monitor_uav_0",
        target_uav=target_uav,
        reason=reason,
        decided_by="monitor_uav_0",
    )


def _peer_pos(uav_id: str, ts: float = 0.0) -> PeerPositionAnnounce:
    return PeerPositionAnnounce(
        source=f"monitor_{uav_id}",
        uav_id=uav_id,
        lat=47.4,
        lon=8.5,
        alt=500.0,
        sample_timestamp=ts,
    )


def _build_coord(
    *,
    our_sysid: int,
    target_uav: str = "uav_0",
    enabled: bool = True,
    handlers: dict | None = None,
    on_recovery_completed=None,
) -> tuple[Coordinator, FakeMesh, RecoveryDecider, RecoveryExecutor]:
    mesh = FakeMesh()
    decider = RecoveryDecider(source="coordinator", enabled=enabled)
    executor = RecoveryExecutor(
        source="enforcer",
        enabled=enabled,
        handlers=handlers if handlers is not None else {
            RecoveryAction.RESTART_PROCESS: _AlwaysOkHandler(),
            RecoveryAction.MODE_LOITER: _AlwaysOkHandler(),
            RecoveryAction.FILTER_COMMANDS: _AlwaysOkHandler(),
        },
    )
    coord = Coordinator(
        source="coordinator",
        our_sysid=our_sysid,
        all_sysids=[1, 2, 3],
        sysid_to_uav={1: "uav_0", 2: "uav_1", 3: "uav_2"},
        target_uav=target_uav,
        mesh=mesh,
        recovery_decider=decider,
        recovery_executor=executor,
        liveness_timeout_sec=1.0,
        on_recovery_completed=on_recovery_completed,
    )
    coord.start()
    return coord, mesh, decider, executor


def _free_ports(n: int) -> list[int]:
    socks = []
    ports = []
    try:
        for _ in range(n):
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s.bind(("127.0.0.1", 0))
            ports.append(s.getsockname()[1])
            socks.append(s)
    finally:
        for s in socks:
            s.close()
    return ports


def _wait_until(predicate, timeout: float = 3.0, poll: float = 0.02) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(poll)
    return predicate()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_our_sysid_must_be_in_all(self):
        with pytest.raises(ValueError, match="our_sysid"):
            Coordinator(
                source="c", our_sysid=4, all_sysids=[1, 2, 3],
                sysid_to_uav={1: "uav_0", 2: "uav_1", 3: "uav_2"},
                target_uav="uav_0",
                mesh=FakeMesh(),
                recovery_decider=RecoveryDecider(source="c", enabled=True),
                recovery_executor=RecoveryExecutor(source="e", enabled=True, handlers={}),
            )

    def test_liveness_timeout_must_be_positive(self):
        with pytest.raises(ValueError, match="liveness_timeout_sec"):
            Coordinator(
                source="c", our_sysid=1, all_sysids=[1, 2, 3],
                sysid_to_uav={1: "uav_0", 2: "uav_1", 3: "uav_2"},
                target_uav="uav_0",
                mesh=FakeMesh(),
                recovery_decider=RecoveryDecider(source="c", enabled=True),
                recovery_executor=RecoveryExecutor(source="e", enabled=True, handlers={}),
                liveness_timeout_sec=0,
            )

    def test_sysid_to_uav_must_cover_all_sysids(self):
        with pytest.raises(ValueError, match="sysids without a uav mapping"):
            Coordinator(
                source="c", our_sysid=1, all_sysids=[1, 2, 3],
                sysid_to_uav={1: "uav_0", 2: "uav_1"},  # missing 3
                target_uav="uav_0",
                mesh=FakeMesh(),
                recovery_decider=RecoveryDecider(source="c", enabled=True),
                recovery_executor=RecoveryExecutor(source="e", enabled=True, handlers={}),
            )


# ---------------------------------------------------------------------------
# Election
# ---------------------------------------------------------------------------


class TestElection:
    def test_lowest_sysid_is_coordinator_at_startup(self):
        c1, *_ = _build_coord(our_sysid=1)
        c2, *_ = _build_coord(our_sysid=2)
        c3, *_ = _build_coord(our_sysid=3)
        # No peer_position seen yet -> only "self" alive.
        # But all_sysids = [1,2,3]. Without other heartbeats, candidates
        # = [self_sysid] for each — all return True when called individually.
        assert c1.is_coordinator is True
        # c2 and c3 considered alone (no peer announcements) — each
        # thinks it's the only one alive, so each is the coordinator.
        # This is correct: in a partitioned mesh each side acts as its
        # own coordinator. Once peer_positions arrive the elected one
        # converges.
        assert c2.is_coordinator is True
        assert c3.is_coordinator is True

    def test_self_loses_when_lower_peer_seen(self):
        c2, mesh2, *_ = _build_coord(our_sysid=2)
        # Deliver a peer_position from sysid 1 (uav_0)
        mesh2.deliver("peer_position", _peer_pos("uav_0"))
        # Now c2 should know peer 1 is alive — and 1 < 2 — so c2 is NOT coordinator.
        assert c2.is_coordinator is False

    def test_self_takes_over_after_liveness_timeout(self):
        c2, mesh2, *_ = _build_coord(our_sysid=2)
        mesh2.deliver("peer_position", _peer_pos("uav_0"))
        assert c2.is_coordinator is False
        # Wait beyond liveness_timeout_sec=1.0
        time.sleep(1.1)
        assert c2.is_coordinator is True

    def test_uav_2_is_never_coordinator_when_uav_0_alive(self):
        c3, mesh3, *_ = _build_coord(our_sysid=3)
        mesh3.deliver("peer_position", _peer_pos("uav_0"))
        mesh3.deliver("peer_position", _peer_pos("uav_1"))
        assert c3.is_coordinator is False

    def test_alive_sysids_includes_self(self):
        c, mesh, *_ = _build_coord(our_sysid=2)
        assert 2 in c.alive_sysids
        mesh.deliver("peer_position", _peer_pos("uav_0"))
        assert {1, 2}.issubset(c.alive_sysids)

# ---------------------------------------------------------------------------
# Isolation-aware election (added with isolation-set tracking fix)
# ---------------------------------------------------------------------------


class TestIsolationAwareElection:
    """An isolated peer is excluded from the alive set used for
    coordinator election. This includes self — an isolated UAV
    relinquishes the coordinator role to the next-lowest non-isolated
    peer."""

    def test_isolated_peer_drops_from_alive_set(self):
        c2, mesh2, *_ = _build_coord(our_sysid=2)
        # sysid 1 alive in mesh -> c2 NOT coordinator (1 < 2)
        mesh2.deliver("peer_position", _peer_pos("uav_0"))
        assert c2.is_coordinator is False
        # Announce isolation for uav_0
        mesh2.deliver("isolation", _isolation(target_uav="uav_0"))
        assert 1 in c2.isolated_sysids
        # Now c2 is the lowest non-isolated alive peer.
        assert c2.is_coordinator is True
        assert 1 not in c2.alive_sysids

    def test_self_isolation_loses_coordinator_status(self):
        c1, mesh1, *_ = _build_coord(our_sysid=1)
        assert c1.is_coordinator is True
        # Our own UAV isolated -> we surrender the coordinator role.
        mesh1.deliver("isolation", _isolation(target_uav="uav_0"))
        assert 1 in c1.isolated_sysids
        assert c1.is_coordinator is False

    def test_successful_recovery_ack_lifts_isolation(self):
        c2, mesh2, *_ = _build_coord(our_sysid=2)
        mesh2.deliver("peer_position", _peer_pos("uav_0"))
        mesh2.deliver("isolation", _isolation(target_uav="uav_0"))
        assert 1 in c2.isolated_sysids
        ack = RecoveryAck(
            source="x", target_uav="uav_0",
            action=RecoveryAction.RESTART_PROCESS,
            success=True, executor="x",
        )
        mesh2.deliver("recovery_ack", ack)
        assert 1 not in c2.isolated_sysids

    def test_failed_recovery_ack_keeps_isolation(self):
        c2, mesh2, *_ = _build_coord(our_sysid=2)
        mesh2.deliver("peer_position", _peer_pos("uav_0"))
        mesh2.deliver("isolation", _isolation(target_uav="uav_0"))
        assert 1 in c2.isolated_sysids
        ack = RecoveryAck(
            source="x", target_uav="uav_0",
            action=RecoveryAction.RESTART_PROCESS,
            success=False, executor="x", error="oops",
        )
        mesh2.deliver("recovery_ack", ack)
        assert 1 in c2.isolated_sysids

    def test_duplicate_isolation_announces_idempotent(self):
        c2, mesh2, *_ = _build_coord(our_sysid=2)
        mesh2.deliver("isolation", _isolation(target_uav="uav_0"))
        mesh2.deliver("isolation", _isolation(target_uav="uav_0"))
        assert c2.isolated_sysids == frozenset({1})

    def test_isolated_sysids_empty_initially(self):
        c2, *_ = _build_coord(our_sysid=2)
        assert c2.isolated_sysids == frozenset()
        
# ---------------------------------------------------------------------------
# Isolation -> RecoveryRequest issuance
# ---------------------------------------------------------------------------


class TestIsolationToRecoveryRequest:
    def test_coordinator_emits_recovery_request(self):
        c, mesh, *_ = _build_coord(our_sysid=1, target_uav="uav_0")
        ann = _isolation(target_uav="uav_2", reason="heartbeat_loss")
        mesh.deliver("isolation", ann)

        # Should have published a RecoveryRequest
        reqs = [e for e in mesh.published if isinstance(e, RecoveryRequest)]
        assert len(reqs) == 1
        assert reqs[0].target_uav == "uav_2"
        assert reqs[0].action == RecoveryAction.RESTART_PROCESS
        assert reqs[0].caused_by == ann.event_id
        assert c.stats["recovery_requests_issued"] == 1

    def test_non_coordinator_ignores_isolation(self):
        c, mesh, *_ = _build_coord(our_sysid=2, target_uav="uav_1")
        # Establish that sysid 1 is alive -> we are not coordinator.
        mesh.deliver("peer_position", _peer_pos("uav_0"))
        assert c.is_coordinator is False

        mesh.deliver("isolation", _isolation(target_uav="uav_2"))

        reqs = [e for e in mesh.published if isinstance(e, RecoveryRequest)]
        assert reqs == []
        assert c.stats["isolations_seen"] == 1
        assert c.stats["skipped_not_coordinator"] == 1

    def test_disabled_decider_no_request(self):
        c, mesh, *_ = _build_coord(our_sysid=1, target_uav="uav_0", enabled=False)
        mesh.deliver("isolation", _isolation(target_uav="uav_2"))
        assert mesh.published == []
        assert c.stats["recovery_requests_issued"] == 0

    def test_decider_dedup(self):
        c, mesh, *_ = _build_coord(our_sysid=1, target_uav="uav_0")
        mesh.deliver("isolation", _isolation(target_uav="uav_2"))
        mesh.deliver("isolation", _isolation(target_uav="uav_2"))  # second
        reqs = [e for e in mesh.published if isinstance(e, RecoveryRequest)]
        assert len(reqs) == 1


# ---------------------------------------------------------------------------
# RecoveryRequest -> execution -> RecoveryAck
# ---------------------------------------------------------------------------


class TestRecoveryRequestExecution:
    def test_target_match_executes_and_acks_success(self):
        c, mesh, *_ = _build_coord(our_sysid=2, target_uav="uav_1")
        req = RecoveryRequest(
            source="other_coord",
            target_uav="uav_1",
            action=RecoveryAction.MODE_LOITER,
            requester="other_coord",
        )
        mesh.deliver("recovery_req", req)

        acks = [e for e in mesh.published if isinstance(e, RecoveryAck)]
        assert len(acks) == 1
        assert acks[0].target_uav == "uav_1"
        assert acks[0].action == RecoveryAction.MODE_LOITER
        assert acks[0].success is True
        assert acks[0].error is None
        assert acks[0].caused_by == req.event_id
        assert c.stats["recovery_requests_executed"] == 1

    def test_target_mismatch_skipped(self):
        c, mesh, *_ = _build_coord(our_sysid=1, target_uav="uav_0")
        # Request targets uav_2; our target is uav_0, so we don't execute.
        req = RecoveryRequest(
            source="x", target_uav="uav_2",
            action=RecoveryAction.RESTART_PROCESS, requester="x",
        )
        mesh.deliver("recovery_req", req)

        acks = [e for e in mesh.published if isinstance(e, RecoveryAck)]
        assert acks == []
        assert c.stats["skipped_not_target"] == 1
        assert c.stats["recovery_requests_executed"] == 0

    def test_handler_failure_emits_failure_ack(self):
        class FailingHandler(ActionHandler):
            async def execute(self, request):
                return False, "no PX4 process"

        handlers = {RecoveryAction.RESTART_PROCESS: FailingHandler()}
        c, mesh, *_ = _build_coord(
            our_sysid=2, target_uav="uav_1", handlers=handlers
        )
        req = RecoveryRequest(
            source="x", target_uav="uav_1",
            action=RecoveryAction.RESTART_PROCESS, requester="x",
        )
        mesh.deliver("recovery_req", req)

        acks = [e for e in mesh.published if isinstance(e, RecoveryAck)]
        assert len(acks) == 1
        assert acks[0].success is False
        assert acks[0].error == "no PX4 process"


# ---------------------------------------------------------------------------
# RecoveryAck reception
# ---------------------------------------------------------------------------


class TestRecoveryAckReception:
    def test_ack_calls_decider_mark_recovered(self):
        c, mesh, decider, _ = _build_coord(our_sysid=1, target_uav="uav_0")
        # Pre-populate decider with a request for uav_2
        mesh.deliver("isolation", _isolation(target_uav="uav_2"))
        assert decider.is_recovery_requested("uav_2")

        # Ack arrives
        ack = RecoveryAck(
            source="x", target_uav="uav_2",
            action=RecoveryAction.RESTART_PROCESS,
            success=True, executor="x",
        )
        mesh.deliver("recovery_ack", ack)

        assert not decider.is_recovery_requested("uav_2")
        assert c.stats["recovery_acks_received"] == 1

    def test_callback_invoked_with_uav_and_success(self):
        seen: list[tuple[str, bool]] = []

        def cb(uav_id: str, success: bool) -> None:
            seen.append((uav_id, success))

        c, mesh, *_ = _build_coord(
            our_sysid=1, target_uav="uav_0", on_recovery_completed=cb
        )
        ack_ok = RecoveryAck(
            source="x", target_uav="uav_2", action="restart_process",
            success=True, executor="x",
        )
        ack_fail = RecoveryAck(
            source="x", target_uav="uav_1", action="mode_loiter",
            success=False, executor="x", error="oops",
        )
        mesh.deliver("recovery_ack", ack_ok)
        mesh.deliver("recovery_ack", ack_fail)

        assert seen == [("uav_2", True), ("uav_1", False)]

    def test_buggy_callback_does_not_kill_coordinator(self):
        def boom(uav_id, success):
            raise RuntimeError("callback bug")

        c, mesh, *_ = _build_coord(
            our_sysid=1, target_uav="uav_0", on_recovery_completed=boom
        )
        ack = RecoveryAck(
            source="x", target_uav="uav_2", action="restart_process",
            success=True, executor="x",
        )
        # Must not raise
        mesh.deliver("recovery_ack", ack)
        assert c.stats["handler_errors"] >= 1
        assert c.stats["recovery_acks_received"] == 1


# ---------------------------------------------------------------------------
# Two-coordinator integration over real ZmqMesh
# ---------------------------------------------------------------------------


class TestTwoCoordinatorIntegration:
    def test_full_recovery_cycle_across_real_mesh(self):
        """
        Two UAVs, two coordinators, real ZmqMesh.
        sysid 1 (uav_0) is the elected coordinator (lowest).
        Some monitor publishes IsolationAnnounce for uav_1.
        Coordinator on uav_0 issues RecoveryRequest.
        Coordinator on uav_1 (target=uav_1) receives, executes,
        publishes RecoveryAck. Both coordinators receive the ack.
        """
        port_0, port_1 = _free_ports(2)
        ep_0 = f"tcp://127.0.0.1:{port_0}"
        ep_1 = f"tcp://127.0.0.1:{port_1}"

        mesh_0 = ZmqMesh(self_endpoint=ep_0, peer_endpoints=[ep_1])
        mesh_1 = ZmqMesh(self_endpoint=ep_1, peer_endpoints=[ep_0])

        decider_0 = RecoveryDecider(source="coord_uav_0", enabled=True)
        decider_1 = RecoveryDecider(source="coord_uav_1", enabled=True)
        executor_0 = RecoveryExecutor(
            source="enforcer_uav_0", enabled=True,
            handlers={RecoveryAction.RESTART_PROCESS: _AlwaysOkHandler()},
        )
        executor_1 = RecoveryExecutor(
            source="enforcer_uav_1", enabled=True,
            handlers={RecoveryAction.RESTART_PROCESS: _AlwaysOkHandler()},
        )

        sysid_to_uav = {1: "uav_0", 2: "uav_1"}

        c0 = Coordinator(
            source="coord_uav_0", our_sysid=1, all_sysids=[1, 2],
            sysid_to_uav=sysid_to_uav, target_uav="uav_0",
            mesh=mesh_0, recovery_decider=decider_0,
            recovery_executor=executor_0,
        )
        c1 = Coordinator(
            source="coord_uav_1", our_sysid=2, all_sysids=[1, 2],
            sysid_to_uav=sysid_to_uav, target_uav="uav_1",
            mesh=mesh_1, recovery_decider=decider_1,
            recovery_executor=executor_1,
        )

        mesh_0.start()
        mesh_1.start()
        c0.start()
        c1.start()
        try:
            # Some monitor publishes IsolationAnnounce for uav_1.
            # Use mesh_1 to publish (as if coming from monitor_uav_1).
            ann = IsolationAnnounce(
                source="monitor_uav_1", target_uav="uav_1",
                reason="heartbeat_loss", decided_by="monitor_uav_1",
            )
            mesh_1.publish(ann)

            # c0 should receive isolation (it's the coordinator) and
            # publish RecoveryRequest. c1 should receive that and
            # execute, publishing RecoveryAck. Both should see the ack.
            assert _wait_until(
                lambda: c0.stats["recovery_requests_issued"] == 1, timeout=3.0
            )
            assert _wait_until(
                lambda: c1.stats["recovery_requests_executed"] == 1, timeout=3.0
            )
            # c0 receives the ack (c1's own ack arrives back via its
            # own publish, but c1 doesn't loopback its own publishes —
            # so only c0 sees this particular ack. That's the realistic
            # scenario where the coordinator that issued the request
            # learns of completion).
            assert _wait_until(
                lambda: c0.stats["recovery_acks_received"] >= 1, timeout=3.0
            )
        finally:
            c0.stop()
            c1.stop()
            mesh_0.stop()
            mesh_1.stop()
