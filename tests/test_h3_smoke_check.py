"""H3 step 10: the smoke-flight setup check reads only the declared
fields (H3_PREREGISTRATION.md, Implementation item 10)."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

_P = Path(__file__).resolve().parent.parent / "scripts" / "h3_smoke_check.py"
_spec = importlib.util.spec_from_file_location("h3_smoke_check", _P)
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

T0 = 1000.0
MON = {"ranging_evaluated": 400, "ranging_no_own_position": 2,
       "ranging_no_range": 1, "handler_errors": 0}
GOOD = {
    "error": None,
    "range_source": {"kind": "simulated_uwb", "seed": 12345},
    "attack_evidence": {"gps_spoofing": {
        "t_target_set": T0, "rate_confirmed": True, "spoof_rate": 0.02}},
    "trajectory_stats": {"samples_written": 5000, "on_sample_errors": 0},
    "monitor_stats": [dict(MON), dict(MON), dict(MON)],
}
SENTINEL = "SENTINEL_ALARM_EVIDENCE"


def ok(rows):
    return all(r[2] for r in rows)


def failed(rows):
    return {r[0] for r in rows if not r[2]}


def good():
    return copy.deepcopy(GOOD)


def test_good_passes():
    assert ok(S.check(good(), T0 + 125.0, 100))


@pytest.mark.parametrize("mut, field", [
    (lambda s: s.update(error="boom"), "error"),
    (lambda s: s.update(range_source=None), "range_source.seed"),
    (lambda s: s["range_source"].pop("seed"), "range_source.seed"),
    (lambda s: s["attack_evidence"]["gps_spoofing"].pop("t_target_set"), "t_target_set"),
    (lambda s: s["attack_evidence"]["gps_spoofing"].update(rate_confirmed=False), "rate_confirmed"),
    (lambda s: s["attack_evidence"]["gps_spoofing"].update(rate_confirmed=None), "rate_confirmed"),
    (lambda s: s["attack_evidence"]["gps_spoofing"].update(spoof_rate=0.006667), "spoof_rate"),
    (lambda s: s["trajectory_stats"].update(samples_written=0), "trajectory_stats.samples_written"),
    (lambda s: s["trajectory_stats"].pop("on_sample_errors"), "trajectory_stats.on_sample_errors"),
    (lambda s: s["trajectory_stats"].update(on_sample_errors=3), "trajectory_stats.on_sample_errors"),
    (lambda s: s["monitor_stats"].pop(), "monitors"),
    (lambda s: s["monitor_stats"][1].update(handler_errors=1), "monitor[1].handler_errors"),
    (lambda s: s["monitor_stats"][2].update(ranging_evaluated=0),
     "monitor[2].ranging (evaluated/no_own/no_range)"),
    (lambda s: s["monitor_stats"][0].pop("ranging_evaluated"),
     "monitor[0].ranging (evaluated/no_own/no_range)"),
    (lambda s: s["monitor_stats"][0].update(ranging_no_range=30), "monitor[0].evaluated_share"),
])
def test_each_field_can_fail(mut, field):
    s = good()
    mut(s)
    assert field in failed(S.check(s, T0 + 125.0, 100))


def test_share_boundary():
    s = good()
    s["monitor_stats"][0].update(ranging_evaluated=95, ranging_no_own_position=3,
                                 ranging_no_range=2)
    assert "monitor[0].evaluated_share" not in failed(S.check(s, T0 + 125.0, 100))
    s["monitor_stats"][0]["ranging_no_range"] = 3
    assert "monitor[0].evaluated_share" in failed(S.check(s, T0 + 125.0, 100))


def test_no_truth_rows_fails():
    assert "uav_0_truth_rows" in failed(S.check(good(), T0 + 125.0, 0))


def test_window_short():
    assert "window_short_s" in failed(S.check(good(), T0 + 119.0, 100))
    assert "window_short_s" in failed(S.check(good(), None, 100))
    assert "window_short_s" not in failed(S.check(good(), T0 + 120.0, 100))


def _run_dir(tmp_path, summary=None):
    d = tmp_path / "runs_h3_smoke" / "run_x_r1"
    d.mkdir(parents=True)
    (d / "run_summary.json").write_text(json.dumps(summary or good()))
    events = [
        {"event_type": "attack", "phase": "inject_start", "timestamp": T0 + 0.1},
        {"event_type": "security", "detector": "ranging", "target_uav": "uav_0",
         "timestamp": T0 + 9.0, "evidence": {"note": SENTINEL}},
        {"event_type": "security", "detector": "gps", "target_uav": "uav_0",
         "timestamp": T0 + 3.0, "evidence": {"note": SENTINEL}},
        {"event_type": "attack", "phase": "inject_end", "timestamp": T0 + 125.1},
    ]
    (d / "merged.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    traj = [{"uav_id": u, "t_wall": T0 + k, "x": 1.0, "y": 2.0}
            for k in range(4) for u in ("uav_0", "uav_1", "uav_2")]
    (d / "trajectory.jsonl").write_text("\n".join(json.dumps(r) for r in traj) + "\n")
    return d


def test_markers_and_rows_from_files(tmp_path):
    d = _run_dir(tmp_path)
    assert S.inject_end_marker(str(d / "merged.jsonl")) == T0 + 125.1
    assert S.victim_rows(str(d / "trajectory.jsonl")) == 4
    assert ok(S.check_run(str(d)))


def test_main_prints_no_alarm_content(tmp_path, capsys):
    d = _run_dir(tmp_path)
    assert S.main(["x", str(d.parent)]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    for forbidden in (SENTINEL, "security", "detector", "target_uav", "gps\n"):
        assert forbidden not in out


def test_main_fail_exit_code(tmp_path, capsys):
    s = good()
    s["attack_evidence"]["gps_spoofing"]["rate_confirmed"] = False
    d = _run_dir(tmp_path, s)
    assert S.main(["x", str(d.parent)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_empty_root(tmp_path, capsys):
    (tmp_path / "r").mkdir()
    assert S.main(["x", str(tmp_path / "r")]) == 1
