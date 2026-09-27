"""Tests for RangingConsistencyDetector and its pure helpers (H3, B1)."""

from __future__ import annotations

import math

import pytest

from core.events import PeerPositionAnnounce, SecurityEvent
from detectors.cross_check import haversine_distance_m
from detectors.ranging import (
    PairStatus,
    RangingConsistencyDetector,
    attribute,
    distance_3d_m,
    interpolate_position,
    local_offset_m,
    next_streaks,
    residual_m,
)

REF = (47.397742, 8.545594, 488.0)  # PX4 SITL home
R = 6_371_000.0


def geo(e: float, n: float, u: float) -> tuple[float, float, float]:
    """Local (east, north, up) metres around REF -> (lat, lon, alt)."""
    lat = REF[0] + math.degrees(n / R)
    lon = REF[1] + math.degrees(e / (R * math.cos(math.radians(REF[0]))))
    return lat, lon, REF[2] + u


def ann(uav_id: str, enu, t: float) -> PeerPositionAnnounce:
    lat, lon, alt = geo(*enu)
    return PeerPositionAnnounce(source=f"monitor_{uav_id}", uav_id=uav_id,
                                lat=lat, lon=lon, alt=alt, sample_timestamp=t)


def dist(a, b) -> float:
    return math.dist(a, b)


def make(monitor="uav_0", ranges=None, **kw) -> RangingConsistencyDetector:
    """Detector whose range_fn reads a dict peer -> range (or callable)."""
    ranges = {} if ranges is None else ranges

    def fn(peer, t):
        v = ranges.get(peer)
        return v(t) if callable(v) else v

    return RangingConsistencyDetector(monitor, f"monitor_{monitor}", fn, **kw)


def own(det, enu, t):
    det.feed_own_position(*geo(*enu), sample_ts=t)


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


class TestGeometry:
    def test_offset_round_trip(self):
        e, n, u = local_offset_m(REF, geo(12.0, -7.0, 5.0))
        assert e == pytest.approx(12.0, abs=1e-3)
        assert n == pytest.approx(-7.0, abs=1e-3)
        assert u == pytest.approx(5.0, abs=1e-9)

    def test_distance_zero_and_vertical(self):
        assert distance_3d_m(REF, REF) == 0.0
        assert distance_3d_m(geo(0, 0, 0), geo(0, 0, 10)) == pytest.approx(10.0)

    def test_horizontal_matches_haversine(self):
        a, b = geo(0, 0, 0), geo(30.0, 40.0, 0)
        d = distance_3d_m(a, b)
        assert d == pytest.approx(50.0, abs=1e-3)
        assert d == pytest.approx(haversine_distance_m(a[0], a[1], b[0], b[1]), abs=1e-3)

    def test_distance_symmetric(self):
        a, b = geo(3, 4, 5), geo(-8, 1, 15)
        assert distance_3d_m(a, b) == pytest.approx(distance_3d_m(b, a), abs=1e-9)

    def test_residual_sign(self):
        assert residual_m(10.0, 8.0) == 2.0
        assert residual_m(8.0, 10.0) == -2.0


class TestInterpolate:
    S = [(0.0, 1.0, 10.0, 100.0), (0.1, 2.0, 20.0, 200.0), (2.0, 3.0, 30.0, 300.0)]

    def test_empty(self):
        assert interpolate_position([], 1.0, 0.5) is None

    def test_exact(self):
        assert interpolate_position(self.S, 0.1, 0.5) == (2.0, 20.0, 200.0)

    def test_linear_inside_small_gap(self):
        assert interpolate_position(self.S, 0.05, 0.5) == pytest.approx((1.5, 15.0, 150.0))

    def test_no_interpolation_across_gap_nearest_within_tolerance(self):
        # bracket 0.1..2.0 is wider than 0.5 s: nearest sample, if close
        assert interpolate_position(self.S, 0.4, 0.5) == (2.0, 20.0, 200.0)
        assert interpolate_position(self.S, 1.7, 0.5) == (3.0, 30.0, 300.0)

    def test_none_in_middle_of_gap(self):
        assert interpolate_position(self.S, 1.0, 0.5) is None

    def test_hold_after_last_and_before_first(self):
        assert interpolate_position(self.S, 2.4, 0.5) == (3.0, 30.0, 300.0)
        assert interpolate_position(self.S, -0.3, 0.5) == (1.0, 10.0, 100.0)
        assert interpolate_position(self.S, 2.6, 0.5) is None


