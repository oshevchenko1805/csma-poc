"""
Factory: configs -> wired fleet of components.

Reads an ArchitectureConfig + ExperimentConfig and produces a
WiredFleet — a structured object holding all of the Monitors,
Coordinators, MeshBus instances, and recovery handlers needed to run
the configured architecture against the configured experiment.

This module has NO side effects beyond object construction. It does
not start threads, open sockets, or spawn processes. Lifecycle is the
caller's responsibility (the experiment runner in 8.6b).

Dependency injection points
---------------------------
- connection_factory: builds a pymavlink connection given a telemetry
  endpoint. Default: real pymavlink. Tests inject lambdas that return
  a FakeConnection so the factory's structural correctness can be
  verified without bringing up live MAVLink.
- mesh_factory: builds a MeshBus given (self_endpoint, peer_endpoints).
  Default: ZmqMesh for C, NoOpMesh for A/B. Tests can override.
- process_runner: ProcessRunner used by RestartProcessHandler
  (Architecture C only). Default: a fresh DefaultProcessRunner per
  handler. Pass an ExternalAwareProcessRunner when PX4 instances were
  launched out-of-band (live PoC pipeline via scripts/launch_px4.sh).

PX4 SITL defaults
-----------------
The RestartProcessHandler (Architecture C only) needs a ProcessSpec
per UAV — the command + env + cwd to relaunch a PX4 instance. We
derive these from sysid: instance = sysid - 1, with poses spaced 2 m
apart on the X axis. The PX4 path defaults to ~/PX4-Autopilot,
overridable via px4_path.

If your local SITL build lives elsewhere or uses different env vars
(e.g. ROS_DOMAIN_ID, GZ_PARTITION), pass a custom px4_path or, for
deeper customisation, build the WiredFleet manually.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from core.config import ArchitectureConfig, ExperimentConfig
from core.events import IsolationAnnounce  # noqa: F401  (used in callbacks)
from core.mesh import MeshBus, NoOpMesh, ZmqMesh
from decision.isolation import IsolationDecider
from decision.recovery import RecoveryAction, RecoveryDecider
from detectors.command import CommandInjectionDetector
from detectors.cross_check import CrossCheckDetector
from detectors.gps import GpsSpoofingDetector
from detectors.heartbeat import HeartbeatDetector
from enforcement.handlers import (
    FilterCommandsHandler,
    ModeLoiterHandler,
    ProcessRunner,
    ProcessSpec,
    RestartProcessHandler,
)
from enforcement.isolation import (
    IsolationEnforcer,
    LocalIsolationEnforcer,
    MeshAnnouncingIsolationEnforcer,
)
from enforcement.recovery import RecoveryExecutor
from runners.coordinator import Coordinator
from runners.monitor import Monitor


# Type aliases for the DI seams.
ConnectionFactory = Callable[[str], object]
"""(endpoint) -> pymavlink-style connection. Default: real pymavlink."""

MeshFactory = Callable[[str, list[str]], MeshBus]
"""(self_endpoint, peer_endpoints) -> MeshBus."""


# ---------------------------------------------------------------------------
# Output struct
# ---------------------------------------------------------------------------


@dataclass
class WiredFleet:
    """All components needed to run one architecture against one mission."""

    architecture: str
    monitors: list[Monitor]
    coordinators: list[Coordinator]
    meshes: list[MeshBus]
    log_dir: Path
    # Cleanup handles (Architecture C only).
    filter_handlers: list[FilterCommandsHandler] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Detector factory
# ---------------------------------------------------------------------------


def _build_detectors(
    detector_names: list[str],
    target_uav: str,
    source: str,
) -> list:
    """Instantiate the requested detectors for a given watched UAV.

    cross_check is intentionally NOT in this list — it has a different
    contract (consumes PeerPositionAnnounce, not TelemetryEvent) and is
    wired separately on the monitor.
    """
    out = []
    for name in detector_names:
        if name == "heartbeat":
            out.append(HeartbeatDetector(target_uav=target_uav, source=source))
        elif name == "command":
            out.append(
                CommandInjectionDetector(target_uav=target_uav, source=source)
            )
        elif name == "gps":
            out.append(
                GpsSpoofingDetector(target_uav=target_uav, source=source)
            )
        elif name == "cross_check":
            continue  # handled separately
        else:
            raise ValueError(f"unknown detector {name!r}")
    return out


# ---------------------------------------------------------------------------
# PX4 SITL defaults for RestartProcessHandler (Architecture C)
# ---------------------------------------------------------------------------


def _default_px4_pose(instance: int) -> str:
    """Spaced 2 m apart on +X axis, matching the original PoC layout."""
    return f"{instance * 2},0,0,0,0,0"


def _default_process_spec(
    *, uav_id: str, sysid: int, px4_path: Path
) -> ProcessSpec:
    instance = sysid - 1
    binary = px4_path / "build" / "px4_sitl_default" / "bin" / "px4"
    env = {
        "PX4_SYS_AUTOSTART": "4001",
        "PX4_GZ_MODEL": "x500",
        "PX4_GZ_MODEL_POSE": _default_px4_pose(instance),
        # Inherit PATH and HOME so PX4 can find its build artifacts.
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }
    return ProcessSpec(
        command=(str(binary), "-i", str(instance)),
        env=env,
        cwd=px4_path,
        start_timeout_sec=8.0,
    )


def _default_mavsdk_endpoint(*, sysid: int) -> str:
    """MAVSDK connection string per PX4 instance."""
    return f"udp://127.0.0.1:{14540 + (sysid - 1)}"


# ---------------------------------------------------------------------------
# Mesh factory defaults
# ---------------------------------------------------------------------------


def _default_mesh_factory(
    self_endpoint: str, peer_endpoints: list[str]
) -> MeshBus:
    return ZmqMesh(
        self_endpoint=self_endpoint, peer_endpoints=list(peer_endpoints)
    )


def _noop_mesh_factory(*_args, **_kwargs) -> MeshBus:
    return NoOpMesh()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_fleet(
    *,
    arch_cfg: ArchitectureConfig,
    exp_cfg: ExperimentConfig,
    run_id: str,
    log_root: Path,
    px4_path: Optional[Path] = None,
    connection_factory: Optional[ConnectionFactory] = None,
    mesh_factory: Optional[MeshFactory] = None,
    process_runner: Optional[ProcessRunner] = None,
) -> WiredFleet:
    """Assemble all components required for one experiment run.

    Parameters
    ----------
    process_runner
        ProcessRunner shared by ALL per-UAV RestartProcessHandlers in
        Architecture C. None (default) means each handler creates its
        own DefaultProcessRunner. Pass an ExternalAwareProcessRunner
        when PX4 instances were launched out-of-band.
    """

    # Set up paths.
    log_dir = Path(log_root) / f"run_{run_id}"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Build a uav_id -> TelemetryEndpointSpec map for fast lookup.
    endpoints_by_uav = {e.uav_id: e for e in exp_cfg.telemetry.endpoints}

    if arch_cfg.architecture == "A":
        return _build_arch_ab(
            arch_cfg=arch_cfg,
            endpoints_by_uav=endpoints_by_uav,
            log_dir=log_dir,
            connection_factory=connection_factory,
            architecture="A",
        )
    elif arch_cfg.architecture == "B":
        return _build_arch_ab(
            arch_cfg=arch_cfg,
            endpoints_by_uav=endpoints_by_uav,
            log_dir=log_dir,
            connection_factory=connection_factory,
            architecture="B",
        )
    elif arch_cfg.architecture == "C":
        return _build_arch_c(
            arch_cfg=arch_cfg,
            exp_cfg=exp_cfg,
            endpoints_by_uav=endpoints_by_uav,
            log_dir=log_dir,
            px4_path=px4_path or Path.home() / "PX4-Autopilot",
            connection_factory=connection_factory,
            mesh_factory=mesh_factory or _default_mesh_factory,
            process_runner=process_runner,
        )
    else:
        raise ValueError(f"unknown architecture {arch_cfg.architecture!r}")


# ---------------------------------------------------------------------------
# Architecture A and B (no mesh, no recovery)
# ---------------------------------------------------------------------------


def _build_arch_ab(
    *,
    arch_cfg: ArchitectureConfig,
    endpoints_by_uav: dict,
    log_dir: Path,
    connection_factory: Optional[ConnectionFactory],
    architecture: str,
) -> WiredFleet:
    monitors: list[Monitor] = []

    for spec in arch_cfg.monitors:
        # spec.watches lists one or more uav_ids that this monitor entry
        # observes. Architecture A typically has one entry with three
        # watches (-> three Monitor instances in one process).
        # Architecture B has three entries with one watch each.
        for watched_uav in spec.watches:
            ep = endpoints_by_uav.get(watched_uav)
            if ep is None:
                raise ValueError(
                    f"monitor at {spec.location!r} watches {watched_uav!r}, "
                    f"but experiment has no telemetry endpoint for it"
                )
            source = f"monitor_{spec.location}_{watched_uav}"
            detectors = _build_detectors(
                list(spec.detectors), target_uav=watched_uav, source=source
            )
            decider = IsolationDecider(source=source)
            enforcer = LocalIsolationEnforcer()

            connection = (
                connection_factory(ep.endpoint)
                if connection_factory is not None
                else None
            )

            mon = Monitor(
                uav_id=watched_uav,
                source=source,
                telemetry_endpoint=ep.endpoint,
                sysid=ep.sysid,
                detectors=detectors,
                log_path=log_dir / f"{source}.jsonl",
                isolation_decider=decider,
                isolation_enforcer=enforcer,
                _telemetry_connection=connection,
            )
            monitors.append(mon)

    return WiredFleet(
        architecture=architecture,
        monitors=monitors,
        coordinators=[],
        meshes=[],
        log_dir=log_dir,
    )


# ---------------------------------------------------------------------------
# Architecture C (mesh + recovery)
# ---------------------------------------------------------------------------


def _build_arch_c(
    *,
    arch_cfg: ArchitectureConfig,
    exp_cfg: ExperimentConfig,
    endpoints_by_uav: dict,
    log_dir: Path,
    px4_path: Path,
    connection_factory: Optional[ConnectionFactory],
    mesh_factory: MeshFactory,
    process_runner: Optional[ProcessRunner] = None,
) -> WiredFleet:
    # Validate that arch.mesh.endpoints covers every monitor's UAV.
    # (load_architecture_config already enforces this, but keep the
    # local check so the factory is robust if called with manually-
    # constructed configs.)
    monitor_uavs = {m.location for m in arch_cfg.monitors}
    missing = monitor_uavs - set(arch_cfg.mesh.endpoints.keys())
    if missing:
        raise ValueError(
            f"architecture C: mesh endpoints missing for {sorted(missing)}"
        )

    # uav_id -> sysid map (for coordinator construction).
    sysid_by_uav = {e.uav_id: e.sysid for e in exp_cfg.telemetry.endpoints}
    sysid_to_uav = {v: k for k, v in sysid_by_uav.items()}
    all_sysids = sorted(sysid_to_uav.keys())

    monitors: list[Monitor] = []
    coordinators: list[Coordinator] = []
    meshes: list[MeshBus] = []
    filter_handlers: list[FilterCommandsHandler] = []

    for spec in arch_cfg.monitors:
        # In Architecture C every monitor entry has location == its own
        # uav_id and watches itself. (Validated by config loader.)
        uav_id = spec.location
        ep = endpoints_by_uav.get(uav_id)
        if ep is None:
            raise ValueError(
                f"monitor at {uav_id!r} has no telemetry endpoint configured"
            )

        # Build mesh: this peer's endpoint + every OTHER peer's endpoint.
        self_ep = arch_cfg.mesh.endpoints[uav_id]
        peer_eps = [
            endpoint
            for other_uav, endpoint in arch_cfg.mesh.endpoints.items()
            if other_uav != uav_id
        ]
        mesh = mesh_factory(self_ep, peer_eps)
        meshes.append(mesh)

        source = f"monitor_{uav_id}"
        detectors = _build_detectors(
            list(spec.detectors), target_uav=uav_id, source=source
        )
        cross_check = (
            CrossCheckDetector(monitor_uav_id=uav_id, source=source)
            if "cross_check" in spec.detectors
            else None
        )

        decider = IsolationDecider(source=source)
        enforcer = MeshAnnouncingIsolationEnforcer(mesh=mesh)

        connection = (
            connection_factory(ep.endpoint)
            if connection_factory is not None
            else None
        )

        mon = Monitor(
            uav_id=uav_id,
            source=source,
            telemetry_endpoint=ep.endpoint,
            sysid=ep.sysid,
            detectors=detectors,
            log_path=log_dir / f"{source}.jsonl",
            isolation_decider=decider,
            isolation_enforcer=enforcer,
            mesh=mesh,
            cross_check=cross_check,
            _telemetry_connection=connection,
        )
        monitors.append(mon)

        # ----- recovery handlers + executor + coordinator -----

        process_spec = _default_process_spec(
            uav_id=uav_id, sysid=ep.sysid, px4_path=px4_path
        )
        # If the caller provided a shared ProcessRunner (typically an
        # ExternalAwareProcessRunner that knows about externally-
        # launched PX4 instances), share it across all per-UAV
        # RestartProcessHandlers. Otherwise each handler defaults to
        # its own DefaultProcessRunner.
        restart_handler = RestartProcessHandler(
            specs={uav_id: process_spec},
            runner=process_runner,
        )
        loiter_handler = ModeLoiterHandler(
            endpoints={uav_id: _default_mavsdk_endpoint(sysid=ep.sysid)}
        )
        filter_handler = FilterCommandsHandler()
        filter_handlers.append(filter_handler)

        executor = RecoveryExecutor(
            source=f"enforcer_{uav_id}",
            enabled=True,
            handlers={
                RecoveryAction.RESTART_PROCESS: restart_handler,
                RecoveryAction.MODE_LOITER: loiter_handler,
                RecoveryAction.FILTER_COMMANDS: filter_handler,
            },
        )
        recovery_decider = RecoveryDecider(
            source=f"coordinator_{uav_id}", enabled=True
        )

        # Recovery completion callback: lift local enforcer + un_isolate
        # local decider when recovery succeeds.
        def _make_callback(d=decider, e=enforcer):
            def _on_recovery_completed(uav: str, success: bool) -> None:
                if not success:
                    return
                e.lift(uav)
                d.un_isolate(uav)
            return _on_recovery_completed

        coord = Coordinator(
            source=f"coordinator_{uav_id}",
            our_sysid=ep.sysid,
            all_sysids=all_sysids,
            sysid_to_uav=sysid_to_uav,
            target_uav=uav_id,
            mesh=mesh,
            recovery_decider=recovery_decider,
            recovery_executor=executor,
            on_recovery_completed=_make_callback(),
            log_path=log_dir / f"coordinator_{uav_id}.jsonl",
        )
        coordinators.append(coord)

    return WiredFleet(
        architecture="C",
        monitors=monitors,
        coordinators=coordinators,
        meshes=meshes,
        log_dir=log_dir,
        filter_handlers=filter_handlers,
    )
