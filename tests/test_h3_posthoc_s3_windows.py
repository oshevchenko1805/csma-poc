"""Post-hoc S3 window check: drift_by_window is the H2 drift truncated at
each window end (exploratory script, not part of the H3 decision)."""

import importlib.util
from pathlib import Path

import pytest

_P = Path(__file__).resolve().parent.parent / "scripts" / "h3_posthoc_s3_windows.py"
_spec = importlib.util.spec_from_file_location("h3_posthoc_s3_windows", _P)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def test_drift_grows_with_window_and_starts_at_ack():
    # (t, north, east): still until ack at t=10, then 0.1 m/s north.
    track = [(float(t), 0.0 if t <= 10 else 0.1 * (t - 10), 0.0) for t in range(0, 131)]
    d = M.drift_by_window(track, t_ack=10.0, t0=0.0)
    assert d[30.0] == pytest.approx(2.0, abs=1e-6)
    assert d[60.0] == pytest.approx(5.0, abs=1e-6)
    assert d[120.0] == pytest.approx(11.0, abs=1e-6)
    assert d[30.0] < d[60.0] < d[90.0] < d[120.0]
