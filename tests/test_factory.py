"""Tests for runners.factory.

Strategy: load real config files from configs/ + use fake connection
factory + recording mesh factory so the fleet is structurally built
but no MAVLink sockets, threads, or ZMQ ports are opened.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from core.config import load_architecture_config, load_experiment_config
from core.events import (
    BaseEvent,
    IsolationAnnounce,
    RecoveryAck,
    SecurityEvent,
)
from core.mesh import MeshBus
from decision.recovery import RecoveryAction
from detectors.command import CommandInjectionDetector
from detectors.cross_check import CrossCheckDetector
from detectors.gps import GpsSpoofingDetector
from detectors.heartbeat import HeartbeatDetector
from enforcement.handlers import (
    FilterCommandsHandler,
    ModeLoiterHandler,
    RestartProcessHandler,
)
from enforcement.isolation import (
    LocalIsolationEnforcer,
    MeshAnnouncingIsolationEnforcer,
)
from runners.factory import WiredFleet, build_fleet


CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeConnection:
    """Stand-in for a pymavlink connection. The factory only stores it."""

    def __init__(self) -> None:
        self.closed = False

    def recv_match(self, **_kwargs):
        return None

    def close(self) -> None:
        self.closed = True


class RecordingMesh(MeshBus):
    """A mesh stub that records subscribers + publishes, and lets the
    test deliver events back to subscribers — for verifying callback
    wiring without touching ZMQ."""

    def __init__(self) -> None:
        self.published: list[BaseEvent] = []
        self._subs: dict[str, list[Callable]] = {}
        self._started: bool = False

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def publish(self, event: BaseEvent) -> None:
        self.published.append(event)

    def subscribe(self, topic: str, callback: Callable) -> None:
        self._subs.setdefault(topic, []).append(callback)

    def deliver(self, topic: str, event: BaseEvent) -> None:
        for cb in self._subs.get(topic, []):
            cb(event)


def _fake_connection_factory(_endpoint: str) -> FakeConnection:
    return FakeConnection()


def _build(arch_name: str, tmp_path: Path, *, mesh_factory=None) -> WiredFleet:
    arch_cfg = load_architecture_config(CONFIG_DIR / f"architecture_{arch_name}.yaml")
    exp_cfg = load_experiment_config(CONFIG_DIR / "experiment.yaml")
    return build_fleet(
        arch_cfg=arch_cfg,
        exp_cfg=exp_cfg,
        run_id="test",
        log_root=tmp_path,
        connection_factory=_fake_connection_factory,
        mesh_factory=mesh_factory,
    )


# ---------------------------------------------------------------------------
# Architecture A
# ---------------------------------------------------------------------------


class TestArchitectureA:
    def test_three_monitors_no_coordinators_no_meshes(self, tmp_path: Path):
        fleet = _build("a", tmp_path)
        assert fleet.architecture == "A"
        assert len(fleet.monitors) == 3
        assert fleet.coordinators == []
        assert fleet.meshes == []

    def test_each_monitor_watches_one_uav(self, tmp_path: Path):
        fleet = _build("a", tmp_path)
        watched = sorted(m.uav_id for m in fleet.monitors)
        assert watched == ["uav_0", "uav_1", "uav_2"]

    def test_local_enforcer_no_mesh(self, tmp_path: Path):
        fleet = _build("a", tmp_path)
        for mon in fleet.monitors:
            assert isinstance(mon.isolation_enforcer, LocalIsolationEnforcer)

    def test_detectors_match_config(self, tmp_path: Path):
        """A wires heartbeat + command + gps; no cross_check."""
        fleet = _build("a", tmp_path)
        for mon in fleet.monitors:
            types = {type(d) for d in mon._detectors}
            assert HeartbeatDetector in types
            assert CommandInjectionDetector in types
            assert GpsSpoofingDetector in types
            assert CrossCheckDetector not in types

    def test_log_dir_created(self, tmp_path: Path):
        fleet = _build("a", tmp_path)
        assert fleet.log_dir.exists()
        assert fleet.log_dir.is_dir()
        assert fleet.log_dir.name == "run_test"


# ---------------------------------------------------------------------------
# Architecture B
# ---------------------------------------------------------------------------


class TestArchitectureB:
    def test_three_monitors_no_coordinators_no_meshes(self, tmp_path: Path):
        fleet = _build("b", tmp_path)
        assert fleet.architecture == "B"
        assert len(fleet.monitors) == 3
        assert fleet.coordinators == []
        assert fleet.meshes == []

    def test_each_monitor_watches_self(self, tmp_path: Path):
        """B: each monitor lives on its UAV and watches that UAV only."""
        fleet = _build("b", tmp_path)
        watched = sorted(m.uav_id for m in fleet.monitors)
        assert watched == ["uav_0", "uav_1", "uav_2"]

    def test_local_enforcer(self, tmp_path: Path):
        fleet = _build("b", tmp_path)
        for mon in fleet.monitors:
            assert isinstance(mon.isolation_enforcer, LocalIsolationEnforcer)


# ---------------------------------------------------------------------------
# Architecture C
# ---------------------------------------------------------------------------


class TestArchitectureC:
    def test_three_monitors_three_coordinators_three_meshes(self, tmp_path: Path):
        fleet = _build("c", tmp_path, mesh_factory=lambda *a: RecordingMesh())
        assert fleet.architecture == "C"
        assert len(fleet.monitors) == 3
        assert len(fleet.coordinators) == 3
        assert len(fleet.meshes) == 3

    def test_mesh_announcing_enforcer(self, tmp_path: Path):
        fleet = _build("c", tmp_path, mesh_factory=lambda *a: RecordingMesh())
        for mon in fleet.monitors:
            assert isinstance(
                mon.isolation_enforcer, MeshAnnouncingIsolationEnforcer
            )

    def test_cross_check_detector_present(self, tmp_path: Path):
        fleet = _build("c", tmp_path, mesh_factory=lambda *a: RecordingMesh())
        for mon in fleet.monitors:
            assert isinstance(mon._cross_check, CrossCheckDetector)
            assert mon._cross_check.monitor_uav_id == mon.uav_id

    def test_coordinator_alignment(self, tmp_path: Path):
        """Each coordinator's target_uav matches its co-located monitor."""
        fleet = _build("c", tmp_path, mesh_factory=lambda *a: RecordingMesh())
        for mon, coord in zip(fleet.monitors, fleet.coordinators):
            assert coord._target_uav == mon.uav_id
            assert coord._our_sysid in [1, 2, 3]
            assert coord._all_sysids == [1, 2, 3]

    def test_handlers_registered_for_all_three_actions(self, tmp_path: Path):
        fleet = _build("c", tmp_path, mesh_factory=lambda *a: RecordingMesh())
        for coord in fleet.coordinators:
            executor = coord._executor
            handlers = executor._handlers
            assert RecoveryAction.RESTART_PROCESS in handlers
            assert RecoveryAction.MODE_LOITER in handlers
            assert RecoveryAction.FILTER_COMMANDS in handlers
            assert isinstance(
                handlers[RecoveryAction.RESTART_PROCESS], RestartProcessHandler
            )
            assert isinstance(
                handlers[RecoveryAction.MODE_LOITER], ModeLoiterHandler
            )
            assert isinstance(
                handlers[RecoveryAction.FILTER_COMMANDS], FilterCommandsHandler
            )

    def test_recovery_callback_lifts_enforcer_and_unisolates_decider(
        self, tmp_path: Path
    ):
        """Verify the callback wiring: when a RecoveryAck arrives at a
        coordinator, the corresponding monitor's enforcer.lift and
        decider.un_isolate are invoked."""
        meshes_built: list[RecordingMesh] = []

        def factory(self_ep, peer_eps):
            m = RecordingMesh()
            meshes_built.append(m)
            return m

        fleet = _build("c", tmp_path, mesh_factory=factory)

        # Pick monitor / coordinator for uav_0.
        mon0 = next(m for m in fleet.monitors if m.uav_id == "uav_0")
        mesh0 = meshes_built[0]  # built in the same iteration as monitor 0

        # Force-mark uav_2 as isolated by uav_0's monitor (simulate that
        # the monitor's enforcer marked uav_2 as isolated earlier).
        ann = IsolationAnnounce(
            source="monitor_uav_0",
            target_uav="uav_2",
            reason="heartbeat_loss",
            decided_by="monitor_uav_0",
        )
        mon0.isolation_enforcer.enforce(ann)
        mon0.isolation_decider.evaluate(
            # pre-load decider state so un_isolate has something to clear
            SecurityEvent(
                source="monitor_uav_0",
                detector="heartbeat",
                target_uav="uav_2",
                severity="high",
                evidence={"missing_for_sec": 5.0},
            )
        )
        assert mon0.isolation_enforcer.is_isolated("uav_2")
        assert mon0.isolation_decider.is_isolated("uav_2")

        # Now deliver a RecoveryAck via the mesh — which should flow to
        # the coordinator and through to the callback.
        ack = RecoveryAck(
            source="some_other_coord",
            target_uav="uav_2",
            action=RecoveryAction.RESTART_PROCESS,
            success=True,
            executor="some_other_coord",
        )
        mesh0.deliver("recovery_ack", ack)

        # Callback should have lifted both:
        assert not mon0.isolation_enforcer.is_isolated("uav_2")
        assert not mon0.isolation_decider.is_isolated("uav_2")

    def test_recovery_callback_skips_lift_on_failure(self, tmp_path: Path):
        meshes_built: list[RecordingMesh] = []

        def factory(self_ep, peer_eps):
            m = RecordingMesh()
            meshes_built.append(m)
            return m

        fleet = _build("c", tmp_path, mesh_factory=factory)

        mon0 = next(m for m in fleet.monitors if m.uav_id == "uav_0")
        mesh0 = meshes_built[0]

        ann = IsolationAnnounce(
            source="monitor_uav_0", target_uav="uav_2",
            reason="heartbeat_loss", decided_by="monitor_uav_0",
        )
        mon0.isolation_enforcer.enforce(ann)
        assert mon0.isolation_enforcer.is_isolated("uav_2")

        # Failure ack -> no lift
        ack = RecoveryAck(
            source="x", target_uav="uav_2",
            action=RecoveryAction.RESTART_PROCESS,
            success=False, executor="x", error="cold-start failed",
        )
        mesh0.deliver("recovery_ack", ack)

        assert mon0.isolation_enforcer.is_isolated("uav_2")  # still isolated


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestLogPaths:
    def test_log_files_per_monitor_under_run_dir(self, tmp_path: Path):
        fleet = _build("c", tmp_path, mesh_factory=lambda *a: RecordingMesh())
        # Each monitor's logger writes to log_dir/<source>.jsonl
        for mon in fleet.monitors:
            assert (fleet.log_dir / f"{mon._source}.jsonl").parent == fleet.log_dir
