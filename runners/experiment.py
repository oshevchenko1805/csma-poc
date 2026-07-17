"""
ExperimentRunner — one experiment run from build to summary.

Drives the full lifecycle of a single trial: build fleet, start mesh
and components, fly the mission, fire the attack (if any), wait for
observation window, stop everything cleanly, merge logs, write
summary.

Inputs
------
- ArchitectureConfig + ExperimentConfig (loaded from yaml)
- An AttackInjector (use NullAttackInjector for baseline)
- A MissionRunner (use NullMissionRunner for tests, MavsdkMissionRunner
  for real PX4)

Outputs
-------
- Per-monitor JSONL logs under <log_root>/run_<run_id>/
- Merged JSONL under run_<run_id>/merged.jsonl
- run_summary.json with counters and metadata
- RunResult returned to caller

Lifecycle order (strict)
------------------------
Setup:                                  Teardown (reverse):
  build_fleet                              merge_logs + summary
  mesh.start()        × N                  attack.cleanup()
  monitor.start()     × N                  mission.abort()
  coordinator.start() × N                  monitor.stop()    × N
                                           coordinator.stop() × N
                                           mesh.stop()        × N

Teardown order matters twice over:
  - attack.cleanup() runs BEFORE mission.abort() so a param-restoring
    attack (gps_spoofing) can still reach the target through the live
    mission connection; abort() RTLs and disconnects it.
  - then stop monitors first so no new mesh publishes happen, then
    coordinators, then meshes. Reversing that can deadlock if a
    coordinator tries to publish a final ack into a stopped mesh.

Self-describing runs
--------------------
`run_summary.json` carries three things beyond counters, all for the
same reason: `*.jsonl` is gitignored, so the summary is the only
artefact that gets committed. A question that cannot be answered from it
cannot be answered at all once the run directory is gone — and both
OPEN-1 and OPEN-3 are exactly that failure.

  mission_plan       what route was flown (laps, waypoints, timing)
  flight_at_attack   what the UAVs were physically doing at injection,
                     from Gazebo ground truth (OPEN-1 / R7: 120 trials
                     attacked a hovering UAV and nothing said so)
  estimator_series   the raw EKF residuals the detectors saw (OPEN-3 /
                     R8: the undetected run holds zero security events,
                     so nothing records what its detector saw)

All three are computed from data the runner already had. None branches
on architecture, so the identical-measurement-procedure requirement
(thesis 3.5.5, table 3.14) holds by construction.

Note the asymmetry in what they are FOR: flight_at_attack comes from
Gazebo, outside the system under test, and is metric-grade.
estimator_series comes from the monitors, inside it — under
monitor_takeout it dies with them, so its availability is
architecture-dependent and it is diagnostic only. Nothing in table 3.13
may be computed from it.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from attacks.base import AttackContext, AttackInjector, NullAttackInjector
from core.config import ArchitectureConfig, ExperimentConfig
from core.events import AttackEvent
from core.logger import EventLogger, merge_jsonl
from enforcement.handlers import ProcessRunner
from metrics.estimator_series import (
    estimator_series as build_estimator_series,
    read_telemetry,
)
from metrics.belief_divergence import (
    belief_divergence as build_belief_divergence,
)
from metrics.flight_check import (
    flight_state_at,
    mission_plan_summary,
    read_trajectory,
)
from runners.factory import (
    TELEMETRY_LOG_PREFIX,
    ConnectionFactory,
    MeshFactory,
    WiredFleet,
    build_fleet,
)
from runners.missions import MissionRunner, NullMissionRunner

# Ground-truth trajectory file, written by an optional TrajectoryRecorder.
# The runner owns the name so the merge step can exclude it reliably: it
# holds pose samples, not events, and must never enter merged.jsonl.
TRAJECTORY_FILENAME = "trajectory.jsonl"

TrajectoryRecorderFactory = Any
"""(out_path: Path) -> object with start()/stop()/stats. Injected so the
real gz-backed recorder is used only for real flights; tests inject a fake
or leave it None (no recording)."""


@dataclass
class RunResult:
    """Outcome of one experiment run — written to run_summary.json."""

    architecture: str
    run_id: str
    attack_name: str
    target_uav: Optional[str]
    duration_sec: float
    log_dir: str
    merged_log: str
    monitor_stats: list[dict[str, Any]] = field(default_factory=list)
    coordinator_stats: list[dict[str, Any]] = field(default_factory=list)
    trajectory_stats: Optional[dict[str, Any]] = None
    """Ground-truth recorder counters, or None when not recording."""
    mission_plan: Optional[dict[str, Any]] = None
    """The route flown: laps, expanded waypoints, injection timing. The
    reference frame without which the coordinates below mean nothing."""
    flight_at_attack: Optional[dict[str, Any]] = None
    """Physical state of every UAV at the injection instant, from Gazebo
    poses. None means NOT OBSERVED (no recorder) — never "not flying"."""
    estimator_series: Optional[dict[str, Any]] = None
    """Raw EKF residual series per UAV, anchored to the injection
    instant. Diagnostic, not metric-grade — see module docstring."""
    belief_divergence: Optional[dict[str, Any]] = None
    """True (Gazebo) vs believed (PX4 NED) position divergence per UAV,
    in metres. Diagnostic, not metric-grade — same scope rule as
    estimator_series (dies under monitor_takeout)."""
    error: Optional[str] = None


class ExperimentRunner:
    """Orchestrates a single experiment run."""

    DEFAULT_OBSERVATION_AFTER_ATTACK_SEC: float = 60.0
    DEFAULT_ATTACK_AT_SEC: float = 30.0

    def __init__(
        self,
        *,
        arch_cfg: ArchitectureConfig,
        exp_cfg: ExperimentConfig,
        run_id: str,
        log_root: Path,
        attack_injector: Optional[AttackInjector] = None,
        mission_runner: Optional[MissionRunner] = None,
        target_uav: Optional[str] = None,
        attack_at_sec: float = DEFAULT_ATTACK_AT_SEC,
        observation_after_attack_sec: Optional[float] = None,
        connection_factory: Optional[ConnectionFactory] = None,
        mesh_factory: Optional[MeshFactory] = None,
        px4_path: Optional[Path] = None,
        process_runner: Optional[ProcessRunner] = None,
        trajectory_recorder_factory: Optional[TrajectoryRecorderFactory] = None,
    ) -> None:
        if attack_at_sec < 0:
            raise ValueError("attack_at_sec must be non-negative")

        self._arch_cfg = arch_cfg
        self._exp_cfg = exp_cfg
        self._run_id = run_id
        self._log_root = Path(log_root)
        self._attack_injector = attack_injector or NullAttackInjector()
        self._mission_runner = mission_runner
        self._target_uav = target_uav
        self._attack_at = attack_at_sec
        self._obs_after = (
            observation_after_attack_sec
            if observation_after_attack_sec is not None
            else exp_cfg.runs.observation_after_attack_sec
        )
        self._connection_factory = connection_factory
        self._mesh_factory = mesh_factory
        self._px4_path = px4_path
        self._process_runner = process_runner
        self._trajectory_recorder_factory = trajectory_recorder_factory

        # State filled during run()
        self._fleet: Optional[WiredFleet] = None
        self._attack_logger: Optional[EventLogger] = None
        self._trajectory_recorder: Optional[Any] = None
        self._start_wall: float = 0.0
        self._attack_fired_wall: Optional[float] = None
        """Wall clock of the injection instant. Stays None if the run
        never reached it (setup failure) — which is why the flight check
        and the residual series then report None instead of a verdict."""

    # ----- public entry point -----

    def run(self) -> RunResult:
        """Synchronous wrapper. Drives the full lifecycle."""
        loop = asyncio.new_event_loop()

        def _swallow_closed_loop(lp, context):
            exc = context.get("exception")
            if isinstance(exc, RuntimeError) and "Event loop is closed" in str(exc):
                return
            lp.default_exception_handler(context)

        loop.set_exception_handler(_swallow_closed_loop)
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(self._run_async())
            loop.run_until_complete(asyncio.sleep(0.25))
            loop.run_until_complete(loop.shutdown_asyncgens())
            return result
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    # ----- internal: full lifecycle -----

    async def _run_async(self) -> RunResult:
        error: Optional[str] = None
        try:
            self._setup_fleet()
            await self._run_scenario()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            # Cleanup MUST run even on failure. Order matters:
            # (1) attack cleanup restores params via the still-live
            #     mission connection;
            # (2) mission abort RTLs and disconnects the UAVs;
            # (3) fleet teardown stops monitors/coordinators/meshes.
            try:
                await self._cleanup_attack()
            except Exception as exc:
                error = error or f"cleanup_attack: {exc}"
            try:
                if self._mission_runner is not None:
                    await self._mission_runner.abort()
            except Exception as exc:
                error = error or f"mission_abort: {exc}"
            try:
                self._teardown_fleet()
            except Exception as exc:
                error = error or f"teardown: {exc}"

        return self._finalize(error)

    # ----- setup -----

    def _resolve_target(self) -> str:
        """The UAV under attack. One definition, used by the scenario and
        by both post-hoc checks — separate copies of this rule could
        disagree and silently describe the wrong vehicle."""
        return self._target_uav or self._exp_cfg.telemetry.endpoints[0].uav_id

    def _setup_fleet(self) -> None:
        self._fleet = build_fleet(
            arch_cfg=self._arch_cfg,
            exp_cfg=self._exp_cfg,
            run_id=self._run_id,
            log_root=self._log_root,
            connection_factory=self._connection_factory,
            mesh_factory=self._mesh_factory,
            px4_path=self._px4_path,
            process_runner=self._process_runner,
        )
        # Dedicated logger for attack ground-truth markers, lives
        # alongside monitor logs in the run directory.
        self._attack_logger = EventLogger(
            self._fleet.log_dir / "attack.jsonl"
        )

        # Ground-truth trajectory recorder (optional). Started before the
        # mission so the pre-attack baseline is captured. It observes the
        # simulator from outside the system under test, so it survives the
        # attacks that stop monitors, and it is never fed by PX4's own
        # (spoofable) estimate. A recorder failure must not fail a flight.
        if self._trajectory_recorder_factory is not None:
            try:
                self._trajectory_recorder = self._trajectory_recorder_factory(
                    self._fleet.log_dir / TRAJECTORY_FILENAME
                )
                self._trajectory_recorder.start()
            except Exception:
                self._trajectory_recorder = None

        # Start order: meshes -> monitors -> coordinators
        for mesh in self._fleet.meshes:
            mesh.start()
        for mon in self._fleet.monitors:
            mon.start()
        for coord in self._fleet.coordinators:
            coord.start()

        # Swap each loiter handler's MAVSDK runner for one backed by the
        # live mission connection. During flight the mission owns the only
        # connection to each UAV; a loiter handler opening its own MAVSDK
        # System can't bind the port (step 10e). Only applies when the
        # mission can lend a connection (real MAVSDK flight); Null/other
        # missions are left with their default runner.
        if self._mission_runner is not None and hasattr(
            self._mission_runner, "loiter_runner_for"
        ):
            # Capture the main event loop that owns the mission MAVSDK
            # connections. Recovery runs hold() from the mesh-receiver
            # thread's short-lived loop; the loiter runner bridges it back
            # onto this loop via run_coroutine_threadsafe.
            try:
                main_loop = asyncio.get_running_loop()
            except RuntimeError:
                main_loop = None
            for handler in self._fleet.loiter_handlers:
                for uav_id in handler.supported_uavs:
                    handler.set_runner(
                        self._mission_runner.loiter_runner_for(
                            uav_id, main_loop=main_loop
                        )
                    )

        self._start_wall = time.time()

    # ----- scenario -----

    async def _run_scenario(self) -> None:
        assert self._fleet is not None

        # Arm attack (resource setup) early so failures show up before
        # mission starts.
        target = self._resolve_target()
        target_sysid = next(
            e.sysid for e in self._exp_cfg.telemetry.endpoints
            if e.uav_id == target
        )
        # A param-writing attack (gps_spoofing) needs to reach PX4 params
        # while the target is flying. During flight the mission owns the
        # only MAVSDK connection, so it lends one via param_writer_for.
        # Resolved lazily by the writer at fire() time (controllers don't
        # exist until mission.start()). None when the mission can't
        # provide one (NullMissionRunner) — non-param attacks ignore it.
        param_writer = (
            self._mission_runner.param_writer_for(target)
            if self._mission_runner is not None
            else None
        )
        ctx = AttackContext(
            target_uav=target,
            target_sysid=target_sysid,
            log_dir=self._fleet.log_dir,
            param_writer=param_writer,
            monitors=tuple(self._fleet.monitors),
        )
        await self._attack_injector.arm(ctx)

        # Start mission (or just observe) and wait until attack_at_sec
        if self._mission_runner is not None:
            await self._mission_runner.start()

        await asyncio.sleep(self._attack_at)

        # The injection instant, on the same wall clock as merged.jsonl
        # events, trajectory.jsonl samples and the telemetry logs.
        # Captured here, not derived later: fire() can block (a param set
        # is a network round trip), and this is the axis both post-hoc
        # checks anchor to. Set on baseline too — the nominal instant is
        # what lets the control condition be checked by the identical
        # procedure (thesis 3.5.5).
        self._attack_fired_wall = time.time()

        # Ground-truth marker BEFORE fire: pin "attack injection started"
        # so MTTD measurement uses a definitive timestamp.
        await self._attack_injector.fire()
        self._emit_attack_event(target, phase="inject_start")

        # Observation window for detection + isolation + recovery
        await asyncio.sleep(self._obs_after)

        # End-of-run marker
        self._emit_attack_event(target, phase="inject_end")

        # NOTE: mission abort/RTL moved to _run_async's finally so it
        # runs AFTER attack cleanup — gps_spoofing's param restore borrows
        # the live mission connection, which abort() tears down.

    def _emit_attack_event(self, target: str, *, phase: str) -> None:
        if self._attack_logger is None:
            return
        ev = AttackEvent(
            source="experiment_runner",
            attack_type=self._attack_injector.name,
            target_uav=target,
            phase=phase,
        )
        try:
            self._attack_logger.log(ev)
        except Exception:
            pass

    # ----- teardown -----

    async def _cleanup_attack(self) -> None:
        try:
            await self._attack_injector.cleanup()
        except Exception:
            # Don't let a buggy attack cleanup hide the actual error.
            pass

    def _teardown_fleet(self) -> None:
        if self._fleet is None:
            return
        # Reverse start order: monitors -> coordinators -> meshes.
        # Monitor.stop() also closes its telemetry log, which _finalize
        # reads back — so the residual series must never be computed
        # before this.
        for mon in self._fleet.monitors:
            try:
                mon.stop()
            except Exception:
                pass
        for coord in self._fleet.coordinators:
            try:
                coord.stop()
            except Exception:
                pass
        for mesh in self._fleet.meshes:
            try:
                mesh.stop()
            except Exception:
                pass
        # Stopped last: keeps recording through mission abort/RTL. This
        # also flushes and closes trajectory.jsonl, which _finalize then
        # reads back — so the flight check must never run before this.
        if self._trajectory_recorder is not None:
            try:
                self._trajectory_recorder.stop()
            except Exception:
                pass
        if self._attack_logger is not None:
            try:
                self._attack_logger.close()
            except Exception:
                pass

    # ----- finalize -----

    def _compute_flight_at_attack(
        self, log_dir: Path
    ) -> Optional[dict[str, Any]]:
        """Read the ground-truth poses back and answer "was it flying?".

        None when no recorder ran: that is "not observed", which is a
        different fact from "not moving", and collapsing the two would put
        a confident falsehood into the dataset. A recorder that ran but
        produced nothing yields a populated dict with null verdicts —
        "we looked and saw nothing" — which the analysis layer can report
        honestly as a dropout.
        """
        if self._trajectory_recorder is None:
            return None
        samples = read_trajectory(log_dir / TRAJECTORY_FILENAME)
        return flight_state_at(
            samples,
            self._attack_fired_wall,
            target_uav=self._resolve_target(),
        )

    def _compute_estimator_series(
        self, log_dir: Path
    ) -> Optional[dict[str, Any]]:
        """Fold every monitor's raw telemetry log into one series set.

        One file per monitor, each holding only its own UAV's samples, so
        concatenating them and grouping by uav_id inside the events is
        lossless. A monitor killed mid-run simply contributes fewer
        samples — which is itself the observation, not an error.
        """
        samples: list[dict[str, Any]] = []
        for path in sorted(log_dir.glob(f"{TELEMETRY_LOG_PREFIX}*.jsonl")):
            samples.extend(read_telemetry(path))
        return build_estimator_series(
            samples,
            self._attack_fired_wall,
            target_uav=self._resolve_target(),
        )

    def _compute_belief_divergence(
        self, log_dir: Path
    ) -> Optional[dict[str, Any]]:
        """Pair Gazebo truth against PX4's believed NED, per UAV.

        None when no trajectory recorder ran: without ground truth there
        is nothing to diverge from. The believed side is read from the
        same per-monitor telemetry logs estimator_series folds; a killed
        monitor simply contributes fewer samples, which is the
        observation, not an error. Unlike estimator_series this runs on
        baseline (unattacked) runs too — that is where the EKF noise floor
        and the axis calibration are validated (attack_at_wall is None
        there, which belief_divergence handles by anchoring to the first
        paired sample).
        """
        if self._trajectory_recorder is None:
            return None
        traj = read_trajectory(log_dir / TRAJECTORY_FILENAME)
        tele: list[dict[str, Any]] = []
        for path in sorted(log_dir.glob(f"{TELEMETRY_LOG_PREFIX}*.jsonl")):
            tele.extend(read_telemetry(path))
        return build_belief_divergence(
            traj,
            tele,
            self._attack_fired_wall,
            target_uav=self._resolve_target(),
        )

    def _finalize(self, error: Optional[str]) -> RunResult:
        duration = time.time() - self._start_wall if self._start_wall else 0.0

        # Independent of the fleet, so it is recorded even for a run that
        # died during setup: a failed run still has to say what it was
        # trying to fly.
        mission_plan: Optional[dict[str, Any]] = None
        try:
            mission_plan = mission_plan_summary(
                self._exp_cfg.mission,
                attack_at_sec=self._attack_at,
                observation_after_attack_sec=self._obs_after,
            )
        except Exception as exc:
            error = error or f"mission_plan: {exc}"

        if self._fleet is None:
            return RunResult(
                architecture=self._arch_cfg.architecture,
                run_id=self._run_id,
                attack_name=self._attack_injector.name,
                target_uav=self._target_uav,
                duration_sec=duration,
                log_dir="",
                merged_log="",
                mission_plan=mission_plan,
                error=error or "fleet_setup_failed",
            )

        log_dir = self._fleet.log_dir
        merged_path = log_dir / "merged.jsonl"

        # Merge all per-component logs in the run directory.
        sources = sorted(log_dir.glob("*.jsonl"))
        # Exclude the merged file itself in case of re-runs.
        # trajectory.jsonl holds pose samples and telemetry_*.jsonl holds
        # raw MAVLink — neither is an event stream. Merging them would
        # bury the events the metrics layer reads under thousands of
        # samples.
        sources = [
            p
            for p in sources
            if p.name not in ("merged.jsonl", TRAJECTORY_FILENAME)
            and not p.name.startswith(TELEMETRY_LOG_PREFIX)
        ]
        try:
            merge_jsonl(sources, merged_path)
        except Exception as exc:
            error = error or f"merge: {exc}"

        # Post-hoc reads of an already-finished flight. A defect here
        # surfaces in `error` rather than raising: the flight happened and
        # its logs are on disk, so losing a real run over a summary field
        # would be the expensive failure — same contract as merge.
        flight_at_attack: Optional[dict[str, Any]] = None
        try:
            flight_at_attack = self._compute_flight_at_attack(log_dir)
        except Exception as exc:
            error = error or f"flight_check: {exc}"

        estimator_series: Optional[dict[str, Any]] = None
        try:
            estimator_series = self._compute_estimator_series(log_dir)
        except Exception as exc:
            error = error or f"estimator_series: {exc}"

        belief_divergence: Optional[dict[str, Any]] = None
        try:
            belief_divergence = self._compute_belief_divergence(log_dir)
        except Exception as exc:
            error = error or f"belief_divergence: {exc}"

        monitor_stats = [m.stats for m in self._fleet.monitors]
        coordinator_stats = [c.stats for c in self._fleet.coordinators]

        result = RunResult(
            architecture=self._arch_cfg.architecture,
            run_id=self._run_id,
            attack_name=self._attack_injector.name,
            target_uav=self._target_uav,
            duration_sec=duration,
            log_dir=str(log_dir),
            merged_log=str(merged_path),
            monitor_stats=monitor_stats,
            coordinator_stats=coordinator_stats,
            trajectory_stats=(
                dict(self._trajectory_recorder.stats)
                if self._trajectory_recorder is not None
                else None
            ),
            mission_plan=mission_plan,
            flight_at_attack=flight_at_attack,
            estimator_series=estimator_series,
            belief_divergence=belief_divergence,
            error=error,
        )

        # Write summary
        summary_path = log_dir / "run_summary.json"
        try:
            with summary_path.open("w") as f:
                json.dump(asdict(result), f, indent=2, default=str)
        except Exception:
            pass

        return result
