"""metrics.collision_flags + metrics.ch4_physical_tables (review P1, stage 4)."""
import csv

from metrics.ch4_physical_tables import _sci, build, fmt_q, table_h2_panel
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


def _h2_row(attack, policy, drift, i):
    acting = policy != "detect_only"
    return {"run_id": "%s_%s_%d" % (attack, policy, i), "policy": policy,
            "attack": attack, "included": True, "action_ok": acting,
            "t_action_s": 3.0 if acting else None,
            "drift_itt_m": drift if acting else None,
            "t_estimate_jump_s": 7.5, "nav_error_end_m": 50.0,
            "waypoints_captured": 1 if acting else 2}


def _h2_rows(trust_drift):
    rows = []
    for a in ("gps_spoofing", "monitor_takeout+gps_spoofing",
              "detector_takeout+gps_spoofing"):
        for i in range(8):
            rows.append(_h2_row(a, "proportionate", 50.0 + 0.01 * i, i))
            rows.append(_h2_row(a, "trust_aware", trust_drift + 0.01 * i, i))
            rows.append(_h2_row(a, "detect_only", None, i))
    return rows


def test_panel_b_accepts_small_drift_and_reports_verdict():
    md = "\n".join(table_h2_panel(_h2_rows(1.5)))
    assert "Панель B" in md
    assert md.count("→ прийнято") == 2          # two confirmatory cells
    assert "описово: Δ медіан −" in md           # detector takeout, no test
    assert "H2 підтверджено." in md
    assert "3.00 (8/8)" in md


def test_panel_b_rejects_when_median_above_bound():
    # significantly smaller than LOITER, but above the 7.91 m bound
    md = "\n".join(table_h2_panel(_h2_rows(20.0)))
    assert md.count("→ не прийнято") == 2
    assert "H2 не підтверджено." in md


def test_sci_format():
    assert _sci(3.7e-06) == "3.7·10⁻⁶"


def test_build_without_h2_has_no_panel_b(tmp_path):
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
    md = build(str(p), str(m), str(f), h2_json=None)
    assert "Панель A" in md and "Панель B. Перевірочна" not in md
