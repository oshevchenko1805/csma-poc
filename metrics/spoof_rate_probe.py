"""
metrics/spoof_rate_probe.py — executable rules of B0_PREREGISTRATION.md
(review stage 5, spoof-rate sweep). Pure functions; the flight script is
scripts/probe_spoof_rate.py.

Question: is there a spoofing speed at which neither the local GPS
detector nor the mesh cross-check notices the attack while the UAV is
dragged off course?

Attack model (GZBridge patch, tag OFFSET_INJECT, called per navsat
message at 30 Hz on x500):  off += r * (target - off).  First-order
approach: v0 = r * f * A (maximum spoof speed, at onset),
tau = -1 / (f * ln(1 - r)).

Detectors are re-evaluated OFFLINE with the campaign classes and
defaults: GpsSpoofingDetector on the logged ESTIMATOR_STATUS stream,
CrossCheckDetector on GLOBAL_POSITION_INT sampled at the monitor's
announce cadence (lossless mesh).

Frames: truth = Gazebo ENU (north = y, east = x), belief =
LOCAL_POSITION_NED (x = north, y = east). Truth is linearly interpolated
to belief timestamps (a UAV cruising at 5 m/s makes nearest-sample
pairing err by up to ~2.5 m), then the constant frame offset is removed
with the median (truth - belief) over the 5 s before injection, as in
metrics/trust_hold_probe.py.
"""

from __future__ import annotations

import bisect
import math
import statistics
from typing import Optional

from core.events import PeerPositionAnnounce, TelemetryEvent
from detectors.cross_check import CrossCheckDetector
from detectors.gps import GpsSpoofingDetector
from metrics.physical_outcomes import JUMP_M, NAV_END_TAIL_S

# --- fixed design (B0_PREREGISTRATION.md) --------------------------------

F_GPS_HZ = 30.0
"""navsat update_rate of x500_base; the patch runs once per message."""

TARGET_M = 50.0
"""SIM_GPS_OFF_N (north), as in the campaign."""

CAMPAIGN_R = 0.02
"""SIM_GPS_OFF_R default; must be restored after every flight."""

LEVELS = {"L30": 30.0, "L10": 10.0, "L3": 3.0, "L1": 1.0, "L0.5": 0.5}
"""Level name -> initial spoof speed v0 (m/s). L0.5 is the extension."""

WINDOW_S = {"L30": 180.0, "L10": 180.0, "L3": 180.0, "L1": 180.0, "L0.5": 300.0}

ANNOUNCE_PERIOD_S = 1.0
"""runners.monitor.Monitor.DEFAULT_PEER_PUBLISH_PERIOD_SEC (test-checked)."""

STEP_BUDGET_M = (CrossCheckDetector.DEFAULT_MAX_VELOCITY_MPS * ANNOUNCE_PERIOD_S
                 + CrossCheckDetector.DEFAULT_POSITION_ERROR_MARGIN_M)
"""35 m: the largest 1 s move the cross-check accepts."""

BIAS_WINDOW_S = 5.0
RAMP_TOL_M = 5.0
LANDED_MIN_M = JUMP_M          # nav_error_end below this -> NOT_LANDED
INJECTED_MIN_M = 5.0           # spoof offset at W below this -> invalid flight
CONTROL_JUMP_S = (5.0, 10.0)
CONTROL_GPS_MAX_S = 10.0

_R_EARTH = 6_371_000.0         # same radius as detectors.cross_check


def level_params(level: str) -> dict:
    v0 = LEVELS[level]
    r = v0 / (F_GPS_HZ * TARGET_M)
    tau = -1.0 / (F_GPS_HZ * math.log(1.0 - r))
    return {"level": level, "v0_mps": v0, "r": r, "tau_s": tau,
            "window_s": WINDOW_S[level]}


def model_offset(t: float, r: float) -> float:
    """Spoof offset (m) t seconds after injection under the patch model."""
    if t <= 0:
        return 0.0
    return TARGET_M * (1.0 - (1.0 - r) ** (F_GPS_HZ * t))


# --- series helpers ------------------------------------------------------

def interp(samples: list, t: float, max_gap: float = 1.0,
           ts: Optional[list] = None) -> Optional[tuple]:
    """samples [(t, a, b)] sorted -> (a, b) linearly at t; None outside or
    across a gap > max_gap. ts = precomputed [s[0] for s in samples]."""
    if ts is None:
        ts = [s[0] for s in samples]
    i = bisect.bisect_left(ts, t)
    if i < len(ts) and ts[i] == t:
        return samples[i][1], samples[i][2]
    if i == 0 or i == len(ts):
        return None
    (t0, a0, b0), (t1, a1, b1) = samples[i - 1], samples[i]
    if t1 - t0 > max_gap:
        return None
    w = (t - t0) / (t1 - t0)
    return a0 + w * (a1 - a0), b0 + w * (b1 - b0)


