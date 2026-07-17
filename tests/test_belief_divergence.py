"""
Tests for metrics.belief_divergence.

Item 2B, first piece: EKF origin resolution. The reason to test this in
isolation is the "mina" documented in PROJECT_STATE -- the fleet is
spread along Gazebo X (`PX4_GZ_MODEL_POSE = instance*5,0,0`), so a
healthy uav_1/uav_2 that never has its origin subtracted reads a false
divergence of 5 m / 10 m. These tests pin down that the origin is:

  * measured from pre-liftoff ground samples, not assumed from a
    fleet-spacing constant;
  * insulated from post-liftoff data -- a crash or landing later in the
    run must not contaminate the reference point;
  * `None`, not (0, 0, 0), when there is nothing to measure.
"""

from __future__ import annotations

import pytest

from metrics.belief_divergence import (
    DEFAULT_AIRBORNE_THRESHOLD_M,
    resolve_ekf_origin,
)


def _sample(uav_id: str, t: float, x: float, y: float, z: float) -> dict:
    return {"t_wall": t, "uav_id": uav_id, "x": x, "y": y, "z": z}


class TestNoData:
    def test_no_samples_for_uav_returns_none(self):
        samples = [_sample("uav_1", 0.0, 5.0, 0.0, 0.0)]
        assert resolve_ekf_origin(samples, "uav_0") is None

    def test_empty_input_returns_none(self):
        assert resolve_ekf_origin([], "uav_0") is None

    def test_first_sample_already_airborne_returns_none(self):
        # Recorder started after liftoff: no ground reference exists.
        samples = [
            _sample("uav_0", 0.0, 0.0, 0.0, 20.0),
            _sample("uav_0", 0.2, 0.1, 0.0, 20.0),
        ]
        assert resolve_ekf_origin(samples, "uav_0") is None


class TestGroundMedian:
    def test_median_of_pre_liftoff_samples(self):
        samples = [
            _sample("uav_0", 0.0, 9.9, -0.1, 0.0),
            _sample("uav_0", 0.2, 10.0, 0.0, 0.0),
            _sample("uav_0", 0.4, 10.1, 0.1, 0.0),
        ]
        origin = resolve_ekf_origin(samples, "uav_0")
        assert origin == {"x": 10.0, "y": 0.0, "z": 0.0, "n_samples": 3}

    def test_stops_at_first_liftoff_crossing(self):
        samples = [
            _sample("uav_0", 0.0, 10.0, 0.0, 0.0),
            _sample("uav_0", 0.2, 10.0, 0.0, 0.5),
            _sample("uav_0", 0.4, 10.0, 0.0, 20.0),  # airborne, boundary
            _sample("uav_0", 0.6, 12.0, 3.0, 20.0),  # in flight
        ]
        origin = resolve_ekf_origin(samples, "uav_0")
        assert origin["n_samples"] == 2
        assert origin["x"] == 10.0

    def test_later_landing_does_not_pull_origin(self):
        # Same trajectory as above, plus a return-to-ground tail far from
        # the true spawn point. Only the FIRST ground block may count.
        samples = [
            _sample("uav_0", 0.0, 10.0, 0.0, 0.0),
            _sample("uav_0", 0.2, 10.0, 0.0, 0.0),
            _sample("uav_0", 0.4, 10.0, 0.0, 20.0),
            _sample("uav_0", 0.6, 40.0, 40.0, 20.0),
            _sample("uav_0", 0.8, 40.0, 40.0, 0.0),  # crash/landing, far away
        ]
        origin = resolve_ekf_origin(samples, "uav_0")
        assert origin == {"x": 10.0, "y": 0.0, "z": 0.0, "n_samples": 2}

    def test_unsorted_input_is_sorted_by_time(self):
        samples = [
            _sample("uav_0", 0.4, 10.2, 0.0, 0.0),
            _sample("uav_0", 0.0, 9.8, 0.0, 0.0),
            _sample("uav_0", 0.2, 10.0, 0.0, 0.0),
        ]
        origin = resolve_ekf_origin(samples, "uav_0")
        assert origin["x"] == 10.0
        assert origin["n_samples"] == 3

    def test_other_uavs_are_ignored(self):
        samples = [
            _sample("uav_0", 0.0, 0.0, 0.0, 0.0),
            _sample("uav_1", 0.0, 5.0, 0.0, 0.0),
            _sample("uav_1", 0.2, 5.0, 0.0, 0.0),
        ]
        origin = resolve_ekf_origin(samples, "uav_1")
        assert origin["x"] == 5.0
        assert origin["n_samples"] == 2


