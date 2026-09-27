"""metrics.fp_contact (OPEN-5: FP / baseline peaks vs peer contacts)."""
from metrics.fp_contact import (
    binom_sf, coincident, contact_starts, peak_episode_starts, verdict,
)


def _track(x0, v=0.0, z=20.0, t0=100.0, n=601, dt=0.1, ground=10):
    # `ground` samples on the pad (z=0), then airborne at z
    out = [(t0 + i * dt, x0, 0.0, 0.0) for i in range(ground)]
    out += [(t0 + (ground + i) * dt, x0 + v * i * dt, 0.0, z) for i in range(n)]
    return out


def test_contact_detected_once_when_peer_passes_through():
    xyz = {"uav_0": _track(0.0), "uav_1": _track(-30.0, v=2.0)}
    s = contact_starts(xyz, "uav_0", 0.0, 1e9)
    assert len(s) == 1
    assert abs(s[0] - (101.0 + 15.0)) < 0.6


def test_no_contact_on_the_ground():
    # both on the pad 0.5 m apart, never airborne -> not a contact
    a = [(100.0 + i * 0.1, 0.0, 0.0, 0.0) for i in range(100)]
    b = [(100.0 + i * 0.1, 0.5, 0.0, 0.0) for i in range(100)]
    assert contact_starts({"uav_0": a, "uav_1": b}, "uav_0", 0.0, 1e9) == []


def test_coincidence_window_is_lookback_10_lead_1():
    assert coincident(110.0, [100.0])
    assert coincident(110.0, [111.0])
    assert not coincident(110.0, [99.9])
    assert not coincident(110.0, [111.1])


def test_peak_episodes_merge_within_gap_and_need_airborne():
    t = [0, 1, 2, 3, 6, 7, 8]
    e = [0.2, 1.5, 1.4, 0.3, 1.2, 0.1, 5.0]
    air = lambda tt: tt != 8
    assert peak_episode_starts(t, e, air) == [1, 6]


def test_binom_sf_edges():
    assert binom_sf(0, 5, 0.1) == 1.0
    assert abs(binom_sf(5, 5, 0.5) - 1 / 32) < 1e-12


def test_verdict_rules():
    assert verdict(9, 10, 0.07)["verdict"] == "ARTEFACT"
    assert verdict(1, 10, 0.07)["verdict"] == "NOT_EXPLAINED"
    assert verdict(6, 11, 0.077)["verdict"] == "MIXED"
    # high fraction but not beyond chance (p0 high) -> never ARTEFACT
    assert verdict(4, 5, 0.7)["verdict"] != "ARTEFACT"
