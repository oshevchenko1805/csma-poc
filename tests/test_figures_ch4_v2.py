"""metrics.figures_ch4_v2 — data helpers behind the new Ch. 4 figures."""
import math

from metrics.figures_ch4_v2 import GRID, _interp, _pick_v1, band


def test_interp_inside_and_gap():
    ts, vs = [0.0, 1.0, 2.0, 10.0], [0.0, 10.0, 20.0, 30.0]
    assert _interp(ts, vs, 0.5) == 5.0
    assert _interp(ts, vs, 2.0) == 20.0
    assert _interp(ts, vs, 5.0) is None      # gap > 2.5 s: not bridged
    assert _interp(ts, vs, -1.0) is None     # outside the series


def test_band_median_and_quartiles():
    series = [[float(k)] * len(GRID) for k in range(1, 6)]   # 1..5 everywhere
    med, lo, hi = band(series)
    assert med[0] == 3.0 and lo[0] < 3.0 < hi[0]


def test_band_needs_half_the_runs():
    series = [[None] * len(GRID) for _ in range(6)]
    series[0] = [1.0] * len(GRID)
    med, _, _ = band(series)
    assert math.isnan(med[0])


def test_pick_v1_uses_cell_metric_and_is_deterministic():
    rows = [
        {"run_id": "r1", "attack": "gps_spoofing", "architecture": "C",
         "post_response_drift_m": "49.0", "route_distance_m": "19.0"},
        {"run_id": "r2", "attack": "gps_spoofing", "architecture": "C",
         "post_response_drift_m": "50.0", "route_distance_m": "0.2"},
        {"run_id": "r3", "attack": "gps_spoofing", "architecture": "C",
         "post_response_drift_m": "51.0", "route_distance_m": "19.5"},
        {"run_id": "a1", "attack": "gps_spoofing", "architecture": "A",
         "post_response_drift_m": "", "route_distance_m": "49.8"},
    ]
    assert _pick_v1(rows, "gps_spoofing", "C")["run_id"] == "r2"   # drift median
    assert _pick_v1(rows, "gps_spoofing", "A")["run_id"] == "a1"   # route distance


def test_loss_sweep_renders(tmp_path):
    from metrics.figures_ch4_v2 import fig_loss_sweep
    p = tmp_path / "loss.csv"
    p.write_text("loss_prob,n,detected\n0.0,28,27\n0.1,29,29\n0.2,30,28\n0.3,30,19\n")
    fig_loss_sweep(str(p), str(tmp_path))
    assert (tmp_path / "fig4_1_losssweep.png").stat().st_size > 0