class TestThreshold:
    def test_custom_airborne_threshold_is_respected(self):
        samples = [
            _sample("uav_0", 0.0, 1.0, 0.0, 0.4),
            _sample("uav_0", 0.2, 1.0, 0.0, 0.4),
        ]
        # Default threshold (1.0 m): both samples count as ground.
        assert resolve_ekf_origin(samples, "uav_0")["n_samples"] == 2
        # Tighter threshold (0.3 m): both samples already "airborne".
        assert (
            resolve_ekf_origin(samples, "uav_0", airborne_threshold_m=0.3)
            is None
        )

    def test_default_matches_documented_value(self):
        assert DEFAULT_AIRBORNE_THRESHOLD_M == 1.0


# ===========================================================================
# belief_divergence — true (Gazebo) vs believed (LOCAL_POSITION_NED)
# ===========================================================================

import math

from metrics.belief_divergence import (
    DEFAULT_BELIEF_MSG_TYPE,
    DEFAULT_OUTPUT_RATE_HZ,
    DEFAULT_PAIR_TOLERANCE_SEC,
    belief_divergence,
)
from metrics import flight_check


def _traj(uav_id, t, x, y, z):
    """Gazebo ENU pose sample (as read_trajectory yields)."""
    return {"t_wall": t, "uav_id": uav_id, "x": x, "y": y, "z": z}


def _belief(uav_id, t, north, east, down):
    """A LOCAL_POSITION_NED telemetry record (as read_telemetry yields)."""
    return {
        "t_wall": t,
        "uav_id": uav_id,
        "msg_type": "LOCAL_POSITION_NED",
        "data": {"x": north, "y": east, "z": down},
    }


def _ground(uav_id, ox, oy, n=3):
    """A pre-liftoff ground block establishing the EKF origin at (ox, oy)."""
    return [_traj(uav_id, 0.0 + i * 0.2, ox, oy, 0.0) for i in range(n)]


class TestThresholdSharedWithFlightCheck:
    def test_airborne_threshold_matches_flight_check(self):
        # The same ground/airborne boundary must define "pre-liftoff"
        # here and "flying" there; a silent divergence would resolve the
        # origin from a different set of samples than the one the flight
        # verdict is built on. Pinned by a direct equality, not by two
        # copies of the literal 1.0.
        assert (
            DEFAULT_AIRBORNE_THRESHOLD_M
            == flight_check.DEFAULT_AIRBORNE_THRESHOLD_M
        )


class TestAxisMapping:
    def test_north_offset_shows_as_north_divergence(self):
        # uav_0 spawns at gz origin (0,0). Truth flies to gz (0, 30):
        # ENU y = north, so this is 30 m north, east 0. Believe it is at
        # NED north=0 (belief lags/frozen) -> 30 m horizontal divergence,
        # all north.
        traj = _ground("uav_0", 0.0, 0.0) + [
            _traj("uav_0", 10.0, 0.0, 30.0, 20.0),
        ]
        tele = [_belief("uav_0", 10.0, 0.0, 0.0, -20.0)]
        out = belief_divergence(traj, tele, attack_at_wall=None,
                                target_uav="uav_0")
        u = out["uavs"]["uav_0"]
        assert u["n"] == 1
        assert u["divergence_horiz_m"][0] == 30.0

    def test_fleet_spacing_offset_is_removed(self):
        # uav_1 spawns at gz (5, 0). Truth at gz (5, 30) == 30 m north of
        # ITS origin; belief agrees (NED north=30, east=0). A resolver
        # that ignored the 5 m spawn offset would report 5 m of false
        # divergence; a correct one reports ~0.
        traj = _ground("uav_1", 5.0, 0.0) + [
            _traj("uav_1", 10.0, 5.0, 30.0, 20.0),
        ]
        tele = [_belief("uav_1", 10.0, 30.0, 0.0, -20.0)]
        out = belief_divergence(traj, tele, target_uav="uav_1")
        u = out["uavs"]["uav_1"]
        assert u["n"] == 1
        assert u["divergence_horiz_m"][0] == pytest.approx(0.0, abs=1e-6)

    def test_east_offset_shows_as_east_divergence(self):
        # gz x = east. Truth at gz (25, 0) from origin (0,0) = 25 m east.
        traj = _ground("uav_0", 0.0, 0.0) + [
            _traj("uav_0", 10.0, 25.0, 0.0, 20.0),
        ]
        tele = [_belief("uav_0", 10.0, 0.0, 0.0, -20.0)]
        out = belief_divergence(traj, tele)
        assert out["uavs"]["uav_0"]["divergence_horiz_m"][0] == 25.0


