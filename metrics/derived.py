"""
metrics/derived.py — post-hoc metrics of Table 3.13 that the live
pipeline does not compute.

Everything here is derived from artefacts already written by every run:
    run_summary.json   mission_plan, belief_divergence (origins)
    merged.jsonl       attack / security / isolation_announce /
                       recovery_request / recovery_ack events
    trajectory.jsonl   Gazebo ground truth, all UAVs, ~5 Hz

No re-runs are needed. Ground truth is Gazebo, never the PX4 estimate
(the estimate is poisoned by the spoof, that is the whole point).

Metrics produced
----------------
time_to_isolation_s      t(isolation_announce) - t(first security)
mttr_functional_s        t(degradation stops) - t(isolation_announce)
recovery_success         degradation stopped before end of observation
residual_mission_func    share of UAVs still on-plan at end of window
mission_degradation_m    peak off-plan distance of the target after attack
coordination_loss        1 - min over time of (share of UAVs on-plan)
coordination_restored    share of UAVs on-plan at the end
total_response_time_s    t(last recovery event) - t(attack inject_start)

"Recovery" is defined per thesis 3.5.4: not a return to the original
state, but stabilisation — the deviation from the mission plan stops
growing. This is what makes it measurable while the attack is still
active, which is the regime the methodology prescribes.

Usage
-----
    python -m metrics.derived runs_campaign/pass1
    python -m metrics.derived runs_campaign/smoke --per-run
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from dataclasses import dataclass, asdict
from typing import Optional

# --- tunables, all reported in Chapter 4 -------------------------------

ON_PLAN_TOLERANCE_M = 15.0
"""Off-plan distance above which a UAV counts as no longer flying the
mission. Nominal tracking error in SITL is well under 5 m."""

STABLE_SLOPE_MPS = 0.5
"""Growth rate of the off-plan distance below which degradation counts
as stopped. A parked (loitering) UAV sits near 0; a UAV flying on a
spoofed position drifts at metres per second."""

SLOPE_WINDOW_S = 5.0
"""Window over which the growth rate is fitted."""

BASELINE_WINDOW_S = 30.0
"""Pre-attack window used to measure this run's nominal tracking error."""


# --- geometry ----------------------------------------------------------


def point_segment_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Shortest distance from point P to segment AB. Pure function."""
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_plan(north: float, east: float, corners: list) -> float:
    """Shortest distance from a point to the closed mission polyline."""
    if not corners:
        return 0.0
    if len(corners) == 1:
        c = corners[0]
        return math.hypot(north - c[0], east - c[1])
    best = float("inf")
    n = len(corners)
    for i in range(n):
        a = corners[i]
        b = corners[(i + 1) % n]
        d = point_segment_distance(north, east, a[0], a[1], b[0], b[1])
        if d < best:
            best = d
    return best


def _slope(times: list, values: list) -> float:
    """Least-squares slope. Zero when the window is degenerate."""
    n = len(times)
    if n < 2:
        return 0.0
    mt = sum(times) / n
    mv = sum(values) / n
    num = sum((t - mt) * (v - mv) for t, v in zip(times, values))
    den = sum((t - mt) ** 2 for t in times)
    if den == 0.0:
        return 0.0
    return num / den


def first_stable_time(
    times: list,
    values: list,
    slope_limit: float = STABLE_SLOPE_MPS,
    window_s: float = SLOPE_WINDOW_S,
) -> Optional[float]:
    """
    Earliest time from which the series stops growing and never resumes
    growing before the end of the record.

    Scanning backwards makes the answer deterministic: a transient dip
    followed by renewed growth does not count as recovery.
    """
    if len(times) < 2:
        return None
    starts = []
    i = 0
    n = len(times)
    while i < n:
        j = i
        while j < n and times[j] - times[i] <= window_s:
            j += 1
        if times[j - 1] - times[i] >= window_s * 0.5:
            starts.append((i, j))
        i += 1
    if not starts:
        return None
    stable_from = None
    for i, j in reversed(starts):
        if _slope(times[i:j], values[i:j]) <= slope_limit:
            stable_from = times[i]
        else:
            break
    return stable_from


# --- run parsing -------------------------------------------------------


def load_events(run_dir: str) -> list:
    path = os.path.join(run_dir, "merged.jsonl")
    out = []
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def load_trajectory(run_dir: str) -> dict:
    """{uav_id: [(t_wall, north_m, east_m), ...]} in each UAV's own frame."""
    path = os.path.join(run_dir, "trajectory.jsonl")
    raw = {}
    if not os.path.exists(path):
        return raw
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
            except ValueError:
                continue
            uav = s.get("uav_id")
            if uav is None:
                continue
            raw.setdefault(uav, []).append(
                (float(s["t_wall"]), float(s["x"]), float(s["y"]))
            )
    out = {}
    for uav, samples in raw.items():
        samples.sort(key=lambda r: r[0])
        ox, oy = samples[0][1], samples[0][2]
        # axis map (belief_divergence): north = gz.y - oy, east = gz.x - ox
        out[uav] = [(t, y - oy, x - ox) for (t, x, y) in samples]
    return out


