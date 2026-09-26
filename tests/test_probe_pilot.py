"""Pure helpers of the stage-3b pilot extension of probe_trust_hold."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import probe_trust_hold as probe  # noqa: E402


def _line(v, t0=100.0, n=41, dt=0.1):
    # straight line north at v m/s, 10 Hz
    return [(t0 + i * dt, v * i * dt, 0.0) for i in range(n)]


def test_speed_at_recovers_constant_speed():
    assert abs(probe.speed_at(_line(5.0), 103.0) - 5.0) < 1e-6


def test_speed_at_none_without_coverage():
    assert probe.speed_at(_line(5.0), 100.5) is None      # nothing 1 s earlier
    assert probe.speed_at([], 103.0) is None


def test_reference_label_is_not_a_verdict():
    lab = probe.reference_label({"post_response_drift_m": 3.456})
    assert lab.startswith("REFERENCE (no attack)")
    assert "3.46 m" in lab
    assert "PASS" not in lab and "FAIL" not in lab
    assert probe.reference_label({}).startswith("REFERENCE INVALID")
