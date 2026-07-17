"""
estimator_series — the raw EKF residual series behind a detection.

Why this exists
---------------
OPEN-3: across runs_v3, 19 of 20 runs fired 3 detectors at ~2.97 s, one
fired 1 at 5.84 s, and one manual run fired none at all. 3 -> 1 -> 0 is a
gradient, not a glitch, so the undetected run is the far end of a real
distribution and the cause is unknown.

It is unknown because it is *unknowable* from what the pipeline records.
Monitors log events, not telemetry: `GpsSpoofingDetector` sees
`pos_horiz_ratio` in every ESTIMATOR_STATUS and emits nothing unless it
fires. The undetected run therefore contains zero security events —
there is literally nothing to inspect. This module records what the
detector saw, so the question becomes answerable by reading the run
instead of by re-running it.

What it answers
---------------
The detector fires on `ratio > threshold` sustained over N consecutive
samples. So a non-detection has exactly two possible causes, and they are
distinguishable:

  - the ratio never crossed the threshold at all
        -> `n_above_threshold == 0`: the injection did not produce the
           signature. The detection rate is then a property of the
           *attack mechanism*, not of the architecture — which belongs in
           threats-to-validity, not in the results table.
  - the ratio crossed but never for N samples in a row
        -> `max_consecutive_above < N`: the signature existed and the
           sustain rule rejected it. That is a detector-tuning finding.

`max_consecutive_above` is the field that separates them. Both readings
are honest and publishable; guessing between them is not.

Scope — diagnostic, NOT a metric source
---------------------------------------
This series is produced by the monitor, which is inside the system under
test. A 4th mavlink-router endpoint would have let an outside tap read
the same stream, but that breaks MAVSDK PARAM_SET routing (step 10e,
blocker 2), so there is no outside channel.

Consequence: under `monitor_takeout` the series dies with the monitor, so
its availability is architecture-dependent. Nothing in table 3.13 may be
computed from it — that would violate the identical-measurement-procedure
requirement (thesis 3.5.5, 3.5.4). It is for explaining mechanisms in
Ch.4/5 and for OPEN-3. Ground truth for metrics stays with Gazebo (see
metrics/flight_check.py).

Under `detector_takeout` the opposite holds and is useful: the listener
survives, the detectors are silenced, so the series shows what the
detector *would* have seen. That is direct evidence of R5's mechanism
rather than only its consequence.

Thresholds
----------
`threshold` is a parameter and is written into the output beside the
counts it produced. It is not imported from `detectors.gps`: this module
describes what the data did, and must stay readable if the detector is
retuned later. A stored series with a stored threshold can be re-scored
against any other threshold without re-flying anything.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Optional, Sequence

# ---------------------------------------------------------------------------
# Defaults — overridable; effective values are recorded in the output.
# ---------------------------------------------------------------------------

DEFAULT_MSG_TYPE: str = "ESTIMATOR_STATUS"

DEFAULT_PRIMARY_FIELD: str = "pos_horiz_ratio"
"""PX4 EKF2's horizontal-position innovation test ratio. >1.0 means the
GPS measurement failed the filter's own chi-squared test."""

DEFAULT_FIELDS: tuple[str, ...] = ("pos_horiz_ratio", "vel_ratio")
"""`vel_ratio` is carried because it separates spoofing from raw GPS
noise: spoofing lifts pos_horiz_ratio while vel_ratio stays low, whereas
noise spikes both together (see detectors/gps.py)."""

DEFAULT_THRESHOLD: float = 1.0
"""Mirrors GpsSpoofingDetector.DEFAULT_THRESHOLD at the time of writing.
Duplicated rather than imported — see module docstring."""

