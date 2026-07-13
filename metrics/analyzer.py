"""
metrics.analyzer — extract MTTD/MTTR/impact metrics from run logs.

Reads experiment run directories (containing merged.jsonl + run_summary.json)
and computes per-run + aggregated metrics for the dissertation's Chapter 5.

Metric definitions
------------------
- **MTTD** (Mean Time To Detect)
  = first SecurityEvent.timestamp − AttackEvent(phase=inject_start).timestamp
  for the SAME target_uav. None if attack was never detected.

- **MTTR** (Mean Time To Recover)
  = first RecoveryAck(success=True).timestamp − IsolationAnnounce.timestamp
  for the same target_uav. None if no successful recovery.

  Note: MTTR is decomposable in Chapter 5 into (detection +
  decision + action + stabilization) phases. The raw MTTR computed
  here is the wall-clock recovery latency from isolation onwards.

- **Recovery status** (per run) ∈ {success, failed, not_applicable}
  Distinguishes three genuinely different outcomes that must NOT be
  collapsed in the Chapter 5 comparison:
    * not_applicable — the run's architecture/policy never requested a
      recovery for the target (e.g. arch A/B local-isolation-only, or
      baseline). MTTR=None here is EXPECTED, not a failure.
    * failed — a recovery WAS requested (recovery_request present) but
      no successful RecoveryAck arrived. This is a real negative result.
    * success — a successful RecoveryAck arrived for the target.
  Collapsing failed and not_applicable into a single "no MTTR" hides the
  architectural contrast (arch C recovers; A/B by design do not), so the
  aggregate reports recovery_success_rate over APPLICABLE runs only.

- **Impact scope**
  = number of distinct UAVs that emitted at least one SecurityEvent
  during the run. For attack runs the legitimate count is 1 (the
  target); higher values indicate collateral impact (cross_check
  firing on healthy peers, for example).

- **Detection rate** (over many runs)
  = fraction of attack runs in which the attack was detected.
  Inverse of false-negative rate.

- **False-positive rate** (computed on baseline runs only)
  = (number of baseline runs with any SecurityEvent) / (total baseline runs)

- **False-negative rate** (computed on attack runs only)
  = 1 − detection_rate

Robustness
----------
The analyzer never raises on missing fields or malformed events.
Missing data shows up as None in the result so the caller can see
exactly which run produced which gap. The dissertation table can
then either drop those runs or report the dropout rate as a quality
indicator.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from core.events import (
    AttackEvent,
    BaseEvent,
    IsolationAnnounce,
    RecoveryAck,
    SecurityEvent,
)
from core.logger import read_jsonl


# ---------------------------------------------------------------------------
# Recovery-status constants
# ---------------------------------------------------------------------------

RECOVERY_SUCCESS = "success"
RECOVERY_FAILED = "failed"
RECOVERY_NOT_APPLICABLE = "not_applicable"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RunMetrics:
    """Metrics from one experiment run."""

    run_id: str
    architecture: str
    attack_type: str  # 'none' for baseline
    target_uav: Optional[str]

    mttd_sec: Optional[float] = None
    mttr_sec: Optional[float] = None

    detected: bool = False
    """At least one SecurityEvent targeting attack's target_uav."""

    recovery_success: bool = False
    """Kept for backward compatibility. True iff recovery_status == success."""

    recovery_status: str = RECOVERY_NOT_APPLICABLE
    """One of {success, failed, not_applicable}. See module docstring.

    - not_applicable: no recovery_request was ever issued for the target
      (baseline, or arch A/B local-isolation-only). MTTR=None is expected.
    - failed: a recovery_request WAS issued but no successful ack arrived.
    - success: a successful RecoveryAck arrived for the target.
    """

    impact_scope: int = 0
    """Number of distinct UAVs with at least one SecurityEvent."""

    affected_uavs: list[str] = field(default_factory=list)

    n_security_events: int = 0
    n_isolations: int = 0
    n_recovery_requests: int = 0
    n_recovery_acks: int = 0

    has_false_positive: bool = False
    """True if SecurityEvent fired for a UAV other than the attack target,
    OR (for baseline runs) for any UAV at all."""

    error: Optional[str] = None
    """If reading the run failed, error message goes here."""


