"""Tests for runners.experiment.

Uses fake connection + NoOp mesh + NullMissionRunner so the lifecycle
runs end-to-end in seconds without PX4.
"""

from __future__ import annotations

import json
import time
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


# ---------------------------------------------------------------------------
# Ground-truth trajectory recorder wiring
# ---------------------------------------------------------------------------


class FakeRecorder:
    """Stands in for TrajectoryRecorder: writes one pose-shaped line so we
    can assert it never leaks into merged.jsonl."""

    def __init__(self, out_path: Path, *, start_raises: bool = False) -> None:
        self.out_path = out_path
        self.started = False
        self.stopped = False
        self._start_raises = start_raises
        self.stats = {"samples_written": 0}

    def start(self) -> None:
        if self._start_raises:
            raise RuntimeError("gz missing")
        self.started = True
        self.out_path.write_text(
            json.dumps({"t_wall": 1.0, "uav_id": "uav_0", "x": 1.0}) + "\n"
        )
        self.stats["samples_written"] = 1

    def stop(self) -> None:
        self.stopped = True


class TestTrajectoryWiring:
    def test_recorder_started_and_stopped(self, tmp_path: Path):
        made: list[FakeRecorder] = []

        def factory(out_path: Path) -> FakeRecorder:
            r = FakeRecorder(out_path)
            made.append(r)
            return r

        runner = _make_runner(tmp_path, "a")
        runner._trajectory_recorder_factory = factory
        runner.run()
        assert len(made) == 1
        assert made[0].started and made[0].stopped
        assert made[0].out_path.name == "trajectory.jsonl"

    def test_trajectory_excluded_from_merged(self, tmp_path: Path):
        runner = _make_runner(tmp_path, "a")
        runner._trajectory_recorder_factory = lambda p: FakeRecorder(p)
        result = runner.run()
        traj = Path(result.log_dir) / "trajectory.jsonl"
        assert traj.exists()  # recorder really wrote it
        # Pose samples must never enter the event log.
        merged_text = Path(result.merged_log).read_text()
        assert '"uav_id": "uav_0", "x": 1.0' not in merged_text
        assert "trajectory" not in merged_text

    def test_stats_in_summary(self, tmp_path: Path):
        runner = _make_runner(tmp_path, "a")
        runner._trajectory_recorder_factory = lambda p: FakeRecorder(p)
        result = runner.run()
        assert result.trajectory_stats == {"samples_written": 1}
        data = json.loads((Path(result.log_dir) / "run_summary.json").read_text())
        assert data["trajectory_stats"]["samples_written"] == 1

    def test_no_recorder_by_default(self, tmp_path: Path):
        result = _make_runner(tmp_path, "a").run()
        assert result.trajectory_stats is None
        assert not (Path(result.log_dir) / "trajectory.jsonl").exists()

    def test_recorder_failure_does_not_fail_run(self, tmp_path: Path):
        # A dead gz must degrade to "no trajectory", never break a flight.
        runner = _make_runner(tmp_path, "a")
        runner._trajectory_recorder_factory = lambda p: FakeRecorder(
            p, start_raises=True
        )
        result = runner.run()
        assert result.error is None
        assert result.trajectory_stats is None


# ---------------------------------------------------------------------------
# Run validity: mission_plan + flight_at_attack
#
# The point of these fields is that runs_v1/v2 attacked a hovering UAV for
# 120 trials and no artefact of the run said so (OPEN-1 / R7). So the
# tests below are about one thing: a run must state its own validity, and
# must never state it falsely.
# ---------------------------------------------------------------------------


