"""run_batch policy arms + trial order (review stage 3)."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import run_batch as rb  # noqa: E402

from core.config import VALID_RECOVERY_POLICIES  # noqa: E402


def test_policies_mirror_config():
    assert rb.VALID_POLICIES == set(VALID_RECOVERY_POLICIES)


def test_legacy_cells_unchanged():
    c = rb.parse_cells("C/gps_spoofing")[0]
    assert c.policy is None
    assert c.key == "C/gps_spoofing"   # old manifests still resume


def test_policy_suffix_parsed_and_in_key():
    cells = rb.parse_cells(
        "C/gps_spoofing@trust_aware,C/detector_takeout+gps_spoofing@detect_only")
    assert cells[0].policy == "trust_aware"
    assert cells[0].key == "C/gps_spoofing@trust_aware"
    assert cells[1].attack == "detector_takeout+gps_spoofing"
    assert cells[1].key == "C/detector_takeout+gps_spoofing@detect_only"


def test_arms_of_one_cell_do_not_shadow_on_resume():
    keys = {c.key for c in rb.parse_cells(
        "C/gps_spoofing@proportionate,C/gps_spoofing@trust_aware,"
        "C/gps_spoofing@detect_only")}
    assert len(keys) == 3


@pytest.mark.parametrize("spec", ["C/gps_spoofing@aggressive",
                                  "A/gps_spoofing@trust_aware"])
def test_bad_policy_rejected(spec):
    with pytest.raises(ValueError):
        rb.parse_cells(spec)


def test_default_policy_fills_only_unset_cells():
    cells = rb.apply_default_policy(
        rb.parse_cells("C/gps_spoofing,C/gps_spoofing@detect_only"), "trust_aware")
    assert [c.policy for c in cells] == ["trust_aware", "detect_only"]
    assert rb.apply_default_policy(rb.parse_cells("A/none"), None)[0].policy is None


def test_default_policy_rejected_for_a():
    with pytest.raises(ValueError):
        rb.apply_default_policy(rb.parse_cells("A/gps_spoofing"), "trust_aware")


def test_trial_orders():
    cells = rb.parse_cells("C/gps_spoofing@proportionate,C/gps_spoofing@trust_aware")
    cm = rb.build_trials(cells, 2, "cell-major")
    rm = rb.build_trials(cells, 2, "replicate-major")
    assert [(c.policy, r) for c, r in cm] == [
        ("proportionate", 1), ("proportionate", 2),
        ("trust_aware", 1), ("trust_aware", 2)]
    assert [(c.policy, r) for c, r in rm] == [
        ("proportionate", 1), ("trust_aware", 1),
        ("proportionate", 2), ("trust_aware", 2)]
    assert sorted(cm, key=lambda t: (t[0].key, t[1])) == \
        sorted(rm, key=lambda t: (t[0].key, t[1]))


def test_order_flag_default_is_historical():
    assert rb.parse_args([]).order == "cell-major"
    assert rb.parse_args(["--order", "replicate-major"]).order == "replicate-major"