@dataclass
class AggregateMetrics:
    """Aggregation over multiple runs of one (architecture, attack) cell."""

    architecture: str
    attack_type: str
    n_runs: int

    mttd_mean_sec: Optional[float] = None
    mttd_p50_sec: Optional[float] = None
    mttd_p95_sec: Optional[float] = None

    mttr_mean_sec: Optional[float] = None
    mttr_p50_sec: Optional[float] = None
    mttr_p95_sec: Optional[float] = None

    detection_rate: float = 0.0
    """Fraction of runs where attack was detected. NaN-safe: 0 if no runs."""

    recovery_rate: float = 0.0
    """LEGACY: fraction of ALL runs in this cell with a successful recovery.
    Kept for backward compatibility. Prefer recovery_success_rate, which is
    computed over APPLICABLE runs only and does not penalise architectures
    that (by design) never attempt recovery."""

    recovery_success_rate: Optional[float] = None
    """Fraction of APPLICABLE runs (recovery_status in {success, failed})
    that succeeded. None when no run in this cell attempted recovery — that
    is the honest signal for arch A/B / baseline cells."""

    n_recovery_applicable: int = 0
    """Runs where a recovery was requested (status success or failed)."""

    n_recovery_success: int = 0
    n_recovery_failed: int = 0

    avg_impact_scope: float = 0.0

    false_positive_rate: Optional[float] = None
    """For baseline only. None if not a baseline cell."""

    false_negative_rate: Optional[float] = None
    """For attack only. None if not an attack cell."""

    # Sample sizes used in MTTD/MTTR — useful for confidence intervals.
    n_with_mttd: int = 0
    n_with_mttr: int = 0


# ---------------------------------------------------------------------------
# Per-run analysis
# ---------------------------------------------------------------------------


def analyze_run(run_dir: Path) -> RunMetrics:
    """Read one run directory and compute its metrics.

    Expected layout:
      <run_dir>/merged.jsonl       — combined event log
      <run_dir>/run_summary.json   — architecture, attack_name, target_uav
    """
    summary_path = run_dir / "run_summary.json"
    merged_path = run_dir / "merged.jsonl"

    run_id = run_dir.name
    architecture = "?"
    attack_type = "?"
    target_uav: Optional[str] = None

    if summary_path.exists():
        try:
            with summary_path.open() as f:
                summary = json.load(f)
            architecture = summary.get("architecture", "?")
            attack_type = summary.get("attack_name", "?")
            target_uav = summary.get("target_uav")
            run_id = summary.get("run_id", run_id)
        except Exception as exc:
            return RunMetrics(
                run_id=run_id,
                architecture=architecture,
                attack_type=attack_type,
                target_uav=target_uav,
                error=f"summary: {exc}",
            )

    if not merged_path.exists():
        return RunMetrics(
            run_id=run_id,
            architecture=architecture,
            attack_type=attack_type,
            target_uav=target_uav,
            error="merged.jsonl missing",
        )

    try:
        events = read_jsonl(merged_path)
    except Exception as exc:
        return RunMetrics(
            run_id=run_id,
            architecture=architecture,
            attack_type=attack_type,
            target_uav=target_uav,
            error=f"merged: {exc}",
        )

    return compute_run_metrics(
        events=events,
        run_id=run_id,
        architecture=architecture,
        attack_type=attack_type,
        target_uav=target_uav,
    )


