"""Tests for runners.experiment.

Uses fake connection + NoOp mesh + NullMissionRunner so the lifecycle
runs end-to-end in seconds without PX4.
"""

from __future__ import annotations

import json
import threading
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


class FakeMessage:
    def __init__(self, type_name: str, sysid: int, fields: dict):
        self._type = type_name
        self._sysid = sysid
        self._fields = dict(fields)

    def get_type(self): return self._type
    def get_srcSystem(self): return self._sysid
    def to_dict(self): return dict(self._fields)


class EstimatorConnection:
    """Emits a steady ESTIMATOR_STATUS stream for one UAV.

    The default FakeConnection returns nothing, so no telemetry ever
    reaches the detectors and the residual series would be empty — which
    would make the estimator_series tests below vacuously pass. This one
    produces the message that actually carries pos_horiz_ratio.

    `sysid` must match the listener's expected_sysid or the listener
    filters everything out; the factory below reads it from the real
    config rather than parsing the endpoint string.
    """

    def __init__(self, *, sysid: int, ratio: float) -> None:
        self._sysid = sysid
        self._ratio = ratio
        self._closed = False
        self._lock = threading.Lock()
        self.sent = 0

    def recv_match(self, type=None, blocking: bool = True, timeout: float = 1.0):
        if self._closed:
            return None
        allowed = None
        if type is not None:
            allowed = {type} if isinstance(type, str) else set(type)
        if allowed is not None and "ESTIMATOR_STATUS" not in allowed:
            time.sleep(min(timeout, 0.05))
            return None
        # Pace roughly like PX4 SITL rather than spinning: a few dozen
        # samples across a sub-second test run is plenty.
        time.sleep(0.02)
        with self._lock:
            self.sent += 1
        return FakeMessage(
            "ESTIMATOR_STATUS",
            self._sysid,
            {"pos_horiz_ratio": self._ratio, "vel_ratio": 0.31},
        )

    def close(self) -> None:
        self._closed = True


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
    estimator_ratio: float | None = None,
) -> ExperimentRunner:
    arch_cfg = load_architecture_config(CONFIG_DIR / f"architecture_{arch}.yaml")
    exp_cfg = load_experiment_config(CONFIG_DIR / "experiment.yaml")

    conn_factory = _fake_conn_factory
    if estimator_ratio is not None:
        sysid_by_endpoint = {
            e.endpoint: e.sysid for e in exp_cfg.telemetry.endpoints
        }

        def conn_factory(endpoint: str):  # noqa: F811
            return EstimatorConnection(
                sysid=sysid_by_endpoint[endpoint], ratio=estimator_ratio
            )

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
        connection_factory=conn_factory,
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


# ---------------------------------------------------------------------------
# Raw EKF residual series (OPEN-3)
#
# Monitors log events, not telemetry, so a detector that never fires
# leaves no trace of what it saw — which is why OPEN-3 cannot be answered
# from the runs on disk. run_summary.json is the only committed artefact,
# so the evidence has to reach it.
# ---------------------------------------------------------------------------


