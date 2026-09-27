"""scripts/run_batch.py for B1 / H3 (item 9b): spoof-rate levels in cells,
C_RANGING, the pre-registered 20-flight preset. v1 cells unchanged."""
import argparse
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import run_batch as rb  # noqa: E402

from metrics import h3_analysis as h3  # noqa: E402


def _h3_cell_name(c):
    """run_batch Cell -> the cell name metrics.h3_analysis.cell_of gives."""
    if c.attack == "none":
        return f"none@{c.policy}"
    dt = "DT+" if c.attack.startswith("detector_takeout+") else ""
    return f"{dt}{c.level}@{c.policy}"


def test_level_rates_mirror_h3_analysis():
    assert rb.LEVEL_RATES == h3.LEVEL_RATES


def test_v1_cell_key_unchanged():
    (c,) = rb.parse_cells("C/gps_spoofing@trust_aware")
    assert c.key == "C/gps_spoofing@trust_aware" and c.level is None and c.spoof_rate is None


def test_level_parsed_into_key_and_rate():
    (c,) = rb.parse_cells("C_RANGING/gps_spoofing:L1@detect_only")
    assert c.key == "C_RANGING/gps_spoofing:L1@detect_only"
    assert c.level == "L1" and c.spoof_rate == 0.0006667


def test_levels_of_one_cell_do_not_shadow_on_resume():
    a, b = rb.parse_cells("C_RANGING/gps_spoofing:L1,C_RANGING/gps_spoofing:L3")
    assert a.key != b.key


@pytest.mark.parametrize("spec", ["C_RANGING/none:L1", "C/comm_disruption:L3",
                                  "C_RANGING/gps_spoofing:L2", "C_RANGING/gps_spoofing:"])
def test_bad_level_rejected(spec):
    with pytest.raises(ValueError):
        rb.parse_cells(spec)


def test_c_ranging_accepts_policies():
    cells = rb.parse_cells("C_RANGING/gps_spoofing:L1@trust_aware,C_RANGING/none@detect_only")
    assert [c.policy for c in cells] == ["trust_aware", "detect_only"]
    assert rb.apply_default_policy(rb.parse_cells("C_RANGING/none"), "detect_only")[0].policy == "detect_only"
    with pytest.raises(ValueError):
        rb.parse_cells("B/gps_spoofing:L1@trust_aware")


def _args(**kw):
    a = rb.parse_args([])
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def test_trial_command_passes_rate_and_arch(tmp_path):
    (c,) = rb.parse_cells("C_RANGING/detector_takeout+gps_spoofing:L1@detect_only")
    cmd = rb.trial_command(c, _args(), tmp_path, "rid")
    assert cmd[cmd.index("--arch") + 1] == "c_ranging"
    assert cmd[cmd.index("--attack") + 1] == "detector_takeout+gps_spoofing"
    assert float(cmd[cmd.index("--spoof-rate") + 1]) == 0.0006667
    assert cmd[cmd.index("--recovery-policy") + 1] == "detect_only"


def test_trial_command_v1_has_no_rate(tmp_path):
    (c,) = rb.parse_cells("C/gps_spoofing")
    cmd = rb.trial_command(c, _args(), tmp_path, "rid")
    assert "--spoof-rate" not in cmd and cmd[cmd.index("--arch") + 1] == "c"


def test_trial_run_id():
    (c,) = rb.parse_cells("C_RANGING/gps_spoofing:L10@detect_only")
    assert rb.trial_run_id(c, 2, 123) == "C_RANGING_gps_spoofing_L10_detect_only_r2_123"
    (v1,) = rb.parse_cells("C/gps_spoofing@trust_aware")
    assert rb.trial_run_id(v1, 1, 5) == "C_gps_spoofing_trust_aware_r1_5"


# --- preset h3 ----------------------------------------------------------------

def test_h3_preset_matches_preregistered_design():
    trials = rb.h3_trials()
    assert len(trials) == 20
    counts = {}
    for c, _r in trials:
        counts[_h3_cell_name(c)] = counts.get(_h3_cell_name(c), 0) + 1
    assert counts == h3.PLANNED
    assert all(c.arch == "C_RANGING" for c, _ in trials)


def test_h3_preset_replicates_unique_and_numbered():
    trials = rb.h3_trials()
    assert len({(c.key, r) for c, r in trials}) == 20
    for cell, n in rb.H3_ATTACK_CELLS:
        assert sorted(r for c, r in trials if c == cell) == list(range(1, n + 1))


def test_h3_preset_order():
    trials = rb.h3_trials()
    none = [i for i, (c, _) in enumerate(trials) if c.attack == "none"]
    assert none[0] == 0 and none[-1] == len(trials) - 1 and len(none) == 3
    assert 5 <= none[1] <= 14
    l1 = [i for i, (c, _) in enumerate(trials)
          if c == rb.H3_ATTACK_CELLS[0][0]]
    assert l1[0] <= 3 and l1[-1] >= 16          # spread, not piled at the end
    assert [c.key for c, _ in trials[1:8]] == [c.key for c, _ in rb.H3_ATTACK_CELLS]


def test_apply_preset_fixes_timing():
    a = rb.parse_args(["--preset", "h3"])
    trials = rb.apply_preset(a)
    assert len(trials) == 20
    assert (a.attack_at_sec, a.obs_sec, a.altitude_layer_step, a.target_uav) == \
        (90.0, 125.0, 5.0, "uav_0")
    assert rb.H3_OBS_SEC >= h3.WINDOW_S + 5.0


def test_no_preset_leaves_args():
    a = rb.parse_args([])
    assert rb.apply_preset(a) is None
    assert (a.obs_sec, a.altitude_layer_step) == (60.0, None)


def test_main_dry_run_preset(capsys, tmp_path):
    assert rb.main(["--preset", "h3", "--log-root", str(tmp_path / "r"), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "20. C_RANGING/none@detect_only r3" in out
    assert "--spoof-rate" not in out.splitlines()[-1]           # trial 1 = no-attack
    assert not (tmp_path / "r").exists()