def plan_corners(summary: dict) -> list:
    plan = summary.get("mission_plan") or {}
    wps = plan.get("lap_waypoints") or plan.get("waypoints") or []
    return [(float(w["north_m"]), float(w["east_m"])) for w in wps]


def _first_ts(events: list, event_type: str) -> Optional[float]:
    for e in events:
        if e.get("event_type") == event_type:
            return float(e["timestamp"])
    return None


def attributable_ts(events: list, t_attack: Optional[float],
                    target: Optional[str], types: tuple,
                    last: bool = False) -> Optional[float]:
    """Час події, яку МОЖНА приписати цій атаці.

    Єдиний гейт атрибуції для ВСІХ подієвих часів. Дві умови:

    1. `timestamp >= t_attack` — подія до інʼєкції не є наслідком цієї
       інʼєкції;
    2. `target_uav == target` — подія про інший борт теж не є.

    Раніше гейт мав тільки `detected`, а `t_detect`, `t_isolate` і
    `t_last_rec` бралися по всьому прогону через `_first_ts`/`_last_ts`.
    Наслідки, виміряні на корпусі (11 атакуючих прогонів мали
    передатакові хибні спрацювання):

    * `time_to_isolation_s` — максимум по корпусу 59 119 мкс проти
      548 мкс без цих прогонів. Саме звідси в тексті взялося «40-59
      мкс»: 59 мілісекунд прочитані як 59 мікросекунд;
    * `mttr_functional_s` — якір `t_isolate` міг стояти ДО атаки, тому
      відлік ішов не звідти; у 10 прогонах вийшло 70-127 с проти
      медіан 51-54 с. Медіани встояли (зсув до 0.13 с), окремі значення
      і IQR — ні;
    * `total_response_time_s` — два відʼємні значення.
    """
    if t_attack is None:
        return None
    hits = []
    for e in events:
        if e.get("event_type") not in types:
            continue
        ts = float(e["timestamp"])
        if ts < t_attack:
            continue
        if target is not None and e.get("target_uav") != target:
            continue
        hits.append(ts)
    if not hits:
        return None
    return max(hits) if last else min(hits)


def first_attack_detection_ts(events: list, t_attack: Optional[float],
                              target: Optional[str]) -> Optional[float]:
    """Перша security-подія, яку МОЖНА приписати атаці.

    Два умови, обидві обовʼязкові:

    1. `timestamp >= t_attack` — подія до інʼєкції не може бути
       виявленням цієї інʼєкції. Це хибне спрацювання, і воно вже
       рахується окремо в R13;
    2. `target_uav == target` — подія про інший борт не є виявленням
       атаки на цей борт.

    Раніше `detected` рахувався як «існує будь-яка security-подія»
    (без обох умов). Через це вісім прогонів A і B під takeout-сценаріями
    рахувались виявленими за рахунок передатакових heartbeat- і
    gps-спрацювань: у всіх них MTTD порожній, бо MTTD гейт мав, а
    `detected` — ні. Те саме правило вже реалізоване в
    `metrics/analyzer.py` і в `campaign_report.mttd`; тут воно приведене
    до них, щоб визначення було одне на весь код.

    Тонка обгортка над `attributable_ts`, лишена окремо, бо на неї
    посилається `analyse_run` і тести регресії.
    """
    return attributable_ts(events, t_attack, target, ("security",))


def _last_ts(events: list, types: tuple) -> Optional[float]:
    """БЕЗ гейта атрибуції. Лишається тільки для діагностики; у метрики
    не подавати — використовуй `attributable_ts(..., last=True)`."""
    ts = [float(e["timestamp"]) for e in events if e.get("event_type") in types]
    return max(ts) if ts else None


def _attack_ts(events: list) -> Optional[float]:
    for e in events:
        if e.get("event_type") == "attack" and e.get("phase") == "inject_start":
            return float(e["timestamp"])
    return _first_ts(events, "attack")


@dataclass
class DerivedMetrics:
    run_id: str
    architecture: str
    attack: str
    target_uav: str
    time_to_isolation_s: Optional[float]
    mttr_functional_s: Optional[float]
    degradation_stopped: Optional[bool]
    stabilisation_level_m: Optional[float]
    residual_mission_func: Optional[float]
    mission_degradation_m: Optional[float]
    coordination_loss: Optional[float]
    coordination_restored: Optional[float]
    total_response_time_s: Optional[float]
    baseline_track_error_m: Optional[float]
    detected: Optional[bool]
    """Whether a SecurityEvent fired for the target on this (attack) run.
    Detection rate = mean over valid attack runs; FN rate = 1 - that."""
    containment_success: Optional[bool]
    """Whether the incident stayed confined to the target — no non-target
    UAV left the mission plan after the attack (thesis 3.13: contained
    without uncontrolled spread)."""


