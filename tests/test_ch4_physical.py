"""metrics.collision_flags + metrics.ch4_physical_tables (review P1, stage 4)."""
import csv

from metrics.ch4_physical_tables import build, fmt_q
from metrics.collision_flags import collision_falls, fall_times


def _hover(x, z=20.0, t0=0.0, n=300, dt=0.2):
    # first sample on the pad: it defines the altitude origin
    return [(t0 - dt, x, 0.0, 0.0)] + [(t0 + i * dt, x, 0.0, z) for i in range(n)]


def _knocked_down(x, t_hit=20.0, dt=0.2, n=300):
    # 20 m hover, drops to 1 m within 3 s after t_hit, then stays low
    out = [(-dt, x, 0.0, 0.0)]  # pad sample = altitude origin
    for i in range(n):
        t = i * dt
        z = 20.0 if t < t_hit else max(1.0, 20.0 - (t - t_hit) * 7.0)
        out.append((t, x, 0.0, z))
    return out


def test_normal_landing_is_not_a_fall():
    s = [(i * 0.2, 0.0, 0.0, max(0.0, 20.0 - i * 0.2 * 0.7)) for i in range(200)]
    assert fall_times(s) == []


def test_fast_drop_is_a_fall_once():
    s = _knocked_down(0.0)
    f = fall_times(s)
    assert len(f) == 1 and 22.0 < f[0] < 23.5


def test_fall_counts_as_collision_only_after_contact():
    # peer flies through uav_0 at t ~ 19.5 s -> contact just before the drop;
    # lone UAV far away -> no contact
    through = [(-0.2, -20.0, 0.0, 0.0)] + [(i * 0.2, -20.0 + i * 0.2, 0.0, 20.0)
                                          for i in range(300)]
    with_peer = {"uav_0": _knocked_down(0.0), "uav_1": through}
    alone = {"uav_0": _knocked_down(0.0), "uav_1": _hover(50.0)}
    assert collision_falls(with_peer)["uav_0"]
    assert collision_falls(alone)["uav_0"] == []


def test_fmt_q_handles_empty_and_values():
    assert fmt_q([None, None]) == "н/д"
    assert fmt_q([1.0, 2.0, 3.0]).startswith("2.00 [")


def _write(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_build_smoke(tmp_path):
    phys = [{"run_id": "r1", "architecture": "C", "attack": "gps_spoofing",
             "nav_error_end_m": "50", "nav_error_peak_m": "50",
             "t_estimate_jump_s": "7.5", "t_first_response_s": "3.0",
             "first_response_action": "mode_loiter",
             "post_response_drift_m": "50", "route_distance_m": "19.7",
             "waypoints_captured": "2", "mission_execution": "0.29"}]
    master = [{"run_id": "r1", "architecture": "C", "attack": "gps_spoofing",
               "valid": "True", "degradation_stopped": "True",
               "mttr_functional_s": "16", "phase_excess_m": "145",
               "geometry_excess_m": "52"}]
    flags = [{"run_id": "r1", "collision_fall": "False"}]
    p, m, f = tmp_path / "p.csv", tmp_path / "m.csv", tmp_path / "f.csv"
    _write(p, phys), _write(m, master), _write(f, flags)
    md = build(str(p), str(m), str(f))
    assert "Таблиця 4.6" in md and "Таблиця 4.7" in md and "Таблиця 4.8" in md
    assert "LOITER, 3.00 (1/1)" in md
    assert "Таблиця Д.1" in md