def _median_offset(pairs: list, t_from: float, t_to: float) -> Optional[tuple]:
    ref = [p for p in pairs if t_from <= p[0] <= t_to]
    if not ref:
        return None
    return (statistics.median(p[1] - p[3] for p in ref),
            statistics.median(p[2] - p[4] for p in ref))


def nav_error_series(truth: list, belief: list, t_inject: float) -> list:
    """[(t_rel, |belief - truth|)]; truth/belief = [(t_wall, north, east)]."""
    tts = [s[0] for s in truth]
    pairs = []
    for t, bn, be in belief:
        tr = interp(truth, t, ts=tts)
        if tr is not None:
            pairs.append((t, tr[0], tr[1], bn, be))
    off = _median_offset(pairs, t_inject - BIAS_WINDOW_S, t_inject)
    if off is None:
        return []
    dn, de = off
    return [(p[0] - t_inject, math.hypot(p[3] + dn - p[1], p[4] + de - p[2]))
            for p in pairs]


def spoof_offset_series(gps: list, truth: list, t_inject: float) -> list:
    """[(t_rel, north offset m)] of the GPS input against truth.

    gps = [(t_wall, lat_deg, lon_deg)]. North from latitude on a sphere;
    the pre-injection median (gps - truth) removes the frame offset."""
    if not gps:
        return []
    lat0 = gps[0][1]
    tts = [s[0] for s in truth]
    pairs = []
    for t, lat, _lon in gps:
        tr = interp(truth, t, ts=tts)
        if tr is not None:
            pairs.append((t, math.radians(lat - lat0) * _R_EARTH, tr[0]))
    ref = [g - n for t, g, n in pairs if t_inject - BIAS_WINDOW_S <= t <= t_inject]
    if not ref:
        return []
    b = statistics.median(ref)
    return [(t - t_inject, g - n - b) for t, g, n in pairs]


def value_at(series: list, t: float, half: float = 0.5) -> Optional[float]:
    """Median of series values within [t - half, t + half]."""
    v = [x for s, x in series if t - half <= s <= t + half and x is not None]
    return statistics.median(v) if v else None


def max_step(series: list, dt: float = 1.0, t_from: float = 0.0,
             t_to: float = math.inf) -> Optional[float]:
    """Largest increase of the series over any dt interval in [t_from, t_to]."""
    ser = [(t, v, 0.0) for t, v in series]
    sts = [s[0] for s in ser]
    best = None
    for t, v in series:
        if t < t_from + dt or t > t_to:
            continue
        prev = interp(ser, t - dt, ts=sts)
        if prev is None:
            continue
        step = v - prev[0]
        best = step if best is None else max(best, step)
    return best


# --- offline detector replay --------------------------------------------

def replay_gps(est: list, t_inject: float, uav: str = "uav_0") -> dict:
    """est = [(t_wall, pos_horiz_ratio)] -> first alarm, relative to t_inject."""
    det = GpsSpoofingDetector(target_uav=uav, source="b0_replay")
    first, pre = None, False
    for t, ratio in sorted(est):
        ev = TelemetryEvent(source="b0_replay", uav_id=uav,
                            msg_type="ESTIMATOR_STATUS", timestamp=t,
                            data={"pos_horiz_ratio": ratio})
        if det.feed(ev) is not None:
            if t < t_inject:
                pre = True
            elif first is None:
                first = t - t_inject
    return {"t_gps_s": first, "gps_alarm_before_injection": pre}


def announcements(gpi: list, period: float = ANNOUNCE_PERIOD_S) -> list:
    """gpi = [(t_wall, lat, lon)] -> what the monitor would publish: the
    latest sample at each tick t0 + k*period (duplicates dropped)."""
    gpi = sorted(gpi)
    if not gpi:
        return []
    out, last_ts = [], None
    ts = [g[0] for g in gpi]
    tick = gpi[0][0] + period
    while tick <= gpi[-1][0] + 1e-9:
        i = bisect.bisect_right(ts, tick) - 1
        if i >= 0 and gpi[i][0] != last_ts:
            out.append(gpi[i])
            last_ts = gpi[i][0]
        tick += period
    return out


def replay_cross_check(gpi: list, t_inject: float, uav: str = "uav_0") -> dict:
    """First cross_check alarm a peer monitor would raise about `uav`."""
    det = CrossCheckDetector(monitor_uav_id="peer", source="b0_replay")
    first, pre = None, False
    for t, lat, lon in announcements(gpi):
        ann = PeerPositionAnnounce(source="b0_replay", uav_id=uav, lat=lat,
                                   lon=lon, alt=0.0, sample_timestamp=t)
        if det.feed_peer_position(ann) is not None:
            if t < t_inject:
                pre = True
            elif first is None:
                first = t - t_inject
    return {"t_cc_s": first, "cc_alarm_before_injection": pre}


