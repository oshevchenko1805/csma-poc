"""Tests for recovery policies (review stage 3).

Guards: the default policy is byte-for-byte the historical table, the
heartbeat-loss regression holds under every policy, and the policy names
agree between decision.recovery and core.config.
"""

from __future__ import annotations

import pytest

from core.config import DEFAULT_RECOVERY_POLICY, VALID_RECOVERY_POLICIES
from core.events import IsolationAnnounce
from decision.recovery import (
    POLICY_TABLES,
    REASON_TO_ACTION,
    RecoveryAction,
    RecoveryDecider,
    RecoveryPolicy,
    action_for_reason,
)

REASONS = ("heartbeat_loss", "command_injection", "gps_anomaly",
           "cross_check_anomaly")


def _ann(reason: str, target: str = "uav_0") -> IsolationAnnounce:
    return IsolationAnnounce(source="m", target_uav=target, reason=reason,
                             decided_by="m")


class TestPolicyTables:
    def test_names_match_config_whitelist(self):
        assert frozenset(POLICY_TABLES) == VALID_RECOVERY_POLICIES
        assert DEFAULT_RECOVERY_POLICY == RecoveryPolicy.PROPORTIONATE

    def test_default_policy_is_the_historical_table(self):
        assert POLICY_TABLES[RecoveryPolicy.PROPORTIONATE] is REASON_TO_ACTION
        for r in REASONS:
            assert action_for_reason(r) == REASON_TO_ACTION.get(r)

    @pytest.mark.parametrize("policy", sorted(POLICY_TABLES))
    def test_heartbeat_loss_has_no_action_in_any_policy(self, policy):
        assert action_for_reason("heartbeat_loss", policy) is None

    def test_trust_aware_table(self):
        p = RecoveryPolicy.TRUST_AWARE
        assert action_for_reason("gps_anomaly", p) == RecoveryAction.HOLD_ZERO_VELOCITY
        assert action_for_reason("cross_check_anomaly", p) == RecoveryAction.HOLD_ZERO_VELOCITY
        # estimate intact under command injection -> action unchanged
        assert action_for_reason("command_injection", p) == RecoveryAction.FILTER_COMMANDS

    @pytest.mark.parametrize("reason", REASONS)
    def test_detect_only_never_acts(self, reason):
        assert action_for_reason(reason, RecoveryPolicy.DETECT_ONLY) is None

    def test_unknown_policy_raises(self):
        with pytest.raises(ValueError, match="unknown recovery policy"):
            action_for_reason("gps_anomaly", "aggressive")


class TestDeciderPolicy:
    def test_default_policy_property(self):
        assert RecoveryDecider("c", enabled=True).policy == "proportionate"

    def test_unknown_policy_rejected_at_construction(self):
        with pytest.raises(ValueError):
            RecoveryDecider("c", enabled=True, policy="aggressive")

    def test_trust_aware_requests_zero_velocity(self):
        d = RecoveryDecider("c", enabled=True, policy="trust_aware")
        req = d.evaluate(_ann("gps_anomaly"))
        assert req is not None
        assert req.action == RecoveryAction.HOLD_ZERO_VELOCITY

    def test_proportionate_still_requests_loiter(self):
        req = RecoveryDecider("c", enabled=True).evaluate(_ann("gps_anomaly"))
        assert req.action == RecoveryAction.MODE_LOITER

    def test_detect_only_requests_nothing_and_leaves_no_state(self):
        d = RecoveryDecider("c", enabled=True, policy="detect_only")
        for r in REASONS:
            assert d.evaluate(_ann(r)) is None
        assert d.requested_uavs == frozenset()