class TestEstimatorSeries:
    def test_series_recorded_per_uav(self, tmp_path: Path):
        result = _make_runner(
            tmp_path, "c", attack=RecordingInjector(), estimator_ratio=1.5
        ).run()
        es = result.estimator_series
        assert es is not None
        assert set(es["uavs"]) == {"uav_0", "uav_1", "uav_2"}
        assert es["target_uav"] == "uav_0"
        assert es["msg_type"] == "ESTIMATOR_STATUS"
        assert es["uavs"]["uav_0"]["n"] > 0

    def test_breach_is_visible_in_the_series(self, tmp_path: Path):
        # The discriminator OPEN-3 needs: a sustained breach means the
        # signature was present, so a non-detection would be a sustain-rule
        # question rather than an injection question.
        result = _make_runner(
            tmp_path, "b", attack=RecordingInjector(), estimator_ratio=1.5
        ).run()
        u = result.estimator_series["uavs"]["uav_0"]
        assert u["peak"] == pytest.approx(1.5)
        assert u["n_above_threshold"] > 0
        assert u["max_consecutive_above"] > 0

    def test_quiet_run_shows_no_breach(self, tmp_path: Path):
        # The other side of the discriminator: the ratio never crossed, so
        # the injection produced no signature at all.
        result = _make_runner(
            tmp_path, "b", attack=RecordingInjector(), estimator_ratio=0.006
        ).run()
        u = result.estimator_series["uavs"]["uav_0"]
        assert u["n_above_threshold"] == 0
        assert u["max_consecutive_above"] == 0
        assert u["first_cross_t_rel_sec"] is None

    def test_anchored_to_the_injection_instant(self, tmp_path: Path):
        # Monitors start before the attack, so the series must straddle
        # t=0. A baseline-free series cannot show a ramp onset.
        result = _make_runner(
            tmp_path, "a", attack=RecordingInjector(), estimator_ratio=0.5
        ).run()
        es = result.estimator_series
        t_rel = es["uavs"]["uav_0"]["t_rel_sec"]
        assert min(t_rel) < 0.0
        assert max(t_rel) > 0.0
        assert es["attack_at_wall"] == pytest.approx(
            es["attack_at_wall"], abs=0.0
        )

    def test_recorded_on_baseline_too(self, tmp_path: Path):
        result = _make_runner(tmp_path, "a", estimator_ratio=0.006).run()
        assert result.attack_name == "none"
        assert result.estimator_series["uavs"]["uav_0"]["n"] > 0

    @pytest.mark.parametrize("arch", ["a", "b", "c"])
    def test_recorded_in_every_architecture(self, arch: str, tmp_path: Path):
        result = _make_runner(
            tmp_path, arch, attack=RecordingInjector(), estimator_ratio=1.5
        ).run()
        assert set(result.estimator_series["uavs"]) == {
            "uav_0", "uav_1", "uav_2"
        }

    def test_telemetry_logs_excluded_from_merged(self, tmp_path: Path):
        # ~1 Hz x 160 s x 3 UAVs of raw MAVLink would bury the event
        # stream the metrics layer reads.
        result = _make_runner(
            tmp_path, "a", attack=RecordingInjector(), estimator_ratio=1.5
        ).run()
        log_dir = Path(result.log_dir)
        telemetry_files = sorted(log_dir.glob("telemetry_*.jsonl"))
        assert len(telemetry_files) == 3
        assert sum(len(p.read_text().splitlines()) for p in telemetry_files) > 0

        merged = read_jsonl(Path(result.merged_log))
        assert all(e.event_type != "telemetry" for e in merged)

    def test_no_anchor_means_no_series(self, tmp_path: Path):
        # arm() raises before the injection instant is captured, so there
        # is no t=0 to anchor to and no series can be honestly reported.
        result = _make_runner(
            tmp_path,
            "a",
            attack=RecordingInjector(arm_raises=True),
            estimator_ratio=1.5,
        ).run()
        assert result.estimator_series is None
        assert result.flight_at_attack is None

    def test_in_summary_json(self, tmp_path: Path):
        result = _make_runner(
            tmp_path, "a", attack=RecordingInjector(), estimator_ratio=1.5
        ).run()
        data = json.loads(
            (Path(result.log_dir) / "run_summary.json").read_text()
        )
        es = data["estimator_series"]
        assert es["threshold"] == 1.0
        assert es["uavs"]["uav_0"]["peak"] == 1.5
        assert isinstance(es["uavs"]["uav_0"]["pos_horiz_ratio"], list)

    def test_series_never_fails_a_run(self, tmp_path: Path):
        runner = _make_runner(
            tmp_path, "a", attack=RecordingInjector(), estimator_ratio=1.5
        )
        runner._compute_estimator_series = lambda _d: (_ for _ in ()).throw(
            RuntimeError("boom")
        )
        result = runner.run()
        assert result.estimator_series is None
        assert result.error is not None
        assert "estimator_series" in result.error
        assert Path(result.merged_log).exists()


# ---------------------------------------------------------------------------
# True-vs-believed divergence (item 2B)
#
# estimator_series answers "did the filter notice?"; belief_divergence
# answers "how far off was the belief, in metres?" — Gazebo truth paired
# against PX4's LOCAL_POSITION_NED. It rides the same per-monitor
# telemetry logs, so these wiring tests only prove the pipe reaches
# run_summary.json; the axis/pairing maths is pinned in
# test_belief_divergence.py.
# ---------------------------------------------------------------------------


