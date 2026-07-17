"""
Tests for metrics.estimator_series.

The module exists to make OPEN-3 answerable, so the tests are built
around the three runs that define it (RESULTS_NOTES R8):

    19 of 20 runs   3 detectors fired, MTTD ~2.97 s
    r10             1 detector fired,  MTTD 5.84 s
    1784210522      0 detectors fired, never detected

and around the one question that separates the two possible causes of a
non-detection: did the ratio never cross the threshold, or did it cross
without sustaining? `max_consecutive_above` is the discriminator, and
`TestOpen3Diagnosis` below is the reason this module was written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metrics.estimator_series import (
    DEFAULT_FIELDS,
    DEFAULT_MSG_TYPE,
    DEFAULT_PRIMARY_FIELD,
    DEFAULT_THRESHOLD,
    estimator_series,
    read_telemetry,
)


T_ATTACK = 1784265378.0


def _sample(
    t_rel: float,
    ratio: float | None = 0.006,
    *,
    uav_id: str = "uav_0",
    vel_ratio: float | None = 0.31,
    msg_type: str = DEFAULT_MSG_TYPE,
) -> dict:
    data: dict = {}
    if ratio is not None:
        data["pos_horiz_ratio"] = ratio
    if vel_ratio is not None:
        data["vel_ratio"] = vel_ratio
    return {
        "t_wall": T_ATTACK + t_rel,
        "uav_id": uav_id,
        "msg_type": msg_type,
        "data": data,
    }


def _ramp(uav_id: str = "uav_0") -> list[dict]:
    """The verified live signature (attacks/gps_spoofing.py): baseline
    ~0.006 while healthy, then a ramp that clips at 2.0 after injection.
    ESTIMATOR_STATUS is 1 Hz on PX4 SITL.
    """
    out = [_sample(float(t), 0.006, uav_id=uav_id) for t in range(-90, 0)]
    ramp = [0.3, 0.9, 1.169, 1.6, 2.0, 2.0, 2.0]
    out += [
        _sample(float(i), v, uav_id=uav_id) for i, v in enumerate(ramp)
    ]
    out += [_sample(float(t), 2.0, uav_id=uav_id) for t in range(7, 60)]
    return out


# ---------------------------------------------------------------------------
# OPEN-3: the two causes of a non-detection must be distinguishable
# ---------------------------------------------------------------------------


class TestOpen3Diagnosis:
    """The whole point of the module."""

    def test_signature_never_appeared(self):
        # Cause 1: the injection produced no signature at all. Then the
        # detection rate is a property of the ATTACK, not of the
        # architecture — a threats-to-validity finding, not a result.
        flat = [_sample(float(t), 0.006) for t in range(-90, 60)]
        res = estimator_series(flat, T_ATTACK, target_uav="uav_0")
        u = res["uavs"]["uav_0"]
        assert u["n_above_threshold"] == 0
        assert u["max_consecutive_above"] == 0
        assert u["first_cross_t_rel_sec"] is None
        assert u["peak"] == 0.006

    def test_signature_appeared_but_did_not_sustain(self):
        # Cause 2: the ratio crossed twice, never 3 in a row. With
        # sustained_samples=3 the detector stays silent although the
        # signature was there — a detector-tuning finding, a different
        # paper section entirely.
        out = [_sample(float(t), 0.006) for t in range(-90, 0)]
        out += [
            _sample(0.0, 1.5),
            _sample(1.0, 1.5),
            _sample(2.0, 0.4),   # dip resets the detector's counter
            _sample(3.0, 1.5),
            _sample(4.0, 1.5),
            _sample(5.0, 0.3),
        ]
        res = estimator_series(out, T_ATTACK)
        u = res["uavs"]["uav_0"]
        assert u["n_above_threshold"] == 4
        assert u["max_consecutive_above"] == 2   # < 3 -> no alert
        assert u["first_cross_t_rel_sec"] == pytest.approx(0.0)

    def test_detected_run_shows_a_sustained_breach(self):
        # The 19-of-20 case: ratio crosses at +2 s and stays up, so the
        # 3-sample sustain rule is satisfied and MTTD ~3 s follows.
        res = estimator_series(_ramp(), T_ATTACK, target_uav="uav_0")
        u = res["uavs"]["uav_0"]
        assert u["max_consecutive_above"] >= 3
        assert u["first_cross_t_rel_sec"] == pytest.approx(2.0)
        assert u["baseline_median"] == pytest.approx(0.006)
        assert u["peak"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Threshold logic must mirror the detector
# ---------------------------------------------------------------------------


class TestThresholdStats:
    def test_exact_threshold_is_not_a_breach(self):
        # GpsSpoofingDetector uses strict `>`. If this module used `>=`
        # it would report breaches the detector never saw.
        out = [_sample(float(i), 1.0) for i in range(5)]
        res = estimator_series(out, T_ATTACK)
        assert res["uavs"]["uav_0"]["n_above_threshold"] == 0

    def test_gap_breaks_a_run_of_breaches(self):
        # A missing sample is not a breach the detector could have
        # counted, so it must not bridge two runs into one.
        out = [
            _sample(0.0, 1.5),
            _sample(1.0, 1.5),
            _sample(2.0, None),   # ESTIMATOR_STATUS without the field
            _sample(3.0, 1.5),
            _sample(4.0, 1.5),
        ]
        res = estimator_series(out, T_ATTACK)
        assert res["uavs"]["uav_0"]["max_consecutive_above"] == 2

    def test_threshold_is_a_parameter_and_is_recorded(self):
        # A stored series can be re-scored against a retuned detector
        # without re-flying anything.
        out = [_sample(float(i), 1.5) for i in range(5)]
        loose = estimator_series(out, T_ATTACK, threshold=1.0)
        tight = estimator_series(out, T_ATTACK, threshold=2.0)
        assert loose["threshold"] == 1.0
        assert tight["threshold"] == 2.0
        assert loose["uavs"]["uav_0"]["n_above_threshold"] == 5
        assert tight["uavs"]["uav_0"]["n_above_threshold"] == 0

    def test_default_threshold_matches_the_detector(self):
        from detectors.gps import GpsSpoofingDetector

        # Duplicated on purpose (this module must stay readable if the
        # detector is retuned), but a silent divergence would make every
        # recorded breach count describe a detector that does not exist.
        assert DEFAULT_THRESHOLD == GpsSpoofingDetector.DEFAULT_THRESHOLD


# ---------------------------------------------------------------------------
# Anchoring
# ---------------------------------------------------------------------------


class TestAnchoring:
    def test_t_rel_is_signed_around_injection(self):
        res = estimator_series(
            [_sample(-2.0), _sample(-1.0), _sample(0.0), _sample(1.0)],
            T_ATTACK,
        )
        assert res["uavs"]["uav_0"]["t_rel_sec"] == [-2.0, -1.0, 0.0, 1.0]

    def test_samples_are_sorted_by_time(self):
        res = estimator_series(
            [_sample(5.0, 1.1), _sample(-1.0, 0.1), _sample(2.0, 0.9)],
            T_ATTACK,
        )
        assert res["uavs"]["uav_0"]["t_rel_sec"] == [-1.0, 2.0, 5.0]
        assert res["uavs"]["uav_0"]["pos_horiz_ratio"] == [0.1, 0.9, 1.1]

    def test_no_anchor_returns_none(self):
        # An unanchored series cannot answer anything about the attack.
        assert estimator_series(_ramp(), None) is None

    def test_attack_wall_recorded(self):
        res = estimator_series(_ramp(), T_ATTACK)
        assert res["attack_at_wall"] == T_ATTACK


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


class TestBaseline:
    def test_baseline_uses_only_pre_injection_samples(self):
        res = estimator_series(_ramp(), T_ATTACK)
        u = res["uavs"]["uav_0"]
        assert u["baseline_n"] == 90
        assert u["baseline_median"] == pytest.approx(0.006)

    def test_baseline_is_median_not_mean(self):
        # One pre-injection transient must not move the baseline.
        out = [_sample(float(t), 0.01) for t in range(-9, 0)]
        out[3] = _sample(-6.0, 99.0)
        out.append(_sample(1.0, 1.5))
        res = estimator_series(out, T_ATTACK)
        assert res["uavs"]["uav_0"]["baseline_median"] == pytest.approx(0.01)

    def test_no_pre_injection_samples_gives_none_not_zero(self):
        res = estimator_series([_sample(1.0, 1.5)], T_ATTACK)
        u = res["uavs"]["uav_0"]
        assert u["baseline_median"] is None
        assert u["baseline_n"] == 0


# ---------------------------------------------------------------------------
# Multi-UAV / routing
# ---------------------------------------------------------------------------


class TestFleet:
    def test_series_split_per_uav(self):
        out = _ramp("uav_0") + [
            _sample(float(t), 0.005, uav_id="uav_1") for t in range(-5, 5)
        ]
        res = estimator_series(out, T_ATTACK, target_uav="uav_0")
        assert set(res["uavs"]) == {"uav_0", "uav_1"}
        assert res["uavs"]["uav_0"]["max_consecutive_above"] >= 3
        assert res["uavs"]["uav_1"]["n_above_threshold"] == 0
        assert res["target_uav"] == "uav_0"

    def test_other_msg_types_ignored(self):
        out = _ramp() + [
            _sample(0.0, 9.9, msg_type="ATTITUDE"),
            _sample(1.0, 9.9, msg_type="LOCAL_POSITION_NED"),
        ]
        res = estimator_series(out, T_ATTACK)
        assert res["n_samples_total"] == len(_ramp())
        assert res["uavs"]["uav_0"]["peak"] == pytest.approx(2.0)

    def test_empty_input(self):
        res = estimator_series([], T_ATTACK)
        assert res["uavs"] == {}
        assert res["n_samples_total"] == 0


# ---------------------------------------------------------------------------
# Field handling
# ---------------------------------------------------------------------------


class TestFields:
    def test_secondary_field_carried(self):
        # vel_ratio separates spoofing (pos high, vel low) from GPS noise
        # (both spike together) — see detectors/gps.py.
        res = estimator_series(_ramp(), T_ATTACK)
        u = res["uavs"]["uav_0"]
        assert u["vel_ratio"][0] == pytest.approx(0.31)
        assert len(u["vel_ratio"]) == len(u["pos_horiz_ratio"])
        assert res["fields"] == list(DEFAULT_FIELDS)

    def test_missing_field_is_none_not_zero(self):
        # A ratio that was never reported is not a ratio of 0.0.
        out = [_sample(0.0, 1.5, vel_ratio=None)]
        res = estimator_series(out, T_ATTACK)
        assert res["uavs"]["uav_0"]["vel_ratio"] == [None]

    def test_non_numeric_values_are_none(self):
        out = [_sample(0.0, 1.5)]
        out[0]["data"]["pos_horiz_ratio"] = "not a number"
        res = estimator_series(out, T_ATTACK)
        u = res["uavs"]["uav_0"]
        assert u["pos_horiz_ratio"] == [None]
        assert u["n_above_threshold"] == 0

    def test_bool_is_not_a_ratio(self):
        # bool is an int subclass in Python: True would silently become
        # 1.0, sitting exactly at the detector threshold.
        out = [_sample(0.0, 1.5)]
        out[0]["data"]["pos_horiz_ratio"] = True
        res = estimator_series(out, T_ATTACK)
        assert res["uavs"]["uav_0"]["pos_horiz_ratio"] == [None]

    def test_nan_and_inf_rejected(self):
        out = [_sample(0.0, 1.5), _sample(1.0, 1.5)]
        out[0]["data"]["pos_horiz_ratio"] = float("nan")
        out[1]["data"]["pos_horiz_ratio"] = float("inf")
        res = estimator_series(out, T_ATTACK)
        u = res["uavs"]["uav_0"]
        assert u["pos_horiz_ratio"] == [None, None]
        assert u["peak"] is None

    def test_custom_fields(self):
        out = [_sample(0.0, 1.5)]
        out[0]["data"]["mag_ratio"] = 0.2
        res = estimator_series(
            out, T_ATTACK, fields=("pos_horiz_ratio", "mag_ratio")
        )
        u = res["uavs"]["uav_0"]
        assert u["mag_ratio"] == [0.2]
        assert "vel_ratio" not in u


# ---------------------------------------------------------------------------
# Rate
# ---------------------------------------------------------------------------


class TestRate:
    def test_rate_hz_reflects_px4_publishing(self):
        # ESTIMATOR_STATUS is 1 Hz on PX4 SITL, which is why MTTD has a
        # ~3 s floor with sustained_samples=3. If a run's rate departs
        # from 1 Hz, its MTTD is not comparable — worth seeing per run.
        res = estimator_series(_ramp(), T_ATTACK)
        assert res["uavs"]["uav_0"]["rate_hz"] == pytest.approx(1.0, rel=0.01)

    def test_single_sample_has_no_rate(self):
        res = estimator_series([_sample(0.0)], T_ATTACK)
        assert res["uavs"]["uav_0"]["rate_hz"] is None
        assert res["uavs"]["uav_0"]["n"] == 1


# ---------------------------------------------------------------------------
# Size and serialization — this goes into a committed artefact
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_json_round_trip(self):
        res = estimator_series(_ramp(), T_ATTACK, target_uav="uav_0")
        loaded = json.loads(json.dumps(res))
        assert loaded["uavs"]["uav_0"]["peak"] == 2.0

    def test_series_stays_small_enough_to_commit(self):
        # ~160 samples x 2 fields x 3 UAVs. The whole reason this can
        # live in run_summary.json rather than only in a gitignored
        # .jsonl is that it is a few kB.
        out = _ramp("uav_0") + _ramp("uav_1") + _ramp("uav_2")
        res = estimator_series(out, T_ATTACK, target_uav="uav_0")
        assert len(json.dumps(res)) < 25_000

    def test_values_are_rounded(self):
        out = [_sample(0.123456789, 1.23456789)]
        res = estimator_series(out, T_ATTACK)
        u = res["uavs"]["uav_0"]
        assert u["pos_horiz_ratio"] == [1.2346]
        assert u["t_rel_sec"] == [0.123]


# ---------------------------------------------------------------------------
# Reader robustness
# ---------------------------------------------------------------------------


class TestReadTelemetry:
    def _write(self, tmp_path: Path, lines: list[str]) -> Path:
        p = tmp_path / "telemetry_uav_0.jsonl"
        p.write_text("\n".join(lines) + "\n")
        return p

    def _line(self, **kw) -> str:
        base = {
            "source": "monitor_uav_0",
            "event_type": "telemetry",
            "event_id": "abc",
            "timestamp": T_ATTACK,
            "caused_by": None,
            "uav_id": "uav_0",
            "msg_type": "ESTIMATOR_STATUS",
            "data": {"pos_horiz_ratio": 0.006, "vel_ratio": 0.31},
        }
        base.update(kw)
        return json.dumps(base)

    def test_round_trip_into_series(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            [
                self._line(
                    timestamp=T_ATTACK + i,
                    data={"pos_horiz_ratio": 1.5, "vel_ratio": 0.3},
                )
                for i in range(4)
            ],
        )
        samples = read_telemetry(p)
        res = estimator_series(samples, T_ATTACK, target_uav="uav_0")
        assert res["uavs"]["uav_0"]["max_consecutive_above"] == 4

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert read_telemetry(tmp_path / "nope.jsonl") == []

    def test_truncated_last_line_skipped(self, tmp_path: Path):
        # The listener thread is killed at teardown, so a half-written
        # final line is normal, not exceptional. read_jsonl would raise.
        p = self._write(tmp_path, [self._line(), '{"event_type": "tel'])
        assert len(read_telemetry(p)) == 1

    def test_non_telemetry_events_ignored(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            [
                self._line(),
                json.dumps(
                    {
                        "source": "m",
                        "event_type": "security",
                        "timestamp": T_ATTACK,
                        "detector": "gps",
                    }
                ),
            ],
        )
        got = read_telemetry(p)
        assert len(got) == 1
        assert got[0]["msg_type"] == "ESTIMATOR_STATUS"

    def test_msg_type_filter(self, tmp_path: Path):
        p = self._write(
            tmp_path,
            [self._line(), self._line(msg_type="ATTITUDE")],
        )
        assert len(read_telemetry(p)) == 2
        assert len(read_telemetry(p, msg_type="ESTIMATOR_STATUS")) == 1

    def test_records_without_data_skipped(self, tmp_path: Path):
        p = self._write(tmp_path, [self._line(data=None), self._line()])
        assert len(read_telemetry(p)) == 1

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "telemetry_uav_0.jsonl"
        p.write_text("")
        assert read_telemetry(p) == []
