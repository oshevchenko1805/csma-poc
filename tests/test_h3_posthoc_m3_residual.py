"""Post-hoc M3 residual geometry (exploratory script, not part of the H3
decision): a sign change of rho makes a large theta miss the first phase."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

_P = Path(__file__).resolve().parent.parent / "scripts" / "h3_posthoc_m3_residual.py"
_spec = importlib.util.spec_from_file_location("h3_posthoc_m3_residual", _P)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def test_sign_change_delays_alarm_for_large_theta():
    # rho: 0 before 5 s; +20 m at 5 s falling to 0 at 8 s; then -6 m/s to -30 m
    t = np.arange(0.0, 30.0 + 1e-9, 0.1)
    rho = np.where(t < 5, 0.0,
                   np.where(t < 8, 20.0 - (t - 5) * 20.0 / 3.0,
                            np.maximum(-30.0, -(t - 8) * 6.0)))
    ticks = np.arange(0.0, 31.0, 1.0)
    rho1 = np.interp(ticks, t, rho)
    assert M.first_sustained(ticks, rho1, 1.8) == pytest.approx(7.0)   # 5, 6, 7 above
    assert M.first_sustained(ticks, rho1, 9.1) == pytest.approx(12.0)  # 7 below: reset
    assert M.zero_crossing(t, rho, after=5.0) == pytest.approx(8.0, abs=0.05)
    assert M.time_below_after_exceed(t, rho, 9.1) > M.time_below_after_exceed(t, rho, 1.8) > 0.0