class BeliefConnection:
    """Emits a steady LOCAL_POSITION_NED stream for one UAV.

    Believes it is at a fixed (north, east, down). Paired against a
    ground-truth recorder that flies the UAV to gz.y=30 (== 30 m north of
    its spawn), a belief of north=0 reads as 30 m of horizontal
    divergence — enough to prove the axis map survives the round trip
    through the runner.
    """

    def __init__(
        self, *, sysid: int, north: float = 0.0, east: float = 0.0,
        down: float = -20.0,
    ) -> None:
        self._sysid = sysid
        self._n = north
        self._e = east
        self._d = down
        self._closed = False
        self.sent = 0

    def recv_match(self, type=None, blocking: bool = True, timeout: float = 1.0):
        if self._closed:
            return None
        allowed = None
        if type is not None:
            allowed = {type} if isinstance(type, str) else set(type)
        if allowed is not None and "LOCAL_POSITION_NED" not in allowed:
            time.sleep(min(timeout, 0.05))
            return None
        time.sleep(0.02)
        self.sent += 1
        return FakeMessage(
            "LOCAL_POSITION_NED",
            self._sysid,
            {"x": self._n, "y": self._e, "z": self._d},
        )

    def close(self) -> None:
        self._closed = True


class FakeBeliefRecorder:
    """Ground-truth trajectory with a pre-liftoff block (for the EKF
    origin) followed by flight to gz.y=30 around 'now' (for pairing).

    Ground block sits at wall now-3.0.. so it never falls in the belief
    stream's live window; only the flight samples pair.
    """

    def __init__(self, out_path: Path, *, gz_y_flight: float = 30.0) -> None:
        self.out_path = out_path
        self.stopped = False
        self._gz_y = gz_y_flight
        self.stats = {"samples_written": 0}

    def start(self) -> None:
        now = time.time()
        lines = []
        # pre-liftoff ground block: spawn at gz (10*u, 0, 0)
        for i in range(3):
            t = now - 3.0 + i * 0.1
            for u in range(3):
                lines.append(json.dumps({
                    "t_wall": t, "t_sim": 10.0 + i * 0.1,
                    "uav_id": f"uav_{u}", "x": 10.0 * u, "y": 0.0, "z": 0.0,
                }))
        # flight around now: gz (10*u, gz_y, 20) -> 30 m north of spawn
        for i in range(31):
            t = now - 1.0 + i * 0.1
            for u in range(3):
                lines.append(json.dumps({
                    "t_wall": t, "t_sim": 100.0 + i * 0.1,
                    "uav_id": f"uav_{u}", "x": 10.0 * u, "y": self._gz_y,
                    "z": 20.0,
                }))
        self.out_path.write_text("\n".join(lines) + "\n")
        self.stats["samples_written"] = len(lines)

    def stop(self) -> None:
        self.stopped = True


def _belief_runner(tmp_path: Path, arch: str = "a", *, attack=None):
    """A runner whose connections emit LOCAL_POSITION_NED, with the
    ground-truth belief recorder wired in."""
    arch_cfg = load_architecture_config(CONFIG_DIR / f"architecture_{arch}.yaml")
    exp_cfg = load_experiment_config(CONFIG_DIR / "experiment.yaml")
    sysid_by_endpoint = {
        e.endpoint: e.sysid for e in exp_cfg.telemetry.endpoints
    }

    def conn_factory(endpoint: str):
        return BeliefConnection(sysid=sysid_by_endpoint[endpoint])

    runner = ExperimentRunner(
        arch_cfg=arch_cfg, exp_cfg=exp_cfg, run_id="test", log_root=tmp_path,
        attack_injector=attack,
        mission_runner=NullMissionRunner(duration_sec=0.5),
        attack_at_sec=0.1, observation_after_attack_sec=0.2,
        connection_factory=conn_factory, mesh_factory=_noop_mesh_factory,
    )
    runner._trajectory_recorder_factory = lambda p: FakeBeliefRecorder(p)
    return runner


