"""Tests for decision.recovery."""

from __future__ import annotations

import pytest

from core.events import IsolationAnnounce, RecoveryRequest
from decision.recovery import (
    REASON_TO_ACTION,
    RecoveryAction,
    RecoveryDecider,
    action_for_reason,
)


def _isolation(
    *,
    target_uav: str = "uav_2",
    reason: str = "heartbeat_loss",
    decided_by: str = "monitor_uav_0",
) -> IsolationAnnounce:
    return IsolationAnnounce(
        source=decided_by,
        target_uav=target_uav,
        reason=reason,
        decided_by=decided_by,
    )


class TestActionMapping:
    @pytest.mark.parametrize(
        "reason,action",
        [
            ("heartbeat_loss", RecoveryAction.RESTART_PROCESS),
            ("command_injection", RecoveryAction.FILTER_COMMANDS),
            ("gps_anomaly", RecoveryAction.MODE_LOITER),
            ("cross_check_anomaly", RecoveryAction.MODE_LOITER),
        ],
    )
    def test_known_reasons_map(self, reason: str, action: str):
        assert action_for_reason(reason) == action

    def test_unknown_reason_returns_none(self):
        assert action_for_reason("invented_reason") is None

    def test_constants_match_table(self):
        # Sanity check: the public constants are what's in the table.
        assert RecoveryAction.RESTART_PROCESS == "restart_process"
        assert RecoveryAction.FILTER_COMMANDS == "filter_commands"
        assert RecoveryAction.MODE_LOITER == "mode_loiter"
        assert REASON_TO_ACTION["heartbeat_loss"] == "restart_process"


class TestEnabledFlag:
    def test_disabled_decider_returns_none(self):
        """Architectures A and B: recovery=false -> always None."""
        d = RecoveryDecider(source="coordinator", enabled=False)
        result = d.evaluate(_isolation())
        assert result is None
        # State should not be marked either
        assert not d.is_recovery_requested("uav_2")

    def test_enabled_property(self):
        on = RecoveryDecider(source="c", enabled=True)
        off = RecoveryDecider(source="c", enabled=False)
        assert on.enabled is True
        assert off.enabled is False


class TestEvaluate:
    def test_heartbeat_loss_yields_restart(self):
        d = RecoveryDecider(source="coordinator_uav_0", enabled=True)
        ann = _isolation(target_uav="uav_2", reason="heartbeat_loss")
        result = d.evaluate(ann)

        assert isinstance(result, RecoveryRequest)
        assert result.target_uav == "uav_2"
        assert result.action == RecoveryAction.RESTART_PROCESS
        assert result.requester == "coordinator_uav_0"
        assert result.source == "coordinator_uav_0"
        assert result.caused_by == ann.event_id
        assert d.is_recovery_requested("uav_2")

    def test_gps_anomaly_yields_loiter(self):
        d = RecoveryDecider(source="c", enabled=True)
        result = d.evaluate(_isolation(reason="gps_anomaly"))
        assert result is not None
        assert result.action == RecoveryAction.MODE_LOITER

    def test_command_injection_yields_filter(self):
        d = RecoveryDecider(source="c", enabled=True)
        result = d.evaluate(_isolation(reason="command_injection"))
        assert result is not None
        assert result.action == RecoveryAction.FILTER_COMMANDS

    def test_cross_check_yields_loiter(self):
        d = RecoveryDecider(source="c", enabled=True)
        result = d.evaluate(_isolation(reason="cross_check_anomaly"))
        assert result is not None
        assert result.action == RecoveryAction.MODE_LOITER

    def test_unknown_reason_returns_none(self):
        d = RecoveryDecider(source="c", enabled=True)
        result = d.evaluate(_isolation(reason="exotic_unmapped"))
        assert result is None
        # State NOT marked — we did not actually request anything
        assert not d.is_recovery_requested("uav_2")

    def test_empty_target_uav_returns_none(self):
        d = RecoveryDecider(source="c", enabled=True)
        ann = IsolationAnnounce(
            source="m", target_uav="", reason="heartbeat_loss", decided_by="m"
        )
        assert d.evaluate(ann) is None


class TestStateAndDeduplication:
    def test_second_isolation_for_same_uav_not_re_requested(self):
        d = RecoveryDecider(source="c", enabled=True)
        first = d.evaluate(_isolation(target_uav="uav_2"))
        second = d.evaluate(_isolation(target_uav="uav_2"))
        assert first is not None
        assert second is None

    def test_independent_per_uav(self):
        d = RecoveryDecider(source="c", enabled=True)
        a = d.evaluate(_isolation(target_uav="uav_1"))
        b = d.evaluate(_isolation(target_uav="uav_2"))
        assert a is not None
        assert b is not None
        assert d.requested_uavs == frozenset({"uav_1", "uav_2"})

    def test_mark_recovered_allows_fresh_request(self):
        d = RecoveryDecider(source="c", enabled=True)
        first = d.evaluate(_isolation(target_uav="uav_2"))
        d.mark_recovered("uav_2")
        assert not d.is_recovery_requested("uav_2")
        second = d.evaluate(_isolation(target_uav="uav_2"))
        assert second is not None
        assert second.event_id != first.event_id

    def test_mark_recovered_unknown_silent(self):
        d = RecoveryDecider(source="c", enabled=True)
        d.mark_recovered("never_seen")  # no exception

    def test_reset_clears_all(self):
        d = RecoveryDecider(source="c", enabled=True)
        d.evaluate(_isolation(target_uav="uav_1"))
        d.evaluate(_isolation(target_uav="uav_2"))
        d.reset()
        assert d.requested_uavs == frozenset()
        assert d.evaluate(_isolation(target_uav="uav_1")) is not None
