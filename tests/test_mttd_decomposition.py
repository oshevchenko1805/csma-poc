"""metrics.mttd_decomposition (review P15, thesis п. 4.2, табл. 4.2)."""
import os

import pytest

from detectors.gps import GpsSpoofingDetector
from metrics import mttd_decomposition as md


def _m(run_id, attack="gps_spoofing", arch="C", valid="True", detected="True",
       mttd="2.9", first="0.9", n_above="6", maxcons="6"):
    return {"run_id": run_id, "attack": attack, "architecture": arch,
            "valid": valid, "detected": detected, "mttd_s": mttd,
            "ratio_first_cross_s": first, "ratio_n_above": n_above,
            "ratio_maxcons_full": maxcons}


def test_floor_follows_the_shipped_detector_parameter():
    assert md.K == GpsSpoofingDetector.DEFAULT_SUSTAINED_SAMPLES
    assert md.FLOOR_S == pytest.approx((md.K - 1) / md.NOMINAL_RATE_HZ)


def test_classify_floor_late_streak_unexplained():
    assert md.classify(md.FLOOR_S, 6, 6) == "floor"
    assert md.classify(md.FLOOR_S + md.TOL_S * 0.9, 6, 6) == "floor"
    # later firing streak, one breach outside it -> explained
    assert md.classify(md.FLOOR_S + 2.0, 8, 7) == "late_streak"
    # later firing but every breach is in one streak -> not explained
    assert md.classify(md.FLOOR_S + 2.0, 7, 7) == "unexplained"
    # faster than the floor is impossible under the sustain rule
    assert md.classify(md.FLOOR_S - 1.0, 6, 6) == "unexplained"
    assert md.classify(md.FLOOR_S + 2.0, None, 7) == "unexplained"


def test_local_rows_filter_valid_detected_and_local_cells_only():
    master = [
        _m("ok"),
        _m("invalid", valid="False"),
        _m("missed", detected="False", mttd=""),
        _m("other_attack", attack="command_injection"),
        _m("cross_path", attack="detector_takeout+gps_spoofing"),
        _m("a_takeout", attack="monitor_takeout+gps_spoofing", arch="A"),
        _m("no_series", first=""),
    ]
    rows = {r["run_id"]: r for r in md.local_rows(master)}
    assert set(rows) == {"ok", "no_series"}
    assert rows["ok"]["delta"] == pytest.approx(2.0)
    assert rows["ok"]["class"] == "floor"
    assert rows["no_series"]["class"] == "no_series"


def test_cross_rows_reference_the_estimate_jump():
    master = [_m("x1", attack="detector_takeout+gps_spoofing", mttd="7.5"),
              _m("x2", attack="detector_takeout+gps_spoofing", mttd="7.0"),
              _m("gps", mttd="2.9")]
    phys = [{"run_id": "x1", "t_estimate_jump_s": "7.4"},
            {"run_id": "x2", "t_estimate_jump_s": ""}]
    rows = {r["run_id"]: r for r in md.cross_rows(master, phys)}
    assert set(rows) == {"x1", "x2"}
    assert rows["x1"]["delta"] == pytest.approx(0.1)
    assert rows["x2"]["delta"] is None


def test_summary_and_markdown_report_exceptions():
    master = [_m("a%d" % i, arch="A", mttd=str(0.8 + i * 0.01 + 2.0),
                 first=str(0.8 + i * 0.01)) for i in range(5)]
    master.append(_m("late", mttd="5.0", first="1.0", n_above="8", maxcons="7"))
    s = md.summary(md.local_rows(master), [])
    assert s["n_local"] == 6 and s["n_floor"] == 5
    assert s["pooled_floor_median"] == pytest.approx(2.0)
    assert s["implied_rate_hz"] == pytest.approx(1.0)
    assert [x["run_id"] for x in s["exceptions"]] == ["late"]
    text = md.build_md(s)
    assert "late: late_streak" in text
    assert "| GPS spoofing | A | локальний детектор | 5 |" in text
    assert "| 5/5 |" in text


MASTER = os.path.join("runs_campaign", "campaign_master.csv")
PHYS = os.path.join("runs_campaign", "physical_outcomes.csv")


@pytest.mark.skipif(not (os.path.exists(MASTER) and os.path.exists(PHYS)),
                    reason="authorised campaign CSVs not present")
def test_regression_on_authorised_master():
    """Numbers quoted in thesis табл. 3.4 and 4.2 (main campaign)."""
    from metrics.plots import load
    master, phys = load(MASTER), load(PHYS)
    s = md.summary(md.local_rows(master), md.cross_rows(master, phys))
    assert s["n_local"] == 102
    assert s["n_floor"] == 101
    assert [x["class"] for x in s["exceptions"]] == ["late_streak"]
    assert s["pooled_floor_median"] == pytest.approx(1.993, abs=0.001)
    assert len(s["cross"]) == 30
    assert all(x["delta"] is not None for x in s["cross"])