class TestBeliefDivergence:
    def test_divergence_recorded_per_uav(self, tmp_path: Path):
        result = _belief_runner(
            tmp_path, "c", attack=RecordingInjector()
        ).run()
        bd = result.belief_divergence
        assert bd is not None
        assert set(bd["uavs"]) == {"uav_0", "uav_1", "uav_2"}
        assert bd["target_uav"] == "uav_0"
        assert bd["belief_msg_type"] == "LOCAL_POSITION_NED"

    def test_axis_map_survives_the_round_trip(self, tmp_path: Path):
        # 30 m north in Gazebo, belief frozen at north=0 -> 30 m horizontal
        # divergence, and the spawn spacing (0/5/10... here 0/10/20 m east)
        # must be removed by the measured origin, not leak in as false
        # divergence.
        result = _belief_runner(
            tmp_path, "a", attack=RecordingInjector()
        ).run()
        u0 = result.belief_divergence["uavs"]["uav_0"]
        assert u0["origin"] is not None
        assert u0["n"] > 0
        assert u0["peak_horiz_m"] == pytest.approx(30.0, abs=0.5)
        # uav_2 spawns 20 m east; a resolver that ignored spawn offset
        # would add 20 m here. It must still read ~30, not ~36.
        u2 = result.belief_divergence["uavs"]["uav_2"]
        assert u2["peak_horiz_m"] == pytest.approx(30.0, abs=0.5)

    def test_no_recorder_means_none(self, tmp_path: Path):
        # No ground truth -> nothing to diverge from. None, not an empty
        # dict pretending to a measurement.
        arch_cfg = load_architecture_config(
            CONFIG_DIR / "architecture_a.yaml"
        )
        exp_cfg = load_experiment_config(CONFIG_DIR / "experiment.yaml")
        sysid_by_endpoint = {
            e.endpoint: e.sysid for e in exp_cfg.telemetry.endpoints
        }
        runner = ExperimentRunner(
            arch_cfg=arch_cfg, exp_cfg=exp_cfg, run_id="test",
            log_root=tmp_path, attack_injector=RecordingInjector(),
            mission_runner=NullMissionRunner(duration_sec=0.5),
            attack_at_sec=0.1, observation_after_attack_sec=0.2,
            connection_factory=lambda ep: BeliefConnection(
                sysid=sysid_by_endpoint[ep]
            ),
            mesh_factory=_noop_mesh_factory,
        )
        result = runner.run()
        assert result.belief_divergence is None

    def test_recorded_on_baseline_too(self, tmp_path: Path):
        # Baseline has no attack, but it carries the NOMINAL injection
        # instant and is validated by the identical procedure as the
        # attack runs (thesis 3.5.5) — same as estimator_series and
        # flight_check. So the anchor is "attack" here too; the
        # "first_sample" fallback only fires when the instant was never
        # captured, which is covered directly in test_belief_divergence.py.
        # This is the condition the axis map and EKF noise floor are
        # validated on (PROJECT_STATE 2A calibration).
        result = _belief_runner(tmp_path, "a").run()
        assert result.attack_name == "none"
        bd = result.belief_divergence
        assert bd["attack_at_wall"] is not None
        assert bd["uavs"]["uav_0"]["anchor"] == "attack"
        assert bd["uavs"]["uav_0"]["n"] > 0

    def test_in_summary_json(self, tmp_path: Path):
        result = _belief_runner(
            tmp_path, "a", attack=RecordingInjector()
        ).run()
        data = json.loads(
            (Path(result.log_dir) / "run_summary.json").read_text()
        )
        bd = data["belief_divergence"]
        assert bd["belief_msg_type"] == "LOCAL_POSITION_NED"
        assert bd["truth_frame"] == "gazebo_world_enu_z_up"
        assert isinstance(
            bd["uavs"]["uav_0"]["divergence_horiz_m"], list
        )

    def test_never_fails_a_run(self, tmp_path: Path):
        # A summary field is not worth losing a 160 s flight over — same
        # contract as flight_check and estimator_series.
        runner = _belief_runner(tmp_path, "a", attack=RecordingInjector())
        runner._compute_belief_divergence = lambda _d: (
            _ for _ in ()
        ).throw(RuntimeError("boom"))
        result = runner.run()
        assert result.belief_divergence is None
        assert result.error is not None
        assert "belief_divergence" in result.error
        assert Path(result.merged_log).exists()