def analyse_run(run_dir: str) -> Optional[DerivedMetrics]:
    spath = os.path.join(run_dir, "run_summary.json")
    if not os.path.exists(spath):
        return None
    with open(spath) as fh:
        summary = json.load(fh)

    events = load_events(run_dir)
    traj = load_trajectory(run_dir)
    corners = plan_corners(summary)
    target = summary.get("target_uav") or ""

    t_attack = _attack_ts(events)
    # Усі три — через єдиний гейт атрибуції. Раніше бралися по всьому
    # прогону, через що передатакове хибне спрацювання ставало «першою
    # ізоляцією» і зсувало якір MTTR у минуле, а `time_to_isolation_s`
    # отримував викид 59 мс серед типових 50 мкс. Див. `attributable_ts`.
    t_detect = attributable_ts(events, t_attack, target, ("security",))
    t_isolate = attributable_ts(events, t_attack, target,
                                ("isolation_announce",))
    t_last_rec = attributable_ts(events, t_attack, target,
                                 ("recovery_ack", "recovery_request"),
                                 last=True)

    tti = None
    if t_detect is not None and t_isolate is not None:
        tti = t_isolate - t_detect
    trt = None
    if t_attack is not None and t_last_rec is not None:
        trt = t_last_rec - t_attack

    # off-plan distance series per UAV
    dev = {}
    for uav, samples in traj.items():
        dev[uav] = [(t, distance_to_plan(n, e, corners)) for (t, n, e) in samples]

    baseline = None
    mttr = None
    rec_ok = None
    stab_level = None
    degradation = None
    is_attack_run = str(summary.get("attack_name") or "").lower() not in ("", "none")
    if target in dev and t_attack is not None and is_attack_run:
        series = dev[target]
        pre = [
            d
            for (t, d) in series
            if t_attack - BASELINE_WINDOW_S <= t < t_attack
        ]
        if pre:
            baseline = statistics.median(pre)
        post = [(t, d) for (t, d) in series if t >= t_attack]
        if post:
            degradation = max(d for (_, d) in post) - (baseline or 0.0)
        anchor = t_isolate if t_isolate is not None else t_attack
        seg = [(t, d) for (t, d) in series if t >= anchor]
        if len(seg) >= 2:
            t_stable = first_stable_time([t for t, _ in seg], [d for _, d in seg])
            if t_stable is not None:
                mttr = t_stable - anchor
                rec_ok = True
                tail = [d for (t, d) in seg if t >= t_stable]
                if tail:
                    stab_level = statistics.median(tail) - (baseline or 0.0)
            else:
                rec_ok = False

    # swarm-level: share of UAVs on plan, over time and at the end
    residual = None
    coord_loss = None
    coord_restored = None
    if dev and t_attack is not None:
        uavs = sorted(dev)
        grid = sorted({round(t, 1) for uav in uavs for (t, _) in dev[uav] if t >= t_attack})
        if grid:
            import bisect

            idx = {u: [t for (t, _) in dev[u]] for u in uavs}
            shares = []
            for gt in grid:
                on = 0
                seen = 0
                for uav in uavs:
                    ts = idx[uav]
                    k = bisect.bisect_left(ts, gt)
                    best = None
                    for cand in (k - 1, k, k + 1):
                        if 0 <= cand < len(ts):
                            gap = abs(ts[cand] - gt)
                            if best is None or gap < best[0]:
                                best = (gap, dev[uav][cand][1])
                    if best is not None and best[0] <= 1.0:
                        seen += 1
                        if best[1] <= ON_PLAN_TOLERANCE_M:
                            on += 1
                if seen:
                    shares.append(on / seen)
            if shares:
                coord_loss = 1.0 - min(shares)
                coord_restored = shares[-1]
                residual = shares[-1]

    # detection (for FN rate) and containment — attack runs only
    detected = None
    containment_success = None
    if is_attack_run and t_attack is not None:
        detected = first_attack_detection_ts(events, t_attack, target) is not None
        # СТРИМУВАННЯ (containment), а не «ізоляція спрацювала»: тут
        # перевіряється лише те, що жоден НЕЦІЛЬОВИЙ борт не зійшов з
        # маршруту після атаки, тобто наслідки не поширились за межі
        # цілі. Механізм ізоляції як такий цим не вимірюється — він
        # внутрішньопроцесний і однаковий у всіх трьох конфігураціях.
        # Поле називалось `isolation_success` і читалось як «ізоляція
        # вдалася», чого воно не означає. Розділ 3 визначає цю метрику
        # саме як стримування («частка запусків, у яких інцидент було
        # стримано без неконтрольованого поширення»), тому перейменування
        # приводить КОД до тексту, а не навпаки.
        spread = False
        for uav, series in dev.items():
            if uav == target:
                continue
            post = [d for (t, d) in series if t >= t_attack]
            if post and max(post) > ON_PLAN_TOLERANCE_M:
                spread = True
                break
        # Only meaningful when we actually observed the other UAVs.
        others = [u for u in dev if u != target]
        if others:
            containment_success = not spread

    return DerivedMetrics(
        run_id=summary.get("run_id") or os.path.basename(run_dir),
        architecture=str(summary.get("architecture") or "?"),
        attack=str(summary.get("attack_name") or "?"),
        target_uav=target,
        time_to_isolation_s=tti,
        mttr_functional_s=mttr,
        degradation_stopped=rec_ok,
        stabilisation_level_m=stab_level,
        residual_mission_func=residual,
        mission_degradation_m=degradation,
        coordination_loss=coord_loss,
        coordination_restored=coord_restored,
        total_response_time_s=trt,
        baseline_track_error_m=baseline,
        detected=detected,
        containment_success=containment_success,
    )


