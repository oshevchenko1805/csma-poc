"""scripts/run_one.py + ExperimentRunner wiring for B1 (H3 item 9a):
--arch c_ranging, --spoof-rate, --range-seed, range source fed by the truth
recorder, range_source (seed) in run_summary. v1 paths unchanged."""
import dataclasses
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import run_one  # noqa: E402

from attacks.composite import SequentialAttackInjector  # noqa: E402
from attacks.detector_takeout import DetectorTakeoutInjector  # noqa: E402
from attacks.gps_spoofing import GpsSpoofingInjector  # noqa: E402
from core.config import ConfigError, load_architecture_config  # noqa: E402
from detectors.range_source import SimulatedUwbRangeSource, TruthBuffer  # noqa: E402
from runners.experiment import RunResult, describe_range_source  # noqa: E402
from runners.trajectory import TrajectoryRecorder  # noqa: E402

CFG = pathlib.Path(__file__).resolve().parent.parent / "configs"
L1 = 0.0006667


def _gps_children(inj):
    kids = inj.children if isinstance(inj, SequentialAttackInjector) else (inj,)
    return [c for c in kids if isinstance(c, GpsSpoofingInjector)]


# --- attacks -------------------------------------------------------------------

@pytest.mark.parametrize("name", list(run_one.ATTACK_FACTORIES))
def test_build_attack_without_rate_is_v1_factory(name):
    inj = run_one.build_attack(name)
    assert type(inj) is type(run_one.ATTACK_FACTORIES[name]())
    for g in _gps_children(inj):
        assert "spoof_rate" not in g.injection_evidence()["gps_spoofing"]


def test_gps_kw_matches_v1_factories():
    for name in ("gps_spoofing", "detector_takeout+gps_spoofing",
                 "monitor_takeout+gps_spoofing"):
        (g,) = _gps_children(run_one.ATTACK_FACTORIES[name]())
        ev = g.injection_evidence()["gps_spoofing"]
        assert ev["param"] == run_one.GPS_SPOOF_KW["param_name"]
        assert ev["spoofed_value"] == run_one.GPS_SPOOF_KW["spoofed_value"]


def test_build_attack_with_rate_gps():
    inj = run_one.build_attack("gps_spoofing", spoof_rate=L1)
    assert isinstance(inj, GpsSpoofingInjector)
    ev = inj.injection_evidence()["gps_spoofing"]
    assert ev["spoof_rate"] == L1 and ev["param"] == "SIM_GPS_OFF_N"
    assert ev["spoofed_value"] == 50.0 and "t_target_set" in ev


def test_build_attack_with_rate_keeps_composite():
    inj = run_one.build_attack("detector_takeout+gps_spoofing", spoof_rate=L1)
    assert isinstance(inj, SequentialAttackInjector)
    assert inj.name == "detector_takeout+gps_spoofing"
    assert isinstance(inj.children[0], DetectorTakeoutInjector)
    (g,) = _gps_children(inj)
    assert g.injection_evidence()["gps_spoofing"]["spoof_rate"] == L1


@pytest.mark.parametrize("name", ["none", "comm_disruption", "command_injection"])
def test_spoof_rate_rejected_without_gps(name):
    with pytest.raises(ConfigError):
        run_one.build_attack(name, spoof_rate=L1)


# --- range source ----------------------------------------------------------------

def test_needs_range_source_is_config_driven():
    assert run_one.needs_range_source(
        load_architecture_config(CFG / "architecture_c_ranging.yaml"))
    for a in ("a", "b", "c"):
        assert not run_one.needs_range_source(
            load_architecture_config(CFG / f"architecture_{a}.yaml"))


def test_build_range_source():
    buf, src = run_one.build_range_source(
        load_architecture_config(CFG / "architecture_c_ranging.yaml"), 42)
    assert isinstance(buf, TruthBuffer) and isinstance(src, SimulatedUwbRangeSource)
    assert src.describe()["seed"] == 42
    assert run_one.build_range_source(
        load_architecture_config(CFG / "architecture_c.yaml"), 42) == (None, None)


def test_default_range_seed_fixed_per_run_and_distinct():
    a = run_one.default_range_seed("C_ranging_r1_1790000000")
    assert a == run_one.default_range_seed("C_ranging_r1_1790000000")
    assert a != run_one.default_range_seed("C_ranging_r2_1790000100")
    assert 0 <= a < 2**31


def test_trajectory_factory(tmp_path):
    assert run_one.make_trajectory_factory("null") is None
    assert run_one.make_trajectory_factory("null", TruthBuffer()) is None
    rec = run_one.make_trajectory_factory("mavsdk")(tmp_path / "t.jsonl")
    assert isinstance(rec, TrajectoryRecorder) and "on_sample_errors" not in rec.stats
    buf = TruthBuffer()
    rec = run_one.make_trajectory_factory("mavsdk", buf)(tmp_path / "u.jsonl")
    assert "on_sample_errors" in rec.stats
    assert rec._on_sample == buf.add


# --- CLI ---------------------------------------------------------------------------

def test_parse_args_defaults_v1():
    a = run_one.parse_args(["--arch", "c", "--attack", "none"])
    assert a.spoof_rate is None and a.range_seed is None


def test_parse_args_b1():
    a = run_one.parse_args(["--arch", "c_ranging", "--attack", "gps_spoofing",
                            "--spoof-rate", str(L1), "--range-seed", "7"])
    assert a.arch == "c_ranging" and a.spoof_rate == L1 and a.range_seed == 7


def test_main_dry_run_c_ranging(tmp_path):
    rc = run_one.main(["--arch", "c_ranging", "--attack", "gps_spoofing",
                       "--spoof-rate", str(L1), "--recovery-policy", "detect_only",
                       "--log-root", str(tmp_path), "--px4-pid-file", "",
                       "--dry-run"])
    assert rc == 0


def test_main_rejects_ranging_without_truth_feed(tmp_path):
    with pytest.raises(ConfigError):
        run_one.main(["--arch", "c_ranging", "--attack", "none", "--mission", "null",
                      "--log-root", str(tmp_path), "--px4-pid-file", "", "--dry-run"])


# --- run_summary ---------------------------------------------------------------------

def test_run_result_range_source_default_none():
    f = {x.name: x for x in dataclasses.fields(RunResult)}
    assert f["range_source"].default is None
    assert list(f)[-1] == "error"


def test_describe_range_source():
    assert describe_range_source(None) is None
    assert describe_range_source(object()) is None
    d = describe_range_source(SimulatedUwbRangeSource(TruthBuffer(), 5))
    assert d["seed"] == 5 and d["model"] == "simulated_uwb"