class TestPairing:
    def test_unpaired_when_no_truth_within_tolerance(self):
        traj = _ground("uav_0", 0.0, 0.0) + [
            _traj("uav_0", 10.0, 0.0, 0.0, 20.0),
        ]
        # Believed sample 5 s away from the nearest truth -> no pair.
        tele = [_belief("uav_0", 30.0, 0.0, 0.0, -20.0)]
        out = belief_divergence(traj, tele)
        u = out["uavs"]["uav_0"]
        assert u["n"] == 0
        assert u["n_unpaired"] == 1

    def test_pairs_within_tolerance(self):
        traj = _ground("uav_0", 0.0, 0.0) + [
            _traj("uav_0", 10.05, 0.0, 0.0, 20.0),
        ]
        tele = [_belief("uav_0", 10.0, 0.0, 0.0, -20.0)]  # 0.05 s gap
        out = belief_divergence(traj, tele)
        assert out["uavs"]["uav_0"]["n"] == 1

    def test_downsampled_to_output_rate(self):
        # 20 believed samples across 2 s (10 Hz) collapse to ~2 at 1 Hz.
        traj = _ground("uav_0", 0.0, 0.0)
        for i in range(20):
            traj.append(_traj("uav_0", 100.0 + i * 0.1, 0.0, 0.0, 20.0))
        tele = [
            _belief("uav_0", 100.0 + i * 0.1, 0.0, 0.0, -20.0)
            for i in range(20)
        ]
        out = belief_divergence(traj, tele, output_rate_hz=1.0)
        assert out["uavs"]["uav_0"]["n"] <= 3


class TestAnchor:
    def test_attack_anchor_and_pre_attack_baseline(self):
        traj = _ground("uav_0", 0.0, 0.0)
        tele = []
        # two pre-attack samples (near-zero divergence), two post (large)
        for t, n in [(98.0, 0.1), (99.0, 0.1), (101.0, 50.0), (102.0, 50.0)]:
            traj.append(_traj("uav_0", t, 0.0, n, 20.0))  # gz y = north
            tele.append(_belief("uav_0", t, 0.0, 0.0, -20.0))
        out = belief_divergence(traj, tele, attack_at_wall=100.0)
        u = out["uavs"]["uav_0"]
        assert u["anchor"] == "attack"
        assert u["t_rel_sec"][0] < 0  # first sample is pre-attack
        # baseline is the pre-attack median (~0.1), not polluted by the
        # 50 m post-attack spike
        assert u["baseline_median_horiz_m"] == pytest.approx(0.1, abs=1e-6)
        assert u["baseline_n"] == 2
        assert u["peak_horiz_m"] == pytest.approx(50.0, abs=1e-6)

    def test_no_anchor_uses_first_sample_and_whole_run_baseline(self):
        traj = _ground("uav_0", 0.0, 0.0)
        tele = []
        for t in (100.0, 101.0, 102.0):
            traj.append(_traj("uav_0", t, 0.0, 0.0, 20.0))
            tele.append(_belief("uav_0", t, 0.0, 0.0, -20.0))
        out = belief_divergence(traj, tele, attack_at_wall=None)
        u = out["uavs"]["uav_0"]
        assert u["anchor"] == "first_sample"
        assert u["t_rel_sec"][0] == 0.0
        assert u["baseline_n"] == u["n"]  # whole run is baseline


class TestNoOrigin:
    def test_missing_origin_yields_null_series_not_zero(self):
        # No ground block: first sample already airborne -> origin None.
        traj = [_traj("uav_0", 100.0, 0.0, 30.0, 20.0)]
        tele = [_belief("uav_0", 100.0, 0.0, 0.0, -20.0)]
        out = belief_divergence(traj, tele)
        u = out["uavs"]["uav_0"]
        assert u["origin"] is None
        assert u["n"] == 0
        assert u["divergence_horiz_m"] == []
        assert u["baseline_median_horiz_m"] is None


class TestRobustness:
    def test_non_belief_msg_types_ignored(self):
        traj = _ground("uav_0", 0.0, 0.0) + [
            _traj("uav_0", 10.0, 0.0, 0.0, 20.0),
        ]
        tele = [
            {
                "t_wall": 10.0,
                "uav_id": "uav_0",
                "msg_type": "ESTIMATOR_STATUS",
                "data": {"pos_horiz_ratio": 0.01},
            }
        ]
        out = belief_divergence(traj, tele)
        assert out["n_belief_samples_total"] == 0
        assert out["uavs"]["uav_0"]["n"] == 0

    def test_bool_belief_field_rejected(self):
        traj = _ground("uav_0", 0.0, 0.0) + [
            _traj("uav_0", 10.0, 0.0, 0.0, 20.0),
        ]
        tele = [_belief("uav_0", 10.0, True, 0.0, -20.0)]
        out = belief_divergence(traj, tele)
        assert out["uavs"]["uav_0"]["n_unpaired"] == 1
        assert out["uavs"]["uav_0"]["n"] == 0

    def test_invalid_output_rate_raises(self):
        with pytest.raises(ValueError):
            belief_divergence([], [], output_rate_hz=0.0)

    def test_self_describing_metadata_present(self):
        out = belief_divergence([], [])
        assert out["belief_msg_type"] == DEFAULT_BELIEF_MSG_TYPE
        assert out["truth_frame"] == "gazebo_world_enu_z_up"
        assert out["pair_tolerance_sec"] == DEFAULT_PAIR_TOLERANCE_SEC
        assert out["output_rate_hz"] == DEFAULT_OUTPUT_RATE_HZ
        assert "axis_map" in out