class TestStreaks:
    def test_bad_strict_greater(self):
        assert next_streaks(2, 0, 1.8, 1.8, 1.3) == (0, 0)
        assert next_streaks(2, 0, 1.81, 1.8, 1.3) == (3, 0)

    def test_fine_inclusive(self):
        assert next_streaks(0, 2, 1.3, 1.8, 1.3) == (0, 3)

    def test_between_thresholds_is_neither(self):
        assert next_streaks(4, 4, 1.5, 1.8, 1.3) == (0, 0)


B, F, P = PairStatus(True, False), PairStatus(False, True), PairStatus(False, False)


class TestAttribute:
    def test_bad_and_fine_flags_bad_peer(self):
        assert attribute("uav_1", {"uav_0": B, "uav_2": F}) == {"uav_0"}

    def test_all_bad_flags_self(self):
        assert attribute("uav_0", {"uav_1": B, "uav_2": B}) == {"uav_0"}

    def test_bad_with_pending_other_flags_nobody(self):
        # 2a would have flagged uav_1 here ("not bad"); [2c] needs "fine"
        assert attribute("uav_0", {"uav_1": B, "uav_2": P}) == frozenset()

    def test_single_heard_pair_is_ambiguous(self):
        assert attribute("uav_0", {"uav_1": B}) == frozenset()

    def test_nothing_heard(self):
        assert attribute("uav_0", {}) == frozenset()

    def test_all_fine(self):
        assert attribute("uav_0", {"uav_1": F, "uav_2": F}) == frozenset()

    def test_four_uavs_two_bad_one_fine(self):
        assert attribute("uav_0", {"uav_1": B, "uav_2": B, "uav_3": F}) == {"uav_1", "uav_2"}

    def test_latch_blocks_peer_path(self):
        assert attribute("uav_0", {"uav_1": B, "uav_2": F}, self_latched=True) == frozenset()

    def test_latch_keeps_self_path(self):
        assert attribute("uav_0", {"uav_1": B, "uav_2": B}, self_latched=True) == {"uav_0"}


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_defaults_are_the_preregistered_values(self):
        assert RangingConsistencyDetector.DEFAULT_THETA_M == 1.8
        assert RangingConsistencyDetector.DEFAULT_THETA_OK_M == 1.3
        assert RangingConsistencyDetector.DEFAULT_SUSTAIN == 3

    def test_name_and_ids(self):
        d = make("uav_2")
        assert d.name == "ranging"
        assert d.monitor_uav_id == "uav_2"
        assert not d.self_latched

    @pytest.mark.parametrize("kw", [
        {"theta_m": 0.0},
        {"theta_ok_m": 0.0},
        {"theta_m": 1.0, "theta_ok_m": 1.5},
        {"sustain": 0},
        {"own_max_gap_s": 0.0},
        {"own_history_s": -1.0},
        {"stale_after_s": 0.0},
    ])
    def test_invalid(self, kw):
        with pytest.raises(ValueError):
            make(**kw)

    def test_range_fn_must_be_callable(self):
        with pytest.raises(ValueError):
            RangingConsistencyDetector("uav_0", "m", None)

    def test_empty_monitor_id(self):
        with pytest.raises(ValueError):
            RangingConsistencyDetector("", "m", lambda p, t: 1.0)


# ---------------------------------------------------------------------------
# Detector on one monitor (uav_1 watching uav_0 and uav_2)
# ---------------------------------------------------------------------------