class FakeFlyingRecorder:
    """Writes a fleet-wide ground-truth trajectory around "now".

    Samples span now-1s .. now+2s at 10 Hz, so whatever wall-clock instant
    the attack lands on inside a fast test run, it falls inside the
    check's +/-1 s window. `vx` selects the regime under test: 4.0 is the
    R7 cruise speed, 0.03 is the R7 hover speed.
    """

    def __init__(
        self, out_path: Path, *, vx: float = 4.0, z: float = 20.0
    ) -> None:
        self.out_path = out_path
        self.stopped = False
        self._vx = vx
        self._z = z
        self.stats = {"samples_written": 0}

    def start(self) -> None:
        now = time.time()
        lines = []
        for i in range(31):
            t = now - 1.0 + i * 0.1
            for u in range(3):
                lines.append(
                    json.dumps(
                        {
                            "t_wall": t,
                            "t_sim": 100.0 + i * 0.1,
                            "uav_id": f"uav_{u}",
                            "x": 10.0 * u + self._vx * (i * 0.1),
                            "y": 0.0,
                            "z": self._z,
                        }
                    )
                )
        self.out_path.write_text("\n".join(lines) + "\n")
        self.stats["samples_written"] = len(lines)

    def stop(self) -> None:
        self.stopped = True


class FakeEmptyRecorder:
    """A recorder that ran and captured nothing (dead gz, wrong topic)."""

    def __init__(self, out_path: Path) -> None:
        self.out_path = out_path
        self.stats = {"samples_written": 0}

    def start(self) -> None:
        self.out_path.write_text("")

    def stop(self) -> None:
        pass


class TestMissionPlanInSummary:
    def test_plan_recorded_on_attack_run(self, tmp_path: Path):
        result = _make_runner(
            tmp_path, "c", attack=RecordingInjector()
        ).run()
        plan = result.mission_plan
        assert plan is not None
        assert plan["laps"] >= 4          # the shipped multi-lap route
        assert plan["n_waypoints"] == len(plan["lap_waypoints"]) * plan["laps"]
        assert plan["type"] == "coordinated_waypoint"

    def test_plan_recorded_on_baseline_too(self, tmp_path: Path):
        # The control condition has to be as auditable as the attack runs,
        # or the comparison rests on an unverified assumption.
        result = _make_runner(tmp_path, "a").run()
        assert result.mission_plan is not None
        assert result.mission_plan["n_waypoints"] > 0

    def test_plan_records_the_timing_actually_used(self, tmp_path: Path):
        # Not the yaml default: the runner's effective values, which
        # run_batch/run_one override per run.
        result = _make_runner(tmp_path, "a", attack_at=0.1, obs_after=0.2).run()
        assert result.mission_plan["attack_at_sec"] == pytest.approx(0.1)
        assert result.mission_plan["observation_after_attack_sec"] == (
            pytest.approx(0.2)
        )

    def test_plan_in_summary_json(self, tmp_path: Path):
        result = _make_runner(tmp_path, "a").run()
        data = json.loads(
            (Path(result.log_dir) / "run_summary.json").read_text()
        )
        assert data["mission_plan"]["laps"] >= 4
        assert isinstance(data["mission_plan"]["lap_waypoints"], list)


