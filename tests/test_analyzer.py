"""Tests for metrics.analyzer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.events import (
    AttackEvent,
    IsolationAnnounce,
    RecoveryAck,
    SecurityEvent,
)
from core.logger import EventLogger
from metrics.analyzer import (
    AggregateMetrics,
    RunMetrics,
    aggregate,
    analyze_run,
    analyze_runs,
    compute_run_metrics,
    find_run_dirs,
    write_summary,
)


# ---------------------------------------------------------------------------
# Helpers to construct synthetic runs
# ---------------------------------------------------------------------------


def _write_run(
    root: Path,
    *,
    run_id: str,
    architecture: str,
    attack_type: str,
    target_uav: str | None,
    events: list,
) -> Path:
    run_dir = root / f"run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Write summary
    summary = {
        "run_id": run_id,
        "architecture": architecture,
        "attack_name": attack_type,
        "target_uav": target_uav,
    }
    (run_dir / "run_summary.json").write_text(json.dumps(summary))

    # Write merged log
    logger = EventLogger(run_dir / "merged.jsonl")
    for ev in events:
        logger.log(ev)
    logger.close()

    return run_dir


def _attack(target: str = "uav_0", t: float = 10.0, attack_type: str = "comm_disruption"):
    return AttackEvent(
        source="experiment_runner",
        timestamp=t,
        attack_type=attack_type,
        target_uav=target,
        phase="inject_start",
    )


def _security(
    target: str = "uav_0",
    t: float = 12.5,
    detector: str = "heartbeat",
    severity: str = "high",
):
    return SecurityEvent(
        source="monitor_uav_0",
        timestamp=t,
        detector=detector,
        target_uav=target,
        severity=severity,
    )


def _isolation(target: str = "uav_0", t: float = 12.6):
    return IsolationAnnounce(
        source="monitor_uav_0",
        timestamp=t,
        target_uav=target,
        reason="heartbeat_loss",
        decided_by="monitor_uav_0",
    )


def _ack(target: str = "uav_0", t: float = 20.0, success: bool = True):
    return RecoveryAck(
        source="coord_uav_1",
        timestamp=t,
        target_uav=target,
        action="restart_process",
        success=success,
        executor="enforcer_uav_0",
    )


# ---------------------------------------------------------------------------
# compute_run_metrics: per-run logic
# ---------------------------------------------------------------------------


class TestComputeRunMetrics:
    def test_full_pipeline_detection_and_recovery(self):
        events = [
            _attack(target="uav_0", t=10.0),
            _security(target="uav_0", t=13.2),
            _isolation(target="uav_0", t=13.3),
            _ack(target="uav_0", t=21.5, success=True),
        ]
        m = compute_run_metrics(
            events=events,
            run_id="r1",
            architecture="C",
            attack_type="comm_disruption",
            target_uav="uav_0",
        )
        assert m.detected is True
        assert m.recovery_success is True
        assert m.mttd_sec == pytest.approx(3.2)
        assert m.mttr_sec == pytest.approx(8.2)
        assert m.impact_scope == 1
        assert m.affected_uavs == ["uav_0"]
        assert m.has_false_positive is False

    def test_no_detection(self):
        events = [_attack(target="uav_0", t=10.0)]
        m = compute_run_metrics(
            events=events,
            run_id="r1",
            architecture="A",
            attack_type="comm_disruption",
            target_uav="uav_0",
        )
        assert m.detected is False
        assert m.mttd_sec is None
        assert m.mttr_sec is None
        assert m.recovery_success is False

    def test_detection_but_failed_recovery(self):
        events = [
            _attack(target="uav_0", t=10.0),
            _security(target="uav_0", t=12.0),
            _isolation(target="uav_0", t=12.1),
            _ack(target="uav_0", t=15.0, success=False),
        ]
        m = compute_run_metrics(
            events=events,
            run_id="r1",
            architecture="C",
            attack_type="comm_disruption",
            target_uav="uav_0",
        )
        assert m.detected is True
        assert m.mttd_sec == pytest.approx(2.0)
        assert m.recovery_success is False
        assert m.mttr_sec is None  # no successful ack

    def test_security_before_attack_ignored(self):
        """Security event whose timestamp predates the attack must not
        be treated as detection."""
        events = [
            _security(target="uav_0", t=5.0),  # before attack
            _attack(target="uav_0", t=10.0),
        ]
        m = compute_run_metrics(
            events=events,
            run_id="r1",
            architecture="C",
            attack_type="comm_disruption",
            target_uav="uav_0",
        )
        assert m.detected is False

    def test_first_security_event_wins(self):
        """When several SecurityEvents match, MTTD uses the earliest."""
        events = [
            _attack(target="uav_0", t=10.0),
            _security(target="uav_0", t=15.0),
            _security(target="uav_0", t=11.5),  # earliest
            _security(target="uav_0", t=12.0),
        ]
        m = compute_run_metrics(
            events=events,
            run_id="r1",
            architecture="C",
            attack_type="comm_disruption",
            target_uav="uav_0",
        )
        assert m.mttd_sec == pytest.approx(1.5)

    def test_impact_scope_counts_unique_uavs(self):
        events = [
            _attack(target="uav_0", t=10.0),
            _security(target="uav_0", t=12.0),
            _security(target="uav_1", t=12.5),
            _security(target="uav_0", t=13.0),  # duplicate target
            _security(target="uav_2", t=13.5),
        ]
        m = compute_run_metrics(
            events=events,
            run_id="r1",
            architecture="C",
            attack_type="comm_disruption",
            target_uav="uav_0",
        )
        assert m.impact_scope == 3
        assert m.affected_uavs == ["uav_0", "uav_1", "uav_2"]

    def test_false_positive_baseline_with_security_event(self):
        """In a baseline (attack='none') run, any SecurityEvent = FP."""
        events = [_security(target="uav_0", t=5.0)]
        m = compute_run_metrics(
            events=events,
            run_id="r1",
            architecture="C",
            attack_type="none",
            target_uav=None,
        )
        assert m.has_false_positive is True

    def test_false_positive_baseline_clean(self):
        m = compute_run_metrics(
            events=[],
            run_id="r1",
            architecture="C",
            attack_type="none",
            target_uav=None,
        )
        assert m.has_false_positive is False

    def test_false_positive_attack_collateral(self):
        """Attack run: security event on non-target UAV = FP."""
        events = [
            _attack(target="uav_0", t=10.0),
            _security(target="uav_0", t=12.0),  # legitimate detection
            _security(target="uav_1", t=12.5),  # collateral FP
        ]
        m = compute_run_metrics(
            events=events,
            run_id="r1",
            architecture="C",
            attack_type="comm_disruption",
            target_uav="uav_0",
        )
        assert m.detected is True
        assert m.has_false_positive is True


# ---------------------------------------------------------------------------
# analyze_run: file IO
# ---------------------------------------------------------------------------


class TestAnalyzeRun:
    def test_full_run_directory(self, tmp_path: Path):
        run_dir = _write_run(
            tmp_path,
            run_id="042",
            architecture="C",
            attack_type="comm_disruption",
            target_uav="uav_0",
            events=[
                _attack(target="uav_0", t=10.0),
                _security(target="uav_0", t=13.0),
                _isolation(target="uav_0", t=13.1),
                _ack(target="uav_0", t=21.0),
            ],
        )
        m = analyze_run(run_dir)
        assert m.error is None
        assert m.architecture == "C"
        assert m.attack_type == "comm_disruption"
        assert m.target_uav == "uav_0"
        assert m.detected is True
        assert m.mttd_sec == pytest.approx(3.0)
        assert m.mttr_sec == pytest.approx(7.9)

    def test_missing_merged_log(self, tmp_path: Path):
        run_dir = tmp_path / "run_001"
        run_dir.mkdir()
        (run_dir / "run_summary.json").write_text(
            json.dumps({"architecture": "C", "attack_name": "none"})
        )
        m = analyze_run(run_dir)
        assert m.error is not None
        assert "merged" in m.error

    def test_missing_summary(self, tmp_path: Path):
        """Missing summary is OK — analyzer falls back to '?' arch."""
        run_dir = tmp_path / "run_001"
        run_dir.mkdir()
        logger = EventLogger(run_dir / "merged.jsonl")
        logger.close()
        m = analyze_run(run_dir)
        # No error since merged exists; architecture defaults to '?'
        assert m.error is None
        assert m.architecture == "?"

    def test_corrupt_summary(self, tmp_path: Path):
        run_dir = tmp_path / "run_001"
        run_dir.mkdir()
        (run_dir / "run_summary.json").write_text("not valid json {")
        m = analyze_run(run_dir)
        assert m.error is not None


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_groups_by_arch_and_attack(self):
        runs = [
            RunMetrics(run_id="r1", architecture="C", attack_type="comm_disruption", target_uav="uav_0", mttd_sec=3.0, detected=True, recovery_success=True, mttr_sec=8.0),
            RunMetrics(run_id="r2", architecture="C", attack_type="comm_disruption", target_uav="uav_0", mttd_sec=4.0, detected=True, recovery_success=True, mttr_sec=9.0),
            RunMetrics(run_id="r3", architecture="A", attack_type="comm_disruption", target_uav="uav_0", mttd_sec=3.5, detected=True),
        ]
        agg = aggregate(runs)
        assert set(agg.keys()) == {("C", "comm_disruption"), ("A", "comm_disruption")}
        c = agg[("C", "comm_disruption")]
        assert c.n_runs == 2
        assert c.mttd_mean_sec == pytest.approx(3.5)
        assert c.mttr_mean_sec == pytest.approx(8.5)
        assert c.recovery_rate == 1.0

    def test_detection_rate(self):
        runs = [
            RunMetrics(run_id=f"r{i}", architecture="A", attack_type="cmd", target_uav="uav_0", detected=(i < 3))
            for i in range(5)
        ]
        agg = aggregate(runs)
        assert agg[("A", "cmd")].detection_rate == pytest.approx(0.6)
        assert agg[("A", "cmd")].false_negative_rate == pytest.approx(0.4)

    def test_false_positive_rate_baseline_only(self):
        runs = [
            RunMetrics(run_id=f"r{i}", architecture="C", attack_type="none", target_uav=None, has_false_positive=(i == 0))
            for i in range(10)
        ]
        agg = aggregate(runs)
        cell = agg[("C", "none")]
        assert cell.false_positive_rate == pytest.approx(0.1)
        assert cell.false_negative_rate is None  # not an attack cell

    def test_false_negative_rate_attack_only(self):
        runs = [
            RunMetrics(run_id=f"r{i}", architecture="C", attack_type="cmd", target_uav="uav_0", detected=True)
            for i in range(3)
        ] + [
            RunMetrics(run_id=f"r{i}", architecture="C", attack_type="cmd", target_uav="uav_0", detected=False)
            for i in range(2)
        ]
        agg = aggregate(runs)
        cell = agg[("C", "cmd")]
        # 3 of 5 detected
        assert cell.detection_rate == pytest.approx(0.6)
        assert cell.false_negative_rate == pytest.approx(0.4)
        assert cell.false_positive_rate is None  # not a baseline cell

    def test_skips_runs_with_error(self):
        runs = [
            RunMetrics(run_id="r1", architecture="C", attack_type="cmd", target_uav="uav_0", mttd_sec=3.0, detected=True),
            RunMetrics(run_id="r2", architecture="C", attack_type="cmd", target_uav="uav_0", error="bad file"),
        ]
        agg = aggregate(runs)
        cell = agg[("C", "cmd")]
        assert cell.n_runs == 1

    def test_percentiles(self):
        runs = [
            RunMetrics(run_id=f"r{i}", architecture="C", attack_type="cmd", target_uav="uav_0", mttd_sec=float(i), detected=True)
            for i in range(1, 11)  # mttds = [1, 2, ... 10]
        ]
        agg = aggregate(runs)
        cell = agg[("C", "cmd")]
        assert cell.mttd_mean_sec == pytest.approx(5.5)
        # p50 of 1..10 with linear interpolation
        assert cell.mttd_p50_sec == pytest.approx(5.5)
        # p95 of 1..10
        assert cell.mttd_p95_sec == pytest.approx(9.55, abs=0.01)


# ---------------------------------------------------------------------------
# Bulk / IO
# ---------------------------------------------------------------------------


class TestBulkAndIO:
    def test_find_run_dirs(self, tmp_path: Path):
        # Mix of valid and invalid subdirs
        for name in ["run_001", "run_002", "other", "run_003"]:
            d = tmp_path / name
            d.mkdir()
            if name in {"run_001", "run_002"}:
                (d / "merged.jsonl").write_text("")
            # run_003 has no merged.jsonl -> skipped

        dirs = find_run_dirs(tmp_path)
        names = [d.name for d in dirs]
        assert names == ["run_001", "run_002"]

    def test_find_run_dirs_missing_root(self, tmp_path: Path):
        assert find_run_dirs(tmp_path / "missing") == []

    def test_analyze_runs_and_write_summary(self, tmp_path: Path):
        # Two C runs of comm_disruption
        _write_run(tmp_path, run_id="001", architecture="C",
                   attack_type="comm_disruption", target_uav="uav_0",
                   events=[_attack(t=10), _security(t=12),
                           _isolation(t=12.1), _ack(t=18)])
        _write_run(tmp_path, run_id="002", architecture="C",
                   attack_type="comm_disruption", target_uav="uav_0",
                   events=[_attack(t=10), _security(t=14),
                           _isolation(t=14.1), _ack(t=22)])
        # One baseline C
        _write_run(tmp_path, run_id="003", architecture="C",
                   attack_type="none", target_uav=None, events=[])

        dirs = find_run_dirs(tmp_path)
        assert len(dirs) == 3
        runs = analyze_runs(dirs)
        assert len(runs) == 3
        assert all(r.error is None for r in runs)

        agg = aggregate(runs)
        assert ("C", "comm_disruption") in agg
        assert ("C", "none") in agg

        # Verify aggregates
        cd = agg[("C", "comm_disruption")]
        assert cd.n_runs == 2
        assert cd.mttd_mean_sec == pytest.approx(3.0)
        assert cd.detection_rate == 1.0

        baseline = agg[("C", "none")]
        assert baseline.false_positive_rate == 0.0

        # Write summary and re-read
        out = tmp_path / "summary.json"
        write_summary(agg, out)
        data = json.loads(out.read_text())
        assert "C/comm_disruption" in data
        assert "C/none" in data
        assert data["C/comm_disruption"]["n_runs"] == 2