def compute_run_metrics(
    *,
    events: list[BaseEvent],
    run_id: str,
    architecture: str,
    attack_type: str,
    target_uav: Optional[str],
) -> RunMetrics:
    """Pure function: events -> metrics. Reusable outside file IO."""

    security_events = [e for e in events if isinstance(e, SecurityEvent)]
    isolations = [e for e in events if isinstance(e, IsolationAnnounce)]
    recoveries = [e for e in events if isinstance(e, RecoveryAck)]
    recovery_requests = [
        e for e in events if getattr(e, "event_type", None) == "recovery_request"
    ]
    attacks_inject_start = [
        e
        for e in events
        if isinstance(e, AttackEvent) and e.phase == "inject_start"
    ]

    affected = sorted({s.target_uav for s in security_events if s.target_uav})

    metrics = RunMetrics(
        run_id=run_id,
        architecture=architecture,
        attack_type=attack_type,
        target_uav=target_uav,
        impact_scope=len(affected),
        affected_uavs=affected,
        n_security_events=len(security_events),
        n_isolations=len(isolations),
        n_recovery_requests=len(recovery_requests),
        n_recovery_acks=len(recoveries),
    )

    # MTTD: time from inject_start to first matching SecurityEvent.
    if target_uav and attacks_inject_start:
        attack_t = attacks_inject_start[0].timestamp
        matching = [
            s
            for s in security_events
            if s.target_uav == target_uav and s.timestamp >= attack_t
        ]
        if matching:
            metrics.detected = True
            first_match = min(matching, key=lambda s: s.timestamp)
            metrics.mttd_sec = max(0.0, first_match.timestamp - attack_t)

    # MTTR: from first matching IsolationAnnounce to first successful
    # RecoveryAck (same target).
    if target_uav:
        matching_iso = [
            i for i in isolations if i.target_uav == target_uav
        ]
        if matching_iso:
            iso_t = min(matching_iso, key=lambda i: i.timestamp).timestamp
            matching_ack = [
                r
                for r in recoveries
                if r.target_uav == target_uav
                and r.success
                and r.timestamp >= iso_t
            ]
            if matching_ack:
                first_ack = min(matching_ack, key=lambda r: r.timestamp)
                metrics.mttr_sec = max(0.0, first_ack.timestamp - iso_t)

    # Recovery status (three-state) — independent of the isolation anchor
    # used for MTTR. A successful ack means success regardless of whether an
    # isolation was announced; a request without a successful ack is a real
    # failure; no request at all is "not applicable" (by-design for arch A/B
    # local isolation, and for baseline).
    if target_uav:
        req_for_target = [
            e
            for e in recovery_requests
            if getattr(e, "target_uav", None) == target_uav
        ]
        success_ack = any(
            r.target_uav == target_uav and r.success for r in recoveries
        )
        if success_ack:
            metrics.recovery_status = RECOVERY_SUCCESS
            metrics.recovery_success = True
        elif req_for_target:
            metrics.recovery_status = RECOVERY_FAILED
        else:
            metrics.recovery_status = RECOVERY_NOT_APPLICABLE
    else:
        metrics.recovery_status = RECOVERY_NOT_APPLICABLE

    # False positive detection.
    if attack_type == "none":
        # Baseline run — ANY security event is a false positive.
        metrics.has_false_positive = len(security_events) > 0
    elif target_uav:
        # Attack run — security events on UAVs OTHER than target are FPs.
        metrics.has_false_positive = any(
            s.target_uav and s.target_uav != target_uav
            for s in security_events
        )

    return metrics


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate(
    runs: list[RunMetrics],
) -> dict[tuple[str, str], AggregateMetrics]:
    """Group runs by (architecture, attack_type) and produce stats."""
    groups: dict[tuple[str, str], list[RunMetrics]] = defaultdict(list)
    for r in runs:
        if r.error is not None:
            continue
        groups[(r.architecture, r.attack_type)].append(r)

    out: dict[tuple[str, str], AggregateMetrics] = {}
    for (arch, atk), group in groups.items():
        out[(arch, atk)] = _aggregate_group(arch, atk, group)
    return out