class TestFlightAtAttack:
    def test_flying_uav_recorded_as_flying(self, tmp_path: Path):
        runner = _make_runner(tmp_path, "c", attack=RecordingInjector())
        runner._trajectory_recorder_factory = lambda p: FakeFlyingRecorder(p)
        result = runner.run()
        fa = result.flight_at_attack
        assert fa is not None
        assert fa["target_uav"] == "uav_0"
        assert fa["target_in_motion"] is True
        assert fa["target_flying"] is True
        assert fa["all_in_motion"] is True
        assert fa["uavs"]["uav_0"]["speed_horiz_mps"] == pytest.approx(
            4.0, rel=0.05
        )

    def test_hovering_uav_is_caught(self, tmp_path: Path):
        # THE regression guard. This is the exact condition that silently
        # invalidated runs_v1, runs_v2 and R1-R4: v ~ 0.03 m/s, airborne,
        # attack lands on a UAV that is not flying its mission.
        runner = _make_runner(tmp_path, "c", attack=RecordingInjector())
        runner._trajectory_recorder_factory = lambda p: FakeFlyingRecorder(
            p, vx=0.03
        )
        result = runner.run()
        fa = result.flight_at_attack
        assert fa["target_in_motion"] is False
        assert fa["target_flying"] is False
        assert fa["uavs"]["uav_0"]["airborne"] is True  # hovering IS airborne

    def test_target_follows_target_uav_argument(self, tmp_path: Path):
        runner = _make_runner(
            tmp_path, "c", attack=RecordingInjector(), target_uav="uav_2"
        )
        runner._trajectory_recorder_factory = lambda p: FakeFlyingRecorder(p)
        result = runner.run()
        assert result.flight_at_attack["target_uav"] == "uav_2"
        assert result.flight_at_attack["target_flying"] is True

    def test_no_recorder_means_not_observed_not_false(self, tmp_path: Path):
        # None must not be readable as "it wasn't flying".
        result = _make_runner(tmp_path, "a", attack=RecordingInjector()).run()
        assert result.flight_at_attack is None

    def test_empty_trajectory_yields_null_verdicts(self, tmp_path: Path):
        # A recorder that ran but saw nothing is a dropout, and must look
        # like one: populated dict, null verdicts, zero samples.
        runner = _make_runner(tmp_path, "a", attack=RecordingInjector())
        runner._trajectory_recorder_factory = lambda p: FakeEmptyRecorder(p)
        result = runner.run()
        fa = result.flight_at_attack
        assert fa is not None
        assert fa["n_samples_total"] == 0
        assert fa["target_in_motion"] is None
        assert fa["uavs"] == {}
        assert result.error is None   # a dropout is not a run failure

    def test_recorded_on_baseline(self, tmp_path: Path):
        # Baseline has no attack, but it has the nominal injection
        # instant, and the control must be validated by the same
        # procedure as the attack runs (thesis 3.5.5).
        runner = _make_runner(tmp_path, "a")
        runner._trajectory_recorder_factory = lambda p: FakeFlyingRecorder(p)
        result = runner.run()
        assert result.attack_name == "none"
        assert result.flight_at_attack["target_flying"] is True

    def test_thresholds_travel_with_the_verdict(self, tmp_path: Path):
        runner = _make_runner(tmp_path, "a", attack=RecordingInjector())
        runner._trajectory_recorder_factory = lambda p: FakeFlyingRecorder(p)
        result = runner.run()
        fa = result.flight_at_attack
        assert fa["motion_threshold_mps"] > 0
        assert fa["airborne_threshold_m"] > 0
        assert fa["window_sec"] > 0
        assert fa["frame"] == "gazebo_world_enu_z_up"

    def test_timestamp_matches_inject_start_event(self, tmp_path: Path):
        # The flight check and MTTD must be anchored to the same instant,
        # or they describe different moments of the same run.
        runner = _make_runner(tmp_path, "a", attack=RecordingInjector())
        runner._trajectory_recorder_factory = lambda p: FakeFlyingRecorder(p)
        result = runner.run()
        events = read_jsonl(Path(result.log_dir) / "attack.jsonl")
        starts = [
            e for e in events
            if e.event_type == "attack" and e.phase == "inject_start"
        ]
        assert len(starts) == 1
        assert result.flight_at_attack["t_wall"] == pytest.approx(
            starts[0].timestamp, abs=1.0
        )

    def test_in_summary_json(self, tmp_path: Path):
        runner = _make_runner(tmp_path, "a", attack=RecordingInjector())
        runner._trajectory_recorder_factory = lambda p: FakeFlyingRecorder(p)
        result = runner.run()
        data = json.loads(
            (Path(result.log_dir) / "run_summary.json").read_text()
        )
        assert data["flight_at_attack"]["target_flying"] is True
        assert set(data["flight_at_attack"]["uavs"]) == {
            "uav_0", "uav_1", "uav_2"
        }

    def test_flight_check_never_fails_a_run(self, tmp_path: Path):
        # A summary field is not worth losing a 160 s flight over.
        class ExplodingRecorder(FakeFlyingRecorder):
            @property
            def stats(self):  # type: ignore[override]
                return {"samples_written": 1}

            @stats.setter
            def stats(self, _v):
                pass

        runner = _make_runner(tmp_path, "a", attack=RecordingInjector())
        runner._trajectory_recorder_factory = lambda p: FakeFlyingRecorder(p)
        runner._compute_flight_at_attack = lambda _d: (_ for _ in ()).throw(
            RuntimeError("boom")
        )
        result = runner.run()
        assert result.flight_at_attack is None
        assert result.error is not None
        assert "flight_check" in result.error
        # The run itself still produced its logs.
        assert Path(result.merged_log).exists()
