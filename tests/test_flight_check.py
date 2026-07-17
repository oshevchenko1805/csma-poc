"""
Tests for metrics.flight_check.

The module answers one question — "was the UAV flying when the attack
fired?" — and the reason it exists is that the answer was wrong for 120
runs and nobody could tell (RESULTS_NOTES OPEN-1 / R7). So these tests
lean hardest on the ways a wrong answer could look right:

  * hover vs flight must not be confusable (the R7 numbers are used
    verbatim);
  * "unmeasurable" must never collapse into "not flying";
  * the Z sign is pinned to measured data, since an inverted frame would
    silently flip every `airborne` flag and read plausible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import MissionConfig, Waypoint
from metrics.flight_check import (
    DEFAULT_AIRBORNE_THRESHOLD_M,
    DEFAULT_MOTION_THRESHOLD_MPS,
    DEFAULT_WINDOW_SEC,
    flight_state_at,
    mission_plan_summary,
    read_trajectory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _samples(
    uav_id: str,
    *,
    t0: float,
    n: int,
    dt: float = 0.2,
    x0: float = 0.0,
    vx: float = 0.0,
    z: float = 20.0,
) -> list[dict]:
    """A UAV moving along +x at `vx` m/s at constant altitude `z`."""
    return [
        {
            "t_wall": t0 + i * dt,
            "uav_id": uav_id,
            "x": x0 + vx * i * dt,
            "y": 0.0,
            "z": z,
        }
        for i in range(n)
    ]


T_ATTACK = 1784215637.0


def _fleet(vx: float, z: float = 20.0) -> list[dict]:
    out: list[dict] = []
    for i in range(3):
        out += _samples(
            f"uav_{i}", t0=T_ATTACK - 1.0, n=11, vx=vx, z=z, x0=10.0 * i
        )
    return out


# ---------------------------------------------------------------------------
# The core discrimination: hover vs mission flight
# ---------------------------------------------------------------------------


class TestHoverVsFlight:
    """The exact confusion that invalidated runs_v1/v2."""

    def test_cruise_reads_in_motion(self):
        # R7 measured v = 2.7-5.1 m/s under mission flight.
        res = flight_state_at(_fleet(vx=4.0), T_ATTACK, target_uav="uav_0")
        assert res["target_in_motion"] is True
        assert res["target_flying"] is True
        assert res["all_in_motion"] is True
        assert res["uavs"]["uav_0"]["speed_horiz_mps"] == pytest.approx(4.0)

    def test_hover_reads_not_in_motion(self):
        # R7 measured v ~ 0.03 m/s while hovering at home. This is the
        # case that must never again be mistaken for a flying UAV.
        res = flight_state_at(_fleet(vx=0.03), T_ATTACK, target_uav="uav_0")
        assert res["target_in_motion"] is False
        assert res["target_flying"] is False
        assert res["uavs"]["uav_0"]["airborne"] is True  # hovering IS airborne

    def test_on_ground_reads_not_airborne(self):
        res = flight_state_at(
            _fleet(vx=0.0, z=-0.013), T_ATTACK, target_uav="uav_0"
        )
        assert res["uavs"]["uav_0"]["airborne"] is False
        assert res["target_flying"] is False

    def test_airborne_and_in_motion_are_independent(self):
        # Taxiing on the ground: moving but not airborne.
        res = flight_state_at(
            _fleet(vx=4.0, z=0.05), T_ATTACK, target_uav="uav_0"
        )
        u = res["uavs"]["uav_0"]
        assert u["in_motion"] is True
        assert u["airborne"] is False
        assert u["flying"] is False


# ---------------------------------------------------------------------------
# Frame — measured, not assumed
# ---------------------------------------------------------------------------


class TestFrame:
    def test_z_up_positive_altitude_is_airborne(self):
        # Verified live: runs_v3/run_C_gps_spoofing_r16_* uav_0 reads
        # z = +19.81 / +20.21 at a 20 m cruise. Gazebo world frame is
        # ENU (Z up), so alt_m = z with no sign flip. If anyone "fixes"
        # this to NED, this test fails instead of a campaign silently
        # recording every flying UAV as grounded.
        res = flight_state_at(_fleet(vx=4.0, z=19.81), T_ATTACK)
        assert res["uavs"]["uav_0"]["alt_m"] == pytest.approx(19.81)
        assert res["uavs"]["uav_0"]["airborne"] is True

    def test_frame_recorded_in_output(self):
        res = flight_state_at(_fleet(vx=4.0), T_ATTACK)
        assert res["frame"] == "gazebo_world_enu_z_up"


# ---------------------------------------------------------------------------
# Unmeasurable is not False
# ---------------------------------------------------------------------------


class TestMissingData:
    def test_no_attack_time_returns_none(self):
        # Baseline runs have no injection instant; the question does not
        # apply and must not be answered.
        assert flight_state_at(_fleet(vx=4.0), None) is None

    def test_no_samples_yields_none_not_false(self):
        res = flight_state_at([], T_ATTACK, target_uav="uav_0")
        assert res is not None
        assert res["uavs"] == {}
        assert res["target_in_motion"] is None
        assert res["all_in_motion"] is None
        assert res["n_samples_total"] == 0

    def test_samples_outside_window_yield_none(self):
        far = _samples("uav_0", t0=T_ATTACK + 60.0, n=10, vx=4.0)
        res = flight_state_at(far, T_ATTACK, target_uav="uav_0")
        u = res["uavs"]["uav_0"]
        assert u["n_samples"] == 0
        assert u["in_motion"] is None
        assert u["speed_horiz_mps"] is None

    def test_single_sample_gives_position_but_no_speed(self):
        one = _samples("uav_0", t0=T_ATTACK, n=1, z=20.0)
        res = flight_state_at(one, T_ATTACK, target_uav="uav_0")
        u = res["uavs"]["uav_0"]
        assert u["alt_m"] == pytest.approx(20.0)
        assert u["airborne"] is True
        assert u["in_motion"] is None   # cannot derive speed from one point
        assert u["flying"] is None

    def test_fleet_verdict_none_if_any_member_unmeasurable(self):
        data = _samples("uav_0", t0=T_ATTACK - 1.0, n=11, vx=4.0)
        data += _samples("uav_1", t0=T_ATTACK + 60.0, n=11, vx=4.0)
        res = flight_state_at(data, T_ATTACK)
        assert res["uavs"]["uav_0"]["in_motion"] is True
        assert res["uavs"]["uav_1"]["in_motion"] is None
        assert res["all_in_motion"] is None   # not False

    def test_unknown_target_yields_none(self):
        res = flight_state_at(_fleet(vx=4.0), T_ATTACK, target_uav="uav_9")
        assert res["target_in_motion"] is None
        assert res["target_flying"] is None


# ---------------------------------------------------------------------------
# Window / thresholds
# ---------------------------------------------------------------------------


class TestWindowAndThresholds:
    def test_window_selects_only_nearby_samples(self):
        data = _samples("uav_0", t0=T_ATTACK - 5.0, n=51, dt=0.2, vx=4.0)
        res = flight_state_at(data, T_ATTACK, window_sec=1.0)
        # +/-1.0 s at 5 Hz => 11 samples.
        assert res["uavs"]["uav_0"]["n_samples"] == 11

    def test_wider_window_takes_more_samples(self):
        data = _samples("uav_0", t0=T_ATTACK - 5.0, n=51, dt=0.2, vx=4.0)
        res = flight_state_at(data, T_ATTACK, window_sec=2.0)
        assert res["uavs"]["uav_0"]["n_samples"] == 21

    def test_thresholds_recorded_next_to_results(self):
        # A threshold baked into code is a hidden assumption; recorded
        # beside its result it is auditable and the booleans are
        # re-derivable from the raw speeds.
        res = flight_state_at(
            _fleet(vx=4.0),
            T_ATTACK,
            motion_threshold_mps=2.0,
            airborne_threshold_m=5.0,
            window_sec=3.0,
        )
        assert res["motion_threshold_mps"] == 2.0
        assert res["airborne_threshold_m"] == 5.0
        assert res["window_sec"] == 3.0

    def test_defaults_recorded_when_not_overridden(self):
        res = flight_state_at(_fleet(vx=4.0), T_ATTACK)
        assert res["window_sec"] == DEFAULT_WINDOW_SEC
        assert res["motion_threshold_mps"] == DEFAULT_MOTION_THRESHOLD_MPS
        assert res["airborne_threshold_m"] == DEFAULT_AIRBORNE_THRESHOLD_M

    def test_threshold_change_flips_verdict_on_same_data(self):
        data = _fleet(vx=1.0)
        assert flight_state_at(data, T_ATTACK, target_uav="uav_0")[
            "target_in_motion"
        ] is True
        assert flight_state_at(
            data, T_ATTACK, target_uav="uav_0", motion_threshold_mps=2.0
        )["target_in_motion"] is False

    def test_zero_window_rejected(self):
        with pytest.raises(ValueError, match="window_sec"):
            flight_state_at(_fleet(vx=4.0), T_ATTACK, window_sec=0)

    def test_negative_window_rejected(self):
        with pytest.raises(ValueError, match="window_sec"):
            flight_state_at(_fleet(vx=4.0), T_ATTACK, window_sec=-1.0)


# ---------------------------------------------------------------------------
# Speed derivation
# ---------------------------------------------------------------------------


class TestSpeed:
    def test_path_length_not_endpoint_displacement(self):
        # A UAV rounding a corner returns near its start. Endpoint
        # displacement would read ~0 m/s and call a flying UAV hovering
        # — the precise failure this module exists to prevent.
        out = []
        for i in range(6):
            out.append(
                {
                    "t_wall": T_ATTACK - 0.5 + i * 0.2,
                    "uav_id": "uav_0",
                    "x": [0.0, 1.0, 2.0, 2.0, 1.0, 0.0][i],
                    "y": 0.0,
                    "z": 20.0,
                }
            )
        res = flight_state_at(out, T_ATTACK, target_uav="uav_0")
        u = res["uavs"]["uav_0"]
        assert u["speed_horiz_mps"] == pytest.approx(4.0 / 1.0)
        assert u["in_motion"] is True

    def test_vertical_motion_excluded_from_horizontal_speed(self):
        # Climbing at 3 m/s with zero ground speed is not "in motion"
        # along the route.
        out = [
            {
                "t_wall": T_ATTACK - 0.5 + i * 0.25,
                "uav_id": "uav_0",
                "x": 0.0,
                "y": 0.0,
                "z": 5.0 + 3.0 * i * 0.25,
            }
            for i in range(5)
        ]
        res = flight_state_at(out, T_ATTACK, target_uav="uav_0")
        u = res["uavs"]["uav_0"]
        assert u["speed_horiz_mps"] == pytest.approx(0.0)
        assert u["speed_mps"] == pytest.approx(3.0)
        assert u["in_motion"] is False

    def test_diagonal_speed(self):
        out = [
            {
                "t_wall": T_ATTACK + i * 0.5,
                "uav_id": "uav_0",
                "x": 3.0 * i * 0.5,
                "y": 4.0 * i * 0.5,
                "z": 20.0,
            }
            for i in range(3)
        ]
        res = flight_state_at(out, T_ATTACK, window_sec=2.0)
        assert res["uavs"]["uav_0"]["speed_horiz_mps"] == pytest.approx(5.0)

    def test_position_taken_from_nearest_sample(self):
        out = [
            {"t_wall": T_ATTACK - 0.9, "uav_id": "uav_0",
             "x": 1.0, "y": 0.0, "z": 20.0},
            {"t_wall": T_ATTACK + 0.1, "uav_id": "uav_0",
             "x": 99.0, "y": 0.0, "z": 20.0},
        ]
        res = flight_state_at(out, T_ATTACK)
        u = res["uavs"]["uav_0"]
        assert u["x"] == pytest.approx(99.0)
        assert u["t_offset_sec"] == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# Serialization — the output is written verbatim into run_summary.json
# ---------------------------------------------------------------------------


class TestSerializable:
    def test_result_is_json_serializable(self):
        res = flight_state_at(_fleet(vx=4.0), T_ATTACK, target_uav="uav_0")
        loaded = json.loads(json.dumps(res))
        assert loaded["target_in_motion"] is True
        assert set(loaded["uavs"]) == {"uav_0", "uav_1", "uav_2"}


# ---------------------------------------------------------------------------
# Reader robustness — a broken trajectory must not fail a run
# ---------------------------------------------------------------------------


class TestReadTrajectory:
    def _write(self, tmp_path: Path, lines: list[str]) -> Path:
        p = tmp_path / "trajectory.jsonl"
        p.write_text("\n".join(lines) + "\n")
        return p

    def test_reads_recorder_shaped_lines(self, tmp_path: Path):
        # Exactly the shape runners/trajectory.py writes.
        line = json.dumps(
            {
                "t_wall": 1784215623.022848,
                "t_sim": 65.856,
                "uav_id": "uav_0",
                "x": 29.464, "y": 25.786, "z": 19.805,
                "qx": 0.15, "qy": -0.05, "qz": 0.16, "qw": 0.97,
            }
        )
        got = read_trajectory(self._write(tmp_path, [line]))
        assert len(got) == 1
        assert got[0]["uav_id"] == "uav_0"
        assert got[0]["z"] == pytest.approx(19.805)

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert read_trajectory(tmp_path / "nope.jsonl") == []

    def test_malformed_and_truncated_lines_skipped(self, tmp_path: Path):
        # The recorder is killed at teardown, so a half-written final
        # line is normal, not exceptional.
        good = json.dumps(
            {"t_wall": 1.0, "uav_id": "uav_0", "x": 1.0, "y": 2.0, "z": 3.0}
        )
        got = read_trajectory(
            self._write(tmp_path, ["not json", "", good, '{"t_wall": 2.0, "uav'])
        )
        assert len(got) == 1

    def test_records_missing_required_fields_skipped(self, tmp_path: Path):
        lines = [
            json.dumps({"uav_id": "uav_0", "x": 1.0}),          # no t_wall
            json.dumps({"t_wall": 1.0, "x": 1.0}),              # no uav_id
            json.dumps({"t_wall": "abc", "uav_id": "uav_0"}),   # bad type
            json.dumps([1, 2, 3]),                              # not an object
            json.dumps({"t_wall": 2.0, "uav_id": "uav_1"}),     # ok, xyz default
        ]
        got = read_trajectory(self._write(tmp_path, lines))
        assert len(got) == 1
        assert got[0]["uav_id"] == "uav_1"
        assert got[0]["x"] == 0.0   # Gazebo omits zero-valued fields

    def test_empty_file_returns_empty(self, tmp_path: Path):
        p = tmp_path / "trajectory.jsonl"
        p.write_text("")
        assert read_trajectory(p) == []

    def test_round_trip_into_flight_state(self, tmp_path: Path):
        lines = [json.dumps(s) for s in _fleet(vx=4.0)]
        got = read_trajectory(self._write(tmp_path, lines))
        res = flight_state_at(got, T_ATTACK, target_uav="uav_0")
        assert res["target_flying"] is True


# ---------------------------------------------------------------------------
# Mission plan
# ---------------------------------------------------------------------------


def _square(alt: float = 20.0) -> list[Waypoint]:
    return [
        Waypoint(north_m=30.0, east_m=0.0, alt_m=alt),
        Waypoint(north_m=30.0, east_m=30.0, alt_m=alt),
        Waypoint(north_m=0.0, east_m=30.0, alt_m=alt),
        Waypoint(north_m=0.0, east_m=0.0, alt_m=alt),
    ]


class TestMissionPlanSummary:
    def _cfg(self, laps: int = 5) -> MissionConfig:
        return MissionConfig(
            type="coordinated_waypoint",
            duration_sec=300.0,
            waypoints=tuple(_square() * laps),
            laps=laps,
        )

    def test_records_laps_and_expanded_plan(self):
        out = mission_plan_summary(self._cfg(laps=5))
        assert out["laps"] == 5
        assert out["n_waypoints"] == 20
        assert len(out["lap_waypoints"]) == 4
        assert len(out["waypoints"]) == 20

    def test_records_attack_timing(self):
        # Without these the coordinates cannot be placed on the route.
        out = mission_plan_summary(
            self._cfg(),
            attack_at_sec=90.0,
            observation_after_attack_sec=60.0,
        )
        assert out["attack_at_sec"] == 90.0
        assert out["observation_after_attack_sec"] == 60.0

    def test_timing_optional(self):
        out = mission_plan_summary(self._cfg())
        assert out["attack_at_sec"] is None
        assert out["observation_after_attack_sec"] is None

    def test_single_lap_config(self):
        out = mission_plan_summary(self._cfg(laps=1))
        assert out["laps"] == 1
        assert out["n_waypoints"] == 4
        assert out["lap_waypoints"] == out["waypoints"]

    def test_is_json_serializable(self):
        # It has to survive json.dump in the runner or the run has no
        # summary at all.
        out = mission_plan_summary(self._cfg(), attack_at_sec=90.0)
        loaded = json.loads(json.dumps(out))
        assert loaded["lap_waypoints"][0] == {
            "north_m": 30.0, "east_m": 0.0, "alt_m": 20.0
        }

    def test_shipped_config_is_recorded_faithfully(self):
        # Guards the OPEN-1 failure class: a run must describe its own
        # plan, because configs/experiment.yaml drifts under the OPEN-2
        # sweeps and cannot be trusted as a retroactive record.
        from core.config import load_experiment_config

        cfg = load_experiment_config(
            Path(__file__).resolve().parents[1] / "configs" / "experiment.yaml"
        )
        out = mission_plan_summary(cfg.mission)
        assert out["laps"] >= 4
        assert out["n_waypoints"] == len(out["lap_waypoints"]) * out["laps"]