def _percentile(xs: list[float], pct: float) -> Optional[float]:
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    xs_sorted = sorted(xs)
    # Linear interpolation
    k = (len(xs_sorted) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(xs_sorted) - 1)
    if f == c:
        return xs_sorted[f]
    return xs_sorted[f] + (xs_sorted[c] - xs_sorted[f]) * (k - f)


def _aggregate_group(
    architecture: str, attack_type: str, runs: list[RunMetrics]
) -> AggregateMetrics:
    n = len(runs)
    mttds = [r.mttd_sec for r in runs if r.mttd_sec is not None]
    mttrs = [r.mttr_sec for r in runs if r.mttr_sec is not None]

    agg = AggregateMetrics(
        architecture=architecture,
        attack_type=attack_type,
        n_runs=n,
        n_with_mttd=len(mttds),
        n_with_mttr=len(mttrs),
    )

    if mttds:
        agg.mttd_mean_sec = statistics.mean(mttds)
        agg.mttd_p50_sec = _percentile(mttds, 50)
        agg.mttd_p95_sec = _percentile(mttds, 95)
    if mttrs:
        agg.mttr_mean_sec = statistics.mean(mttrs)
        agg.mttr_p50_sec = _percentile(mttrs, 50)
        agg.mttr_p95_sec = _percentile(mttrs, 95)

    if n > 0:
        agg.detection_rate = sum(1 for r in runs if r.detected) / n
        agg.recovery_rate = sum(1 for r in runs if r.recovery_success) / n
        agg.avg_impact_scope = sum(r.impact_scope for r in runs) / n

    # Three-state recovery aggregation. recovery_success_rate is over
    # APPLICABLE runs only (status in {success, failed}); it stays None for
    # cells where nothing ever attempted recovery (arch A/B, baseline) so the
    # table shows "—" rather than a misleading 0%.
    agg.n_recovery_success = sum(
        1 for r in runs if r.recovery_status == RECOVERY_SUCCESS
    )
    agg.n_recovery_failed = sum(
        1 for r in runs if r.recovery_status == RECOVERY_FAILED
    )
    agg.n_recovery_applicable = agg.n_recovery_success + agg.n_recovery_failed
    if agg.n_recovery_applicable > 0:
        agg.recovery_success_rate = (
            agg.n_recovery_success / agg.n_recovery_applicable
        )

    if attack_type == "none":
        # Baseline cell — compute FP rate
        if n > 0:
            agg.false_positive_rate = (
                sum(1 for r in runs if r.has_false_positive) / n
            )
    else:
        # Attack cell — FN rate is 1 - detection_rate
        agg.false_negative_rate = 1.0 - agg.detection_rate

    return agg


# ---------------------------------------------------------------------------
# Bulk analysis + summary writer
# ---------------------------------------------------------------------------


def analyze_runs(run_dirs: list[Path]) -> list[RunMetrics]:
    """Analyze a list of run directories."""
    return [analyze_run(d) for d in run_dirs]


def find_run_dirs(root: Path) -> list[Path]:
    """Return all `run_*/` subdirectories of `root` that contain a
    merged.jsonl file."""
    if not root.exists():
        return []
    out: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not child.name.startswith("run_"):
            continue
        if (child / "merged.jsonl").exists():
            out.append(child)
    return out


def write_summary(
    aggregates: dict[tuple[str, str], AggregateMetrics],
    output_path: Path,
) -> None:
    """Write an aggregate summary as JSON.

    Top-level keys are 'architecture/attack_type' strings; values are
    AggregateMetrics dicts.
    """
    out: dict[str, dict] = {}
    for (arch, atk), agg in aggregates.items():
        out[f"{arch}/{atk}"] = asdict(agg)
    with output_path.open("w") as f:
        json.dump(out, f, indent=2, default=str)
