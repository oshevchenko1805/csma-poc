"""metrics.peer_separation (review stage 3 secondary metric)."""
import json

from metrics.peer_separation import (
    CONTACT_M, NEAR_MISS_M, count_episodes, load_world_xyz,
    separation_series, summarize,
)


def _still(x, y, z=20.0, t0=100.0, n=601, dt=0.1):
    return [(t0 + i * dt, x, y, z) for i in range(n)]


def _pass_through(t0=100.0, n=601, dt=0.1, y=0.0, z=20.0, v=2.0, x0=-30.0):
    # peer flies along x at speed v, crossing x=0 at t0 + 15 s
    return [(t0 + i * dt, x0 + v * i * dt, y, z) for i in range(n)]


def test_no_peer_close():
    s = summarize({"uav_0": _still(0, 0), "uav_1": _still(20, 0)}, "uav_0", 100.0)
    assert abs(s["min_peer_sep_m"] - 20.0) < 1e-9
    assert s["n_contacts"] == 0 and s["n_near_miss"] == 0


def test_pass_through_is_one_contact_and_one_near_miss():
    s = summarize({"uav_0": _still(0, 0), "uav_2": _pass_through()}, "uav_0", 100.0)
    assert s["min_peer_sep_m"] < 0.2
    assert abs(s["t_min_peer_sep_s"] - 15.0) < 0.2
    assert s["closest_peer"] == "uav_2"
    assert s["n_contacts"] == 1 and s["n_near_miss"] == 1


def test_altitude_separation_counts():
    # same horizontal track, 5 m above: not a contact, not a near miss
    s = summarize({"uav_0": _still(0, 0, 20.0), "uav_2": _pass_through(z=25.0)},
                  "uav_0", 100.0)
    assert abs(s["min_peer_sep_m"] - 5.0) < 0.2
    assert s["n_contacts"] == 0 and s["n_near_miss"] == 0


def test_window_excludes_pre_injection():
    # crossing at t0+15 but injection at t0+20 -> outside the window
    s = summarize({"uav_0": _still(0, 0), "uav_2": _pass_through()}, "uav_0", 120.0)
    assert s["n_contacts"] == 0 and s["min_peer_sep_m"] > 3.0


def test_episode_counting():
    ser = [(0.0, 5), (0.1, 0.5), (0.2, 0.5), (0.3, 5), (3.0, 0.5), (3.1, 5)]
    assert count_episodes(ser, CONTACT_M) == 2
    assert count_episodes([(0.0, 0.5), (0.5, 5), (0.9, 0.5)], CONTACT_M) == 1  # gap < 1 s


def test_unpaired_samples_skipped():
    far_in_time = [(t + 10.0, x, y, z) for t, x, y, z in _still(0, 0, n=10)]
    assert separation_series(_still(0, 0, n=10), far_in_time, 0, 1e9) == []


def test_missing_data_is_none_not_zero():
    s = summarize({"uav_0": _still(0, 0)}, "uav_0", 100.0)
    assert s["min_peer_sep_m"] is None and s["n_contacts"] is None


def test_load_world_xyz(tmp_path):
    p = tmp_path / "trajectory.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        {"t_wall": 2.0, "uav_id": "uav_0", "x": 1, "y": 2, "z": 3},
        {"t_wall": 1.0, "uav_id": "uav_0", "x": 0, "y": 0, "z": 0},
        {"t_wall": 1.0, "model": "ground"},
    ]) + "\n")
    xyz = load_world_xyz(str(tmp_path))
    assert xyz == {"uav_0": [(1.0, 0.0, 0.0, 0.0), (2.0, 1.0, 2.0, 3.0)]}


def test_thresholds_fixed():
    assert (CONTACT_M, NEAR_MISS_M) == (1.0, 3.0)