# uav_1 at the origin; honest uav_2 20 m east; uav_0 20 m north.
P1, P2, P0 = (0.0, 0.0, 10.0), (20.0, 0.0, 10.0), (0.0, 20.0, 10.0)


def run_peer_monitor(offsets, ranges_override=None, own_ok=None):
    """uav_1's detector; uav_0 announces P0 + (0, offset, 0) at t = 0, 1, ...

    True ranges are exact. Returns the events per tick.
    """
    r = {"uav_0": dist(P1, P0), "uav_2": dist(P1, P2)}
    if ranges_override:
        r.update(ranges_override)
    d = make("uav_1", r)
    out = []
    for t, off in enumerate(offsets):
        t = float(t)
        if own_ok is None or own_ok(t):
            own(d, P1, t)
        ev = d.feed_peer_position(ann("uav_2", P2, t))
        ev += d.feed_peer_position(ann("uav_0", (P0[0], P0[1] + off, P0[2]), t))
        out.append(ev)
    return d, out


def first_tick(out, target):
    for i, ev in enumerate(out):
        if any(e.target_uav == target for e in ev):
            return i
    return None


class TestPeerPath:
    def test_honest_swarm_no_events(self):
        _, out = run_peer_monitor([0.0] * 10)
        assert all(ev == [] for ev in out)

    def test_fires_on_third_consecutive_bad(self):
        # offset 3 m along the line of sight -> rho = +3 m from tick 3 on
        _, out = run_peer_monitor([0, 0, 0, 3, 3, 3, 3])
        assert first_tick(out, "uav_0") == 5
        ev = out[5][0]
        assert isinstance(ev, SecurityEvent)
        assert ev.detector == "ranging"
        assert ev.target_uav == "uav_0"
        assert ev.source == "monitor_uav_1"
        assert ev.evidence["path"] == "peer"
        assert ev.evidence["trigger_peer"] == "uav_0"
        assert ev.evidence["pairs"]["uav_0"]["rho_m"] == pytest.approx(3.0, abs=1e-3)
        assert ev.evidence["pairs"]["uav_2"]["fine"] is True
        assert ev.evidence["theta_m"] == 1.8 and ev.evidence["theta_ok_m"] == 1.3

    def test_negative_residual_counts(self):
        _, out = run_peer_monitor([0, 0, 0, -3, -3, -3])
        assert first_tick(out, "uav_0") == 5

    def test_between_thresholds_neither_bad_nor_fine(self):
        # |rho| = 1.6 m: not bad (<= theta), not fine (> theta_ok)
        _, out = run_peer_monitor([0, 0, 0] + [1.6] * 5)
        assert first_tick(out, "uav_0") is None

    def test_streak_broken_by_good_sample(self):
        _, out = run_peer_monitor([0, 0, 0, 3, 3, 0, 3, 3, 0])
        assert first_tick(out, "uav_0") is None

    def test_hysteresis_one_event_per_cycle_and_refire(self):
        d, out = run_peer_monitor([0, 0, 0, 3, 3, 3, 3, 3, 0, 0, 3, 3, 3])
        fired = [i for i, ev in enumerate(out) if ev]
        assert fired == [5, 12]
        assert d.is_alerted("uav_0")

    def test_missing_range_resets_streak(self):
        rng = dist(P1, P0)

        def r0(t):
            return None if t == 5.0 else rng
        _, out = run_peer_monitor([0, 0, 0, 3, 3, 3, 3, 3, 3], {"uav_0": r0})
        assert first_tick(out, "uav_0") == 8   # 3, 4, gap at 5, then 6, 7, 8

    def test_missing_own_position_resets_streak(self):
        _, out = run_peer_monitor([0, 0, 0, 3, 3, 3, 3, 3, 3],
                                  own_ok=lambda t: t != 5.0)
        assert first_tick(out, "uav_0") == 8

    def test_nonfinite_range_is_a_gap(self):
        _, out = run_peer_monitor([0, 0, 0, 3, 3, 3, 3],
                                  {"uav_0": lambda t: float("nan") if t == 4.0 else dist(P1, P0)})
        assert first_tick(out, "uav_0") is None

    def test_needs_fine_other_pair(self):
        """Only uav_0 heard for the first ticks: ambiguous, no flag; the
        flag comes once uav_2 has been fine for 3 announcements."""
        r = {"uav_0": dist(P1, P0), "uav_2": dist(P1, P2)}
        d = make("uav_1", r)
        fired = []
        for t in range(8):
            t = float(t)
            own(d, P1, t)
            if t >= 3:
                fired += [(t, e) for e in d.feed_peer_position(ann("uav_2", P2, t))]
            fired += [(t, e) for e in d.feed_peer_position(
                ann("uav_0", (P0[0], P0[1] + 3.0, P0[2]), t))]
        assert [t for t, _ in fired] == [5.0]

    def test_stale_peer_is_not_heard(self):
        """uav_2 stops announcing; after stale_after_s its fine status no
        longer counts, so a new bad cycle against uav_0 is ambiguous."""
        r = {"uav_0": dist(P1, P0), "uav_2": dist(P1, P2)}
        d = make("uav_1", r)
        fired = []
        for t in range(12):
            t = float(t)
            own(d, P1, t)
            if t <= 3:
                d.feed_peer_position(ann("uav_2", P2, t))
            off = 3.0 if t >= 7 else 0.0
            fired += [t for _ in d.feed_peer_position(
                ann("uav_0", (P0[0], P0[1] + off, P0[2]), t))]
        assert fired == []

    def test_self_announcement_and_empty_id_ignored(self):
        d = make("uav_1", {"uav_1": 0.0})
        own(d, P1, 0.0)
        assert d.feed_peer_position(ann("uav_1", P1, 0.0)) == []
        assert d.feed_peer_position(ann("", P1, 0.0)) == []

    def test_own_samples_out_of_order(self):
        d = make("uav_1", {"uav_0": dist(P1, P0)})
        own(d, P1, 1.0)
        own(d, (0.0, -10.0, 10.0), 0.0)   # late arrival of an older sample
        assert [s[0] for s in d._own.samples] == [0.0, 1.0]

    def test_own_history_is_pruned(self):
        d = make("uav_1", {}, own_history_s=2.0)
        for t in range(10):
            own(d, P1, float(t))
        assert [s[0] for s in d._own.samples] == [7.0, 8.0, 9.0]

    def test_reset(self):
        d, out = run_peer_monitor([0, 0, 0, 3, 3, 3])
        assert d.is_alerted("uav_0")
        d.reset()
        assert not d.is_alerted("uav_0")
        assert d._pairs == {} and d._own.samples == []


