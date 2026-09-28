"""metrics.figures_h3_map — data helpers of the H3 offline-map figure."""
from metrics.figures_h3_map import LEVELS, series_from_map, spread_labels


def _cell(theta, h, t, fa=0):
    lv = {L: {"v0_mps": v, "peer_detect_share": 1.0,
              "t_rng_s": {"median": t + i}, "harm_at_alarm_m": {"median": h, "p5": h - 1, "p95": h + 2}}
          for i, (L, v) in enumerate(zip(LEVELS, (1, 3, 10, 30)))}
    return {"calibration": {"theta_m": theta}, "levels": lv, "false_alarms": {"alarms": fa}}


def test_series_from_map_picks_bias_and_sorts_sigma():
    res = {"cells": {"1.5|0.2": _cell(9.1, 17.0, 20.0), "0.0|0.2": _cell(1.8, 5.5, 8.0),
                     "0.0|0.4": _cell(2.0, 99.0, 99.0, fa=5)}}
    d = series_from_map(res, bias=0.2)
    assert d["sigma"] == [0.0, 1.5]
    assert d["theta"] == [1.8, 9.1]
    assert d["harm_L1"][0] == (5.5, 4.5, 7.5)
    assert d["t_rng"]["L3"] == [9.0, 21.0]
    assert d["detect"] == 1.0 and d["false_alarms"] == 0


def test_spread_labels_keeps_order_and_gap():
    ys = [40.4, 19.0, 18.0, 9.5]
    out = spread_labels(ys, 2.4)
    assert out[0] == 40.4 and out[3] == 9.5
    assert abs(out[1] - out[2]) >= 2.4 - 1e-9
    assert out[2] == 18.0 and out[1] == 20.4
