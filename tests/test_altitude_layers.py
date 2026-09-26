"""Vertical separation of the formation (review stage 3)."""
import asyncio
import pathlib
import sys

import pytest

from core.config import ConfigError, MissionConfig, Waypoint, load_experiment_config
from metrics.flight_check import mission_plan_summary
from tests.test_mission_mavsdk import FakeDroneController
from runners.mission_mavsdk import MavsdkMissionRunner

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import run_batch  # noqa: E402
import run_one  # noqa: E402

CONFIGS = pathlib.Path(__file__).resolve().parent.parent / "configs"
WPS = [Waypoint(north_m=30.0, east_m=0.0, alt_m=20.0),
       Waypoint(north_m=30.0, east_m=30.0, alt_m=20.0)]


def _runner(offsets):
    made = []

    def factory(ep):
        c = FakeDroneController(ep)
        made.append(c)
        return c

    r = MavsdkMissionRunner(
        endpoints=[f"udp://:{14540 + i}" for i in range(3)], waypoints=WPS,
        controller_factory=factory, takeoff_altitude_m=15.0,
        uav_ids=["uav_0", "uav_1", "uav_2"], alt_offsets_m=offsets)
    return r, made


def test_default_is_single_layer_v1():
    cfg = load_experiment_config(CONFIGS / "experiment.yaml")
    assert cfg.mission.altitude_layer_step_m == 0.0
    r, made = _runner(None)
    asyncio.run(r.start())
    assert [c.takeoff_alt for c in made] == [15.0, 15.0, 15.0]
    assert {it.relative_alt_m for c in made for it in c.uploaded} == {20.0}


def test_offsets_applied_to_takeoff_and_every_waypoint():
    r, made = _runner([0.0, 5.0, 10.0])
    asyncio.run(r.start())
    assert [c.takeoff_alt for c in made] == [15.0, 20.0, 25.0]
    assert [sorted({it.relative_alt_m for it in c.uploaded}) for c in made] == \
        [[20.0], [25.0], [30.0]]


@pytest.mark.parametrize("bad", [[0.0, 5.0], [0.0, -5.0, 10.0]])
def test_bad_offsets_rejected(bad):
    with pytest.raises(ValueError):
        _runner(bad)


def test_negative_step_rejected():
    with pytest.raises(ConfigError, match="altitude_layer_step_m"):
        MissionConfig(type="coordinated_waypoint", duration_sec=10.0,
                      waypoints=tuple(WPS), altitude_layer_step_m=-1.0)


def test_cli_override_and_provenance():
    cfg = load_experiment_config(CONFIGS / "experiment.yaml")
    assert run_one.apply_altitude_layer_override(cfg, step=None) is cfg
    cfg5 = run_one.apply_altitude_layer_override(cfg, step=5.0)
    assert cfg5.mission.altitude_layer_step_m == 5.0
    assert cfg5.mission.waypoints == cfg.mission.waypoints  # route unchanged
    assert mission_plan_summary(cfg5.mission)["altitude_layer_step_m"] == 5.0
    assert mission_plan_summary(cfg.mission)["altitude_layer_step_m"] == 0.0


def test_target_uav0_never_moved_by_the_builder():
    cfg5 = run_one.apply_altitude_layer_override(
        load_experiment_config(CONFIGS / "experiment.yaml"), step=5.0)
    runner = run_one.build_mavsdk_mission(cfg5, takeoff_altitude_m=15.0)
    assert runner._alt_offsets == [0.0, 5.0, 10.0]
    assert runner._uav_ids[0] == "uav_0"


def test_flags_parse_and_pass_through():
    assert run_one.parse_args(["--arch", "c", "--attack", "none",
                               "--altitude-layer-step", "5"]).altitude_layer_step == 5.0
    assert run_batch.parse_args([]).altitude_layer_step is None
    assert run_batch.parse_args(["--altitude-layer-step", "5"]).altitude_layer_step == 5.0