# --- aggregation -------------------------------------------------------


def _fmt(values: list) -> str:
    vals = [v for v in values if isinstance(v, (int, float))]
    if not vals:
        return "—"
    if len(vals) == 1:
        return "%.2f (1)" % vals[0]
    return "%.2f±%.2f (%d)" % (
        statistics.mean(vals),
        statistics.pstdev(vals),
        len(vals),
    )


def _fmt_rate(values: list) -> str:
    vals = [v for v in values if isinstance(v, bool)]
    if not vals:
        return "—"
    k = sum(1 for v in vals if v)
    return "%d/%d (%d%%)" % (k, len(vals), round(100 * k / len(vals)))


def _fmt_fn_rate(values: list) -> str:
    """False-negative rate = share of valid attack runs NOT detected."""
    vals = [v for v in values if isinstance(v, bool)]
    if not vals:
        return "—"
    fn = sum(1 for v in vals if not v)
    return "%d/%d (%d%%)" % (fn, len(vals), round(100 * fn / len(vals)))


FIELDS = [
    ("detected", "Detection rate (valid attacks)", _fmt_rate),
    ("detected", "False-negative rate", _fmt_fn_rate),
    ("containment_success", "Containment success rate", _fmt_rate),
    ("time_to_isolation_s", "Time to isolation, s", _fmt),
    ("mttr_functional_s", "MTTR functional, s", _fmt),
    ("degradation_stopped", "Recovery success rate", _fmt_rate),
    ("stabilisation_level_m", "Stabilisation level, m", _fmt),
    ("mission_degradation_m", "Mission degradation, m", _fmt),
    ("residual_mission_func", "Residual mission function", _fmt),
    ("coordination_loss", "Coordination loss", _fmt),
    ("coordination_restored", "Coordination restored", _fmt),
    ("total_response_time_s", "Total response time, s", _fmt),
    ("baseline_track_error_m", "Baseline track error, m", _fmt),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", help="batch root, e.g. runs_campaign/pass1")
    ap.add_argument("--per-run", action="store_true", help="dump every run")
    ap.add_argument("--csv", default=None, help="write per-run rows to CSV")
    args = ap.parse_args()

    rows = []
    for name in sorted(os.listdir(args.root)):
        d = os.path.join(args.root, name)
        if not os.path.isdir(d) or not name.startswith("run_"):
            continue
        m = analyse_run(d)
        if m is not None:
            rows.append(m)

    if not rows:
        print("no runs found under", args.root)
        return

    if args.per_run:
        for m in rows:
            print(json.dumps(asdict(m)))

    archs = sorted({m.architecture for m in rows})
    attacks = sorted({m.attack for m in rows})
    for field, title, fmt in FIELDS:
        print()
        print(title)
        header = "%-22s" % "Attack" + "".join("%-18s" % a for a in archs)
        print(header)
        print("-" * len(header))
        for atk in attacks:
            cells = []
            for a in archs:
                vals = [
                    getattr(m, field)
                    for m in rows
                    if m.architecture == a and m.attack == atk
                ]
                cells.append("%-18s" % fmt(vals))
            print("%-22s" % atk[:22] + "".join(cells))

    if args.csv:
        import csv

        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(asdict(rows[0]).keys()))
            w.writeheader()
            for m in rows:
                w.writerow(asdict(m))
        print()
        print("wrote", args.csv)

    print()
    print("analysed %d runs" % len(rows))


if __name__ == "__main__":
    main()
