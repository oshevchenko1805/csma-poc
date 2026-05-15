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
  mesh.start()        × N                  monitor.stop()    × N
  monitor.start()     × N                  coordinator.stop() × N
  coordinator.start() × N                  mesh.stop()        × N
                                           (handlers cleaned up below)

The teardown order matters: stop monitors first so no new mesh
publishes happen, then coordinators, then meshes. Reversing this can
deadlock if a coordinator tries to publish a final ack into a
mesh that's already stopped.
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
from runners.factory import (
    ConnectionFactory,
    MeshFactory,
    WiredFleet,
    build_fleet,
)
from runners.missions import MissionRunner, NullMissionRunner


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

        # State filled during run()
        self._fleet: Optional[WiredFleet] = None
        self._attack_logger: Optional[EventLogger] = None
        self._start_wall: float = 0.0

    # ----- public entry point -----

    def run(self) -> RunResult:
        """Synchronous wrapper. Drives the full lifecycle."""
        return asyncio.run(self._run_async())

    # ----- internal: full lifecycle -----

    async def _run_async(self) -> RunResult:
        error: Optional[str] = None
        try:
            self._setup_fleet()
            await self._run_scenario()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            # Cleanup MUST run even on failure.
            try:
                await self._cleanup_attack()
            except Exception as exc:
                error = error or f"cleanup_attack: {exc}"
            try:
                self._teardown_fleet()
            except Exception as exc:
                error = error or f"teardown: {exc}"

        return self._finalize(error)

    # ----- setup -----

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

        # Start order: meshes -> monitors -> coordinators
        for mesh in self._fleet.meshes:
            mesh.start()
        for mon in self._fleet.monitors:
            mon.start()
        for coord in self._fleet.coordinators:
            coord.start()

        self._start_wall = time.time()

    # ----- scenario -----

    async def _run_scenario(self) -> None:
        assert self._fleet is not None

        # Arm attack (resource setup) early so failures show up before
        # mission starts.
        target = self._target_uav or self._exp_cfg.telemetry.endpoints[0].uav_id
        target_sysid = next(
            e.sysid for e in self._exp_cfg.telemetry.endpoints
            if e.uav_id == target
        )
        ctx = AttackContext(
            target_uav=target,
            target_sysid=target_sysid,
            log_dir=self._fleet.log_dir,
        )
        await self._attack_injector.arm(ctx)

        # Start mission (or just observe) and wait until attack_at_sec
        if self._mission_runner is not None:
            await self._mission_runner.start()

        await asyncio.sleep(self._attack_at)

        # Ground-truth marker BEFORE fire: pin "attack injection started"
        # so MTTD measurement uses a definitive timestamp.
        await self._attack_injector.fire()
        self._emit_attack_event(target, phase="inject_start")

        # Observation window for detection + isolation + recovery
        await asyncio.sleep(self._obs_after)

        # End-of-run marker
        self._emit_attack_event(target, phase="inject_end")

        # If a mission is running, abort it (we've collected what we
        # need). Real MAVSDK mission would do a safe RTL.
        if self._mission_runner is not None:
            await self._mission_runner.abort()

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
        # Reverse start order: monitors -> coordinators -> meshes
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
        if self._attack_logger is not None:
            try:
                self._attack_logger.close()
            except Exception:
                pass

    # ----- finalize -----

    def _finalize(self, error: Optional[str]) -> RunResult:
        duration = time.time() - self._start_wall if self._start_wall else 0.0

        if self._fleet is None:
            return RunResult(
                architecture=self._arch_cfg.architecture,
                run_id=self._run_id,
                attack_name=self._attack_injector.name,
                target_uav=self._target_uav,
                duration_sec=duration,
                log_dir="",
                merged_log="",
                error=error or "fleet_setup_failed",
            )

        log_dir = self._fleet.log_dir
        merged_path = log_dir / "merged.jsonl"

        # Merge all per-component logs in the run directory.
        sources = sorted(log_dir.glob("*.jsonl"))
        # Exclude the merged file itself in case of re-runs.
        sources = [p for p in sources if p.name != "merged.jsonl"]
        try:
            merge_jsonl(sources, merged_path)
        except Exception as exc:
            error = error or f"merge: {exc}"

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
