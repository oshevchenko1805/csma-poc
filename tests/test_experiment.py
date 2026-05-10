"""Tests for runners.experiment.

Uses fake connection + NoOp mesh + NullMissionRunner so the lifecycle
runs end-to-end in seconds without PX4.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from attacks.base import AttackContext, AttackInjector, NullAttackInjector
from core.config import load_architecture_config, load_experiment_config
from core.logger import read_jsonl
from core.mesh import NoOpMesh
from runners.experiment import ExperimentRunner, RunResult
from runners.missions import NullMissionRunner


CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def recv_match(self, **_kwargs):
        return None

    def close(self) -> None:
        self.closed = True


def _fake_conn_factory(_endpoint: str) -> FakeConnection:
    return FakeConnection()


def _noop_mesh_factory(_self_ep, _peer_eps) -> NoOpMesh:
    return NoOpMesh()


class RecordingInjector(AttackInjector):
    """Counts arm / fire / cleanup calls."""

    def __init__(
        self,
        *,
        name: str = "test_attack",
        arm_raises: bool = False,
        fire_raises: bool = False,
    ) -> None:
        self._name = name
        self.armed = False
        self.fired = False
        self.cleaned = False
        self._arm_raises = arm_raises
        self._fire_raises = fire_raises
        self.context: AttackContext | None = None

    @property
    def name(self) -> str:
        return self._name

    async def arm(self, ctx: AttackContext) -> None:
        self.context = ctx
        if self._arm_raises:
            raise RuntimeError("arm failed")
        self.armed = True

    async def fire(self) -> None:
        if self._fire_raises:
            raise RuntimeError("fire failed")
        self.fired = True

    async def cleanup(self) -> None:
        self.cleaned = True


def _make_runner(
    tmp_path: Path,
    arch: str = "a",
    *,
    attack: AttackInjector | None = None,
    mission_duration: float = 0.5,
    attack_at: float = 0.1,
    obs_after: float = 0.2,
    target_uav: str | None = None,
) -> ExperimentRunner:
    arch_cfg = load_architecture_config(CONFIG_DIR / f"architecture_{arch}.yaml")
    exp_cfg = load_experiment_config(CONFIG_DIR / "experiment.yaml")
    return ExperimentRunner(
        arch_cfg=arch_cfg,
        exp_cfg=exp_cfg,
        run_id="test",
        log_root=tmp_path,
        attack_injector=attack,
        mission_runner=NullMissionRunner(duration_sec=mission_duration),
        target_uav=target_uav,
        attack_at_sec=attack_at,
        observation_after_attack_sec=obs_after,
        connection_factory=_fake_conn_factory,
        mesh_factory=_noop_mesh_factory,
    )


# ---------------------------------------------------------------------------
# Baseline runs (no attack)
# ---------------------------------------------------------------------------


class TestBaselineRun:
    def test_baseline_a_completes_cleanly(self, tmp_path: Path):
        result = _make_runner(tmp_path, "a").run()
        assert isinstance(result, RunResult)
        assert result.architecture == "A"
        assert result.run_id == "test"
        assert result.attack_name == "none"
        assert result.error is None
        assert result.duration_sec > 0
        assert Path(result.log_dir).exists()

    def test_baseline_c_completes_cleanly(self, tmp_path: Path):
        result = _make_runner(tmp_path, "c").run()
        assert result.architecture == "C"
        assert result.error is None
        # Architecture C should have non-empty coordinator stats
        assert len(result.coordinator_stats) == 3

    def test_summary_json_written(self, tmp_path: Path):
        result = _make_runner(tmp_path, "a").run()
        summary = Path(result.log_dir) / "run_summary.json"
        assert summary.exists()
        data = json.loads(summary.read_text())
        assert data["architecture"] == "A"
        assert data["error"] is None

    def test_merged_log_created(self, tmp_path: Path):
        result = _make_runner(tmp_path, "a").run()
        merged = Path(result.merged_log)
        assert merged.exists()
        assert merged.name == "merged.jsonl"


# ---------------------------------------------------------------------------
# Attack injection lifecycle
# ---------------------------------------------------------------------------


class TestAttackInjection:
    def test_arm_fire_cleanup_called_in_order(self, tmp_path: Path):
        inj = RecordingInjector()
        result = _make_runner(tmp_path, "a", attack=inj).run()
        assert inj.armed
        assert inj.fired
        assert inj.cleaned
        assert result.attack_name == "test_attack"
        assert result.error is None

    def test_attack_event_logged(self, tmp_path: Path):
        inj = RecordingInjector(name="comm_disruption")
        result = _make_runner(tmp_path, "a", attack=inj).run()
        attack_log = Path(result.log_dir) / "attack.jsonl"
        assert attack_log.exists()
        events = read_jsonl(attack_log)
        # Should have at least inject_start and inject_end
        types = [e.event_type for e in events]
        assert "attack" in types
        attack_events = [e for e in events if e.event_type == "attack"]
        phases = sorted({e.phase for e in attack_events})
        assert "inject_start" in phases
        assert "inject_end" in phases
        # All should reference our target_uav and attack name
        for e in attack_events:
            assert e.target_uav  # non-empty
            assert e.attack_type == "comm_disruption"

    def test_context_passed_to_arm(self, tmp_path: Path):
        inj = RecordingInjector()
        _make_runner(tmp_path, "a", attack=inj, target_uav="uav_1").run()
        assert inj.context is not None
        assert inj.context.target_uav == "uav_1"
        assert inj.context.target_sysid == 2

    def test_default_target_first_uav(self, tmp_path: Path):
        inj = RecordingInjector()
        _make_runner(tmp_path, "a", attack=inj).run()
        assert inj.context.target_uav == "uav_0"

    def test_cleanup_runs_even_on_fire_failure(self, tmp_path: Path):
        inj = RecordingInjector(fire_raises=True)
        result = _make_runner(tmp_path, "a", attack=inj).run()
        # fire raised, but cleanup still ran
        assert inj.armed
        assert inj.cleaned
        # And the error is surfaced in the result
        assert result.error is not None
        assert "fire failed" in result.error

    def test_cleanup_runs_even_on_arm_failure(self, tmp_path: Path):
        inj = RecordingInjector(arm_raises=True)
        result = _make_runner(tmp_path, "a", attack=inj).run()
        # arm raised, fire never ran
        assert not inj.armed
        assert not inj.fired
        # cleanup still ran
        assert inj.cleaned
        assert result.error is not None


# ---------------------------------------------------------------------------
# Lifecycle: clean stop
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_fleet_components_stopped_after_run(self, tmp_path: Path):
        runner = _make_runner(tmp_path, "c")
        runner.run()
        # After run, every monitor should have stopped (no live threads)
        for mon in runner._fleet.monitors:
            assert mon._started is False
        # Every coordinator stopped
        for coord in runner._fleet.coordinators:
            assert coord._started is False

    def test_monitor_stats_in_result(self, tmp_path: Path):
        result = _make_runner(tmp_path, "b").run()
        assert len(result.monitor_stats) == 3
        # Each is a dict with expected keys (independent of values)
        for s in result.monitor_stats:
            assert "telemetry_seen" in s
            assert "security_emitted" in s

    def test_no_error_field_on_clean_run(self, tmp_path: Path):
        result = _make_runner(tmp_path, "a").run()
        assert result.error is None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_negative_attack_at_rejected(self, tmp_path: Path):
        arch_cfg = load_architecture_config(CONFIG_DIR / "architecture_a.yaml")
        exp_cfg = load_experiment_config(CONFIG_DIR / "experiment.yaml")
        with pytest.raises(ValueError, match="attack_at_sec"):
            ExperimentRunner(
                arch_cfg=arch_cfg,
                exp_cfg=exp_cfg,
                run_id="test",
                log_root=tmp_path,
                attack_at_sec=-1.0,
            )