# ---------------------------------------------------------------------------
# Self path and latch (the victim's own monitor)
# ---------------------------------------------------------------------------


class TestSelfPathAndLatch:
    def _victim(self, own_offsets, peers=((20.0, 0.0, 10.0), (0.0, 20.0, 10.0))):
        """uav_0 truly at the origin; its own belief is shifted by own_offsets
        (east, north per tick). Peers honest, exact ranges."""
        truth0 = (0.0, 0.0, 10.0)
        p1, p2 = peers
        d = make("uav_0", {"uav_1": dist(truth0, p1), "uav_2": dist(truth0, p2)})
        out = []
        for t, (de, dn) in enumerate(own_offsets):
            t = float(t)
            own(d, (de, dn, 10.0), t)
            ev = d.feed_peer_position(ann("uav_1", p1, t))
            ev += d.feed_peer_position(ann("uav_2", p2, t))
            out.append(ev)
        return d, out

    def test_self_flag_when_inconsistent_with_everyone(self):
        # belief 10 m south-west: both ranges off by > theta
        d, out = self._victim([(0, 0)] * 3 + [(-10, -10)] * 4)
        assert first_tick(out, "uav_0") == 5
        ev = [e for e in out[5] if e.target_uav == "uav_0"][0]
        assert ev.evidence["path"] == "self"
        assert d.self_latched
        assert all(e.target_uav == "uav_0" for ev in out for e in ev)

    def test_perpendicular_error_is_ambiguous_before_self_flag(self):
        """Stated limit: error along the line of sight to uav_2 only (north),
        perpendicular to uav_1 (east): the victim's monitor sees 'bad with
        uav_2, fine with uav_1' and flags uav_2."""
        _, out = self._victim([(0, 0)] * 3 + [(0, 3)] * 4)
        assert first_tick(out, "uav_2") == 5

    def test_latch_blocks_later_peer_flags(self):
        # self flag at tick 5; then the error turns along uav_2's line of
        # sight only: without the latch uav_2 would be flagged
        seq = [(0, 0)] * 3 + [(-10, -10)] * 3 + [(0, 3)] * 6
        d, out = self._victim(seq)
        assert first_tick(out, "uav_0") == 5
        assert first_tick(out, "uav_2") is None
        assert d.self_latched

    def test_reset_clears_latch(self):
        d, _ = self._victim([(0, 0)] * 3 + [(-10, -10)] * 3)
        assert d.self_latched
        d.reset()
        assert not d.self_latched


