"""Pipeline wiring of the recovery policies (review stage 3a-2).

Covers the factory (handler registration, decider policy from config),
the mission-backed zero-velocity runner (same-loop and cross-loop paths),
the run_one / run_batch CLI overrides and HOLD_ACTIONS. The injection of
the runner inside ExperimentRunner.start() is exercised live by the
stage-3b pilot, not here.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import threading
from dataclasses import replace

import pytest

from core.config import (
    DEFAULT_RECOVERY_POLICY,
    VALID_RECOVERY_POLICIES,
    ConfigError,
    load_architecture_config,
    load_experiment_config,
)
from decision.recovery import RecoveryAction
from enforcement.handlers import ZeroVelocityHoldHandler
from metrics.physical_outcomes import HOLD_ACTIONS
from runners.experiment import RunResult
from runners.factory import build_fleet
from runners.mission_mavsdk import DroneController, MissionVelocityHoldRunner

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import run_batch  # noqa: E402
import run_one  # noqa: E402

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "configs"


class _Conn:
    def recv_match(self, **_k):
        return None

    def close(self):
        pass


class _Mesh:
    def start(self): pass
    def stop(self): pass
    def publish(self, e): pass
    def subscribe(self, t, cb): pass


def _fleet(tmp_path, arch="c", policy=None):
    cfg = load_architecture_config(CONFIG_DIR / f"architecture_{arch}.yaml")
    if policy is not None:
        cfg = replace(cfg, recovery=replace(cfg.recovery, policy=policy))
    return build_fleet(
        arch_cfg=cfg,
        exp_cfg=load_experiment_config(CONFIG_DIR / "experiment.yaml"),
        run_id="t",
        log_root=tmp_path,
        connection_factory=lambda _e: _Conn(),
        mesh_factory=(lambda *a: _Mesh()) if arch == "c" else None,
    )


# --- factory --------------------------------------------------------------


class TestFactory:
    def test_c_registers_zero_velocity_handler_per_uav(self, tmp_path):
        fleet = _fleet(tmp_path)
        assert len(fleet.velocity_hold_handlers) == 3
        for coord, h in zip(fleet.coordinators, fleet.velocity_hold_handlers):
            handlers = coord._executor._handlers
            assert handlers[RecoveryAction.HOLD_ZERO_VELOCITY] is h
            assert isinstance(h, ZeroVelocityHoldHandler)
            assert h.target_uav == coord._target_uav
            assert h.runner is None  # injected by ExperimentRunner only

    def test_default_decider_policy_is_proportionate(self, tmp_path):
        for coord in _fleet(tmp_path).coordinators:
            assert coord._decider.policy == DEFAULT_RECOVERY_POLICY

    @pytest.mark.parametrize("policy", ["trust_aware", "detect_only"])
    def test_decider_policy_comes_from_config(self, tmp_path, policy):
        for coord in _fleet(tmp_path, policy=policy).coordinators:
            assert coord._decider.policy == policy

    @pytest.mark.parametrize("arch", ["a", "b"])
    def test_a_b_have_no_velocity_hold_handlers(self, tmp_path, arch):
        assert _fleet(tmp_path, arch=arch).velocity_hold_handlers == []


# --- mission-backed runner ------------------------------------------------


class _FakeController(DroneController):
    def __init__(self):
        self.calls = 0
        self.loop = None

    async def connect(self): pass
    async def get_home_position(self): return (0.0, 0.0, 0.0)
    async def arm_and_takeoff(self, *, altitude_m): pass
    async def upload_mission(self, items): pass
    async def start_mission(self): pass
    async def is_mission_complete(self): return False
    async def return_to_launch(self): pass
    async def disconnect(self): pass

    async def hold_zero_velocity(self):
        self.calls += 1
        self.loop = asyncio.get_running_loop()


class _FakeMissionRunner:
    def __init__(self, c):
        self._c = c

    def controller_for(self, uav_id):
        assert uav_id == "uav_0"
        return self._c


class TestMissionVelocityHoldRunner:
    def test_same_loop_awaits_directly(self):
        c = _FakeController()
        r = MissionVelocityHoldRunner(_FakeMissionRunner(c), "uav_0")
        asyncio.run(r.hold_zero_velocity())
        assert c.calls == 1

    def test_cross_loop_runs_on_main_loop(self):
        c = _FakeController()
        main = asyncio.new_event_loop()
        t = threading.Thread(target=main.run_forever, daemon=True)
        t.start()
        try:
            r = MissionVelocityHoldRunner(
                _FakeMissionRunner(c), "uav_0", main_loop=main
            )
            asyncio.run(r.hold_zero_velocity())  # a different loop
            assert c.calls == 1
            assert c.loop is main  # executed where the System lives
        finally:
            main.call_soon_threadsafe(main.stop)
            t.join(timeout=2)
            main.close()

    def test_base_controller_does_not_pretend(self):
        class Bare(_FakeController):
            hold_zero_velocity = DroneController.hold_zero_velocity
        with pytest.raises(NotImplementedError):
            asyncio.run(Bare().hold_zero_velocity())


# --- CLI overrides ----------------------------------------------------------


class TestCli:
    def _cfg(self, arch):
        return load_architecture_config(CONFIG_DIR / f"architecture_{arch}.yaml")

    def test_none_leaves_config_untouched(self):
        cfg = self._cfg("c")
        assert run_one.apply_recovery_policy_override(cfg, policy=None) is cfg

    @pytest.mark.parametrize("policy", sorted(VALID_RECOVERY_POLICIES))
    def test_override_on_c(self, policy):
        cfg = run_one.apply_recovery_policy_override(self._cfg("c"), policy=policy)
        assert cfg.recovery.policy == policy
        assert cfg.recovery.enabled

    @pytest.mark.parametrize("policy", ["trust_aware", "detect_only"])
    def test_override_rejected_on_a(self, policy):
        with pytest.raises(ConfigError, match="requires recovery enabled"):
            run_one.apply_recovery_policy_override(self._cfg("a"), policy=policy)

    def test_unknown_policy_rejected(self):
        with pytest.raises(ConfigError):
            run_one.apply_recovery_policy_override(self._cfg("c"), policy="x")

    def test_run_one_flag(self):
        a = run_one.parse_args(["--arch", "c", "--attack", "gps_spoofing",
                                "--recovery-policy", "trust_aware"])
        assert a.recovery_policy == "trust_aware"
        assert run_one.parse_args(["--arch", "c", "--attack", "none"]).recovery_policy is None

    def test_run_batch_flag_and_choices_match_config(self):
        assert run_batch.parse_args([]).recovery_policy is None
        assert run_batch.parse_args(
            ["--recovery-policy", "detect_only"]).recovery_policy == "detect_only"
        for p in VALID_RECOVERY_POLICIES:
            run_batch.parse_args(["--recovery-policy", p])


# --- summary + metrics ------------------------------------------------------


def test_run_result_has_recovery_settings_field():
    assert "recovery_settings" in RunResult.__dataclass_fields__


def test_zero_velocity_hold_counts_as_hold_action():
    assert HOLD_ACTIONS == frozenset({"mode_loiter", "hold_zero_velocity"})