T_ROUND: int = 3
V_ROUND: int = 4
"""ESTIMATOR_STATUS runs at ~1 Hz, so a 160 s trial is ~160 samples per
UAV. Rounding keeps the whole series a few kB — small enough to live in
`run_summary.json`, which is the only artefact that gets committed."""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_telemetry(
    path: Path | str, *, msg_type: Optional[str] = None
) -> list[dict[str, Any]]:
    """Load a `telemetry_<uav>.jsonl` file into flat samples.

    Deliberately NOT `core.logger.read_jsonl`: that raises on a malformed
    line so corrupt event logs surface immediately, which is right for
    metrics. This file is diagnostic and is written by a thread that gets
    killed at teardown, so a truncated final line is normal. Losing a
    trailing sample must not raise.
    """
    out: list[dict[str, Any]] = []
    p = Path(path)
    try:
        with p.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get("event_type") != "telemetry":
                    continue
                mt = rec.get("msg_type")
                if msg_type is not None and mt != msg_type:
                    continue
                data = rec.get("data")
                if not isinstance(data, dict):
                    continue
                try:
                    out.append(
                        {
                            "t_wall": float(rec["timestamp"]),
                            "uav_id": str(rec["uav_id"]),
                            "msg_type": str(mt),
                            "data": data,
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return out
    return out


# ---------------------------------------------------------------------------
# Series extraction
# ---------------------------------------------------------------------------


def _as_float(v: Any) -> Optional[float]:
    """None for anything not a real number.

    `bool` is rejected explicitly: it is an int subclass in Python, so a
    stray `True` would silently become a ratio of 1.0 — exactly at the
    detector threshold.
    """
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _threshold_stats(
    values: list[Optional[float]],
    t_rel: list[float],
    threshold: float,
) -> dict[str, Any]:
    """Reproduce the detector's sustain rule over the recorded series.

    Strict `>`, matching GpsSpoofingDetector: a sample exactly at the
    threshold is not anomalous. A gap (`None`) breaks a run of
    consecutive breaches rather than continuing it — the detector would
    never have seen that sample, so it cannot have counted toward
    sustain.
    """
    n_above = 0
    run = 0
    max_run = 0
    first_cross: Optional[float] = None
    for v, t in zip(values, t_rel):
        if v is not None and v > threshold:
            n_above += 1
            run += 1
            if run > max_run:
                max_run = run
            if first_cross is None:
                first_cross = t
        else:
            run = 0
    return {
        "n_above_threshold": n_above,
        "max_consecutive_above": max_run,
        "first_cross_t_rel_sec": first_cross,
    }


def _uav_series(
    samples: list[dict[str, Any]],
    *,
    attack_at_wall: float,
    fields: Sequence[str],
    primary_field: str,
    threshold: float,
) -> dict[str, Any]:
    samples = sorted(samples, key=lambda s: s["t_wall"])
    t_rel = [
        round(s["t_wall"] - attack_at_wall, T_ROUND) for s in samples
    ]

    series: dict[str, list[Optional[float]]] = {}
    for f in fields:
        col: list[Optional[float]] = []
        for s in samples:
            v = _as_float(s["data"].get(f))
            col.append(None if v is None else round(v, V_ROUND))
        series[f] = col

    entry: dict[str, Any] = {
        "n": len(samples),
        "rate_hz": None,
        "t_rel_sec": t_rel,
        "baseline_median": None,
        "baseline_n": 0,
        "peak": None,
        "peak_t_rel_sec": None,
        "n_above_threshold": None,
        "max_consecutive_above": None,
        "first_cross_t_rel_sec": None,
    }
    entry.update(series)

    if len(samples) >= 2:
        span = samples[-1]["t_wall"] - samples[0]["t_wall"]
        if span > 0:
            entry["rate_hz"] = round((len(samples) - 1) / span, V_ROUND)

    primary = series.get(primary_field)
    if primary is None:
        # The primary field was not requested; the raw columns are still
        # there, but no verdict can be derived. None, not zero.
        return entry

    # Baseline: pre-injection samples only. Median, not mean — a single
    # transient spike before t=0 must not move it.
    pre = [
        v
        for v, t in zip(primary, t_rel)
        if v is not None and t < 0.0
    ]
    entry["baseline_n"] = len(pre)
    if pre:
        entry["baseline_median"] = round(statistics.median(pre), V_ROUND)

    observed = [(v, t) for v, t in zip(primary, t_rel) if v is not None]
    if observed:
        peak_v, peak_t = max(observed, key=lambda vt: vt[0])
        entry["peak"] = peak_v
        entry["peak_t_rel_sec"] = peak_t

    entry.update(_threshold_stats(primary, t_rel, threshold))
    return entry


def estimator_series(
    samples: list[dict[str, Any]],
    attack_at_wall: Optional[float],
    *,
    target_uav: Optional[str] = None,
    msg_type: str = DEFAULT_MSG_TYPE,
    fields: Sequence[str] = DEFAULT_FIELDS,
    primary_field: str = DEFAULT_PRIMARY_FIELD,
    threshold: float = DEFAULT_THRESHOLD,
) -> Optional[dict[str, Any]]:
    """Per-UAV EKF residual series, anchored to the injection instant.

    Returns None when `attack_at_wall` is None: without an anchor the
    series has no `t_rel`, and an unanchored series cannot answer any
    question about the attack. That happens only when a run died before
    injection.

    The returned dict goes verbatim into `run_summary.json`, so it
    carries its own threshold and field names: `*.jsonl` is gitignored,
    which is precisely why OPEN-3 is unanswerable for runs already on
    disk. A committed run has to carry its own evidence.
    """
    if attack_at_wall is None:
        return None

    fields = tuple(fields)
    by_uav: dict[str, list[dict[str, Any]]] = {}
    n_total = 0
    for s in samples:
        if s.get("msg_type") != msg_type:
            continue
        n_total += 1
        by_uav.setdefault(s["uav_id"], []).append(s)

    uavs = {
        uav_id: _uav_series(
            by_uav[uav_id],
            attack_at_wall=attack_at_wall,
            fields=fields,
            primary_field=primary_field,
            threshold=threshold,
        )
        for uav_id in sorted(by_uav)
    }

    return {
        "msg_type": msg_type,
        "fields": list(fields),
        "primary_field": primary_field,
        "threshold": threshold,
        "attack_at_wall": attack_at_wall,
        "n_samples_total": n_total,
        "target_uav": target_uav,
        "uavs": uavs,
    }