# ---------------------------------------------------------------------------
# Three monitors, H3 geometry (layers: peers above the victim)
# ---------------------------------------------------------------------------


def _three_monitors(truth, v=0.7, t_end=30):
    """Every monitor sees exact ranges; uav_0's belief drifts north at v m/s
    from t = 0. Announcements on whole seconds, order uav_0, uav_1, uav_2.
    Returns [(t, monitor, event)]."""
    ids = list(truth)
    dets = {i: make(i, {j: dist(truth[i], truth[j]) for j in ids if j != i}) for i in ids}
    events = []
    for k in range(-5, t_end):
        t = float(k)
        belief = dict(truth)
        belief["uav_0"] = (truth["uav_0"][0], truth["uav_0"][1] + max(0.0, v * t),
                           truth["uav_0"][2])
        for i in ids:
            own(dets[i], belief[i], t)
        for j in ids:
            a = ann(j, belief[j], t)
            for i in ids:
                events += [(t, i, ev) for ev in dets[i].feed_peer_position(a)]
    return events


def test_h3_pattern_peers_above_the_victim():
    """H3 geometry (5 m layers; peers above the victim). Expected (H3 [2c]):
    uav_1 and uav_2 flag uav_0, uav_0 flags itself, nobody flags an honest
    UAV, and the peer path is not later than the self path."""
    events = _three_monitors({"uav_0": (0.0, 0.0, 10.0), "uav_1": (0.0, 0.0, 15.0),
                              "uav_2": (0.0, 0.0, 20.0)})
    targets = {(i, ev.target_uav) for _, i, ev in events}
    assert ("uav_1", "uav_0") in targets
    assert ("uav_2", "uav_0") in targets
    assert ("uav_0", "uav_0") in targets
    assert not any(ev.target_uav in ("uav_1", "uav_2") for _, _, ev in events)
    t_peer = min(t for t, i, ev in events if i != "uav_0")
    t_self = min(t for t, i, ev in events if i == "uav_0")
    assert t_peer <= t_self


def test_unfavourable_geometry_victim_monitor_misattributes():
    """Stated limit (H3 [2c]): with uav_2 offset 2 m north (the spoof
    direction), the pair 0-2 stays within theta_ok while the pair 0-1 turns
    bad, and the victim's own monitor flags the honest uav_1 before its self
    flag. The peers' monitors still attribute correctly."""
    events = _three_monitors({"uav_0": (0.0, 0.0, 10.0), "uav_1": (2.0, 1.0, 15.0),
                              "uav_2": (-1.0, 2.0, 20.0)})
    wrong = [(t, i, ev.target_uav) for t, i, ev in events if ev.target_uav != "uav_0"]
    assert wrong and all(i == "uav_0" for _, i, _ in wrong)
    assert {(i, ev.target_uav) for _, i, ev in events if i != "uav_0"} == {
        ("uav_1", "uav_0"), ("uav_2", "uav_0")}
