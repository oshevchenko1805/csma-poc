"""B1 item 4: ranging_anomaly in the isolation and recovery tables
(H3_PREREGISTRATION.md: proportionate -> mode_loiter, trust_aware ->
hold_zero_velocity, detect_only -> none). v1 rows stay unchanged."""

from __future__ import annotations

import pytest

from core.events import IsolationAnnounce, SecurityEvent
from decision.isolation import IsolationDecider, reason_for_detector
from decision.recovery import (
    POLICY_TABLES,
    RecoveryAction,
    RecoveryDecider,
    RecoveryPolicy,
    action_for_reason,
)

# The tables as they were before B1 (commit 1b34295). B1 may only add
# the ranging_anomaly row.
V1_TABLES = {
    RecoveryPolicy.PROPORTIONATE: {
        "command_injection": RecoveryAction.FILTER_COMMANDS,
        "gps_anomaly": RecoveryAction.MODE_LOITER,
        "cross_check_anomaly": RecoveryAction.MODE_LOITER,
    },
    RecoveryPolicy.TRUST_AWARE: {
        "command_injection": RecoveryAction.FILTER_COMMANDS,
        "gps_anomaly": RecoveryAction.HOLD_ZERO_VELOCITY,
        "cross_check_anomaly": RecoveryAction.HOLD_ZERO_VELOCITY,
    },
    RecoveryPolicy.DETECT_ONLY: {},
}

EXPECTED = {
    RecoveryPolicy.PROPORTIONATE: RecoveryAction.MODE_LOITER,
    RecoveryPolicy.TRUST_AWARE: RecoveryAction.HOLD_ZERO_VELOCITY,
    RecoveryPolicy.DETECT_ONLY: None,
}


def test_detector_maps_to_reason():
    assert reason_for_detector("ranging") == "ranging_anomaly"


def test_v1_detector_reasons_unchanged():
    assert reason_for_detector("gps") == "gps_anomaly"
    assert reason_for_detector("cross_check") == "cross_check_anomaly"
    assert reason_for_detector("heartbeat") == "heartbeat_loss"
    assert reason_for_detector("command") == "command_injection"


def test_every_policy_is_covered():
    assert set(POLICY_TABLES) == set(EXPECTED)


@pytest.mark.parametrize("policy", sorted(EXPECTED))
def test_preregistered_action(policy):
    assert action_for_reason("ranging_anomaly", policy) == EXPECTED[policy]


@pytest.mark.parametrize("policy", sorted(EXPECTED))
def test_only_the_ranging_row_was_added(policy):
    table = dict(POLICY_TABLES[policy])
    table.pop("ranging_anomaly", None)
    assert table == V1_TABLES[policy]


@pytest.mark.parametrize("policy", sorted(EXPECTED))
def test_ranging_follows_the_position_anomaly_row(policy):
    """A ranging alarm is a position anomaly: same action as gps_anomaly."""
    assert (action_for_reason("ranging_anomaly", policy)
            == action_for_reason("gps_anomaly", policy))


@pytest.mark.parametrize("policy", sorted(EXPECTED))
def test_chain_security_event_to_recovery_request(policy):
    ev = SecurityEvent(source="monitor_uav_1", detector="ranging",
                       target_uav="uav_0", severity="high",
                       evidence={"path": "peer"})
    ann = IsolationDecider(source="monitor_uav_1").evaluate(ev)
    assert isinstance(ann, IsolationAnnounce)
    assert ann.reason == "ranging_anomaly"
    assert ann.target_uav == "uav_0"
    assert ann.caused_by == ev.event_id
    req = RecoveryDecider("coordinator_uav_0", enabled=True, policy=policy).evaluate(ann)
    if EXPECTED[policy] is None:
        assert req is None
    else:
        assert req.action == EXPECTED[policy]
        assert req.target_uav == "uav_0"
        assert req.caused_by == ann.event_id


def test_self_path_event_targets_the_monitors_own_uav():
    """The self path emits target_uav = the monitor's own UAV; the chain is
    the same as for any other target."""
    ev = SecurityEvent(source="monitor_uav_0", detector="ranging",
                       target_uav="uav_0", severity="high",
                       evidence={"path": "self"})
    ann = IsolationDecider(source="monitor_uav_0").evaluate(ev)
    assert ann.reason == "ranging_anomaly" and ann.target_uav == "uav_0"


def test_recovery_disabled_short_circuits():
    ann = IsolationAnnounce(source="m", target_uav="uav_0", reason="ranging_anomaly",
                            decided_by="m")
    assert RecoveryDecider("c", enabled=False, policy="proportionate").evaluate(ann) is None