# --- per flight ----------------------------------------------------------

def summarize_flight(level: str, t_inject: float, truth: list, belief: list,
                     gps: list, est: list, gpi: list) -> dict:
    p = level_params(level)
    w = p["window_s"]
    nav = nav_error_series(truth, belief, t_inject)
    navw = [(t, e) for t, e in nav if 0.0 <= t <= w]
    spoof = spoof_offset_series(gps, truth, t_inject)
    g = replay_gps(est, t_inject)
    c = replay_cross_check(gpi, t_inject)
    alarms = [x for x in (g["t_gps_s"], c["t_cc_s"]) if x is not None and x <= w]
    t_alarm = min(alarms) if alarms else None
    at_tau = value_at(spoof, p["tau_s"])
    at_2tau = value_at(spoof, 2 * p["tau_s"])
    return {
        **p,
        "t_gps_s": g["t_gps_s"] if g["t_gps_s"] is not None and g["t_gps_s"] <= w else None,
        "t_cc_s": c["t_cc_s"] if c["t_cc_s"] is not None and c["t_cc_s"] <= w else None,
        "gps_alarm_before_injection": g["gps_alarm_before_injection"],
        "cc_alarm_before_injection": c["cc_alarm_before_injection"],
        "t_jump_s": next((t for t, e in navw if e > JUMP_M), None),
        "max_step_1s_m": max_step(nav, 1.0, 0.0, w),
        "nav_error_end_m": value_at(navw, w - NAV_END_TAIL_S / 2, NAV_END_TAIL_S / 2),
        "harm_at_alarm_m": (value_at(navw, t_alarm, 0.25) if t_alarm is not None
                            else max((e for _, e in navw), default=None)),
        "spoof_at_tau_m": at_tau,
        "spoof_at_2tau_m": at_2tau,
        "spoof_at_window_end_m": value_at(spoof, w - 1.0, 1.0),
        "ramp_ok": (at_tau is not None and at_2tau is not None
                    and abs(at_tau - model_offset(p["tau_s"], p["r"])) <= RAMP_TOL_M
                    and abs(at_2tau - model_offset(2 * p["tau_s"], p["r"])) <= RAMP_TOL_M),
    }


def classify_flight(s: dict, error: Optional[str] = None) -> str:
    """INVALID | NOT_LANDED | DETECTED | BLIND (B0_PREREGISTRATION.md)."""
    if error:
        return "INVALID"
    sp = s.get("spoof_at_window_end_m")
    if sp is None or sp < INJECTED_MIN_M:
        return "INVALID"
    ne = s.get("nav_error_end_m")
    if ne is None:
        return "INVALID"
    if ne < LANDED_MIN_M:
        return "NOT_LANDED"
    if s.get("t_gps_s") is not None or s.get("t_cc_s") is not None:
        return "DETECTED"
    return "BLIND"


def detected_by(s: dict) -> Optional[str]:
    g, c = s.get("t_gps_s") is not None, s.get("t_cc_s") is not None
    return {(True, True): "both", (True, False): "gps only",
            (False, True): "cc only"}.get((g, c))


def classify_level(classes: list) -> str:
    """Valid flight classes of one level -> level class, or 'FLY_AGAIN'."""
    valid = [c for c in classes if c != "INVALID"]
    if len(valid) < 2:
        return "FLY_AGAIN"
    if len(valid) == 2:
        return valid[0] if valid[0] == valid[1] else "FLY_AGAIN"
    top = max(set(valid), key=valid.count)
    return top if valid.count(top) * 2 > len(valid) else "FLY_AGAIN"


def control_ok(l30: list) -> bool:
    """Both L30 flights reproduce the campaign (jump 5-10 s, gps <= 10 s)."""
    if len(l30) < 2:
        return False
    lo, hi = CONTROL_JUMP_S
    return all(s.get("t_jump_s") is not None and lo <= s["t_jump_s"] <= hi
               and s.get("t_gps_s") is not None and s["t_gps_s"] <= CONTROL_GPS_MAX_S
               for s in l30)


def decision(level_classes: dict) -> str:
    """level -> class. Decision rule of B0_PREREGISTRATION.md."""
    if any(c == "FLY_AGAIN" for c in level_classes.values()):
        return "INCOMPLETE: a level needs another flight"
    blind = [LEVELS[l] for l, c in level_classes.items() if c == "BLIND"]
    if blind:
        return "BLIND ZONE: v_blind = %g m/s -> B1" % max(blind)
    if "L0.5" not in level_classes and level_classes.get("L1") == "DETECTED":
        return "EXTEND: fly L0.5 (W = 300 s)"
    return "NO BLIND ZONE: decide velocity-consistent spoof vs B as future work"
