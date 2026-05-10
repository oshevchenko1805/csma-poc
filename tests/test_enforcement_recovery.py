"""
Tests for enforcement.recovery.

Async tests use asyncio.run() — no pytest-asyncio dependency required.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import pytest

from core.events import RecoveryAck, RecoveryRequest
from enforcement.recovery import ActionHandler, RecoveryExecutor


# ---------------------------------------------------------------------------
# Fake handlers
# ---------------------------------------------------------------------------


class FakeSuccessHandler(ActionHandler):
    def __init__(self) -> None:
        self.calls: list[RecoveryRequest] = []

    async def execute(
        self, request: RecoveryRequest
    ) -> tuple[bool, Optional[str]]:
        self.calls.append(request)
        return True, None


class FakeFailureHandler(ActionHandler):
    def __init__(self, error: str = "no soup for you") -> None:
        self.calls: list[RecoveryRequest] = []
        self.error = error

    async def execute(
        self, request: RecoveryRequest
    ) -> tuple[bool, Optional[str]]:
        self.calls.append(request)
        return False, self.error


class FakeRaisingHandler(ActionHandler):
    async def execute(
        self, request: RecoveryRequest
    ) -> tuple[bool, Optional[str]]:
        raise RuntimeError("simulated handler crash")


class FakeBadContractHandler(ActionHandler):
    """Handler that lies: success=True with an error string. Executor
    should normalize this to a clean ack."""

    async def execute(
        self, request: RecoveryRequest
    ) -> tuple[bool, Optional[str]]:
        return True, "should be ignored"


def _request(
    *,
    action: str = "restart_process",
    target_uav: str = "uav_2",
    requester: str = "coordinator",
) -> RecoveryRequest:
    return RecoveryRequest(
        source=requester,
        target_uav=target_uav,
        action=action,
        requester=requester,
    )


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Disabled executor
# ---------------------------------------------------------------------------


class TestDisabledExecutor:
    def test_returns_failure_ack(self):
        """Even with handlers registered, disabled=True short-circuits."""
        ex = RecoveryExecutor(
            source="enforcer_uav_2",
            enabled=False,
            handlers={"restart_process": FakeSuccessHandler()},
        )
        req = _request()
        ack = _run(ex.execute(req))

        assert isinstance(ack, RecoveryAck)
        assert ack.success is False
        assert ack.error == "recovery_disabled"
        assert ack.target_uav == "uav_2"
        assert ack.action == "restart_process"
        assert ack.source == "enforcer_uav_2"
        assert ack.executor == "enforcer_uav_2"
        assert ack.caused_by == req.event_id
        assert ex.stats["disabled_short_circuits"] == 1
        assert ex.stats["executed"] == 0

    def test_handler_not_invoked(self):
        h = FakeSuccessHandler()
        ex = RecoveryExecutor(
            source="x", enabled=False, handlers={"restart_process": h}
        )
        _run(ex.execute(_request()))
        assert h.calls == []


# ---------------------------------------------------------------------------
# Unknown action
# ---------------------------------------------------------------------------


class TestUnknownAction:
    def test_returns_failure_with_action_name(self):
        ex = RecoveryExecutor(
            source="x", enabled=True, handlers={"restart_process": FakeSuccessHandler()}
        )
        ack = _run(ex.execute(_request(action="brand_new_action")))
        assert ack.success is False
        assert ack.error == "unknown_action:brand_new_action"
        assert ex.stats["unknown_action"] == 1
        assert ex.stats["executed"] == 0


# ---------------------------------------------------------------------------
# Successful path
# ---------------------------------------------------------------------------


class TestSuccess:
    def test_success_ack_fields(self):
        h = FakeSuccessHandler()
        ex = RecoveryExecutor(
            source="enforcer_uav_2",
            enabled=True,
            handlers={"restart_process": h},
        )
        req = _request(action="restart_process", target_uav="uav_2")
        ack = _run(ex.execute(req))

        assert ack.success is True
        assert ack.error is None
        assert ack.target_uav == "uav_2"
        assert ack.action == "restart_process"
        assert ack.source == "enforcer_uav_2"
        assert ack.executor == "enforcer_uav_2"
        assert ack.caused_by == req.event_id

        assert h.calls == [req]
        assert ex.stats["succeeded"] == 1
        assert ex.stats["executed"] == 1

    def test_handler_dispatch_by_action_name(self):
        restart = FakeSuccessHandler()
        loiter = FakeSuccessHandler()
        filter_ = FakeSuccessHandler()
        ex = RecoveryExecutor(
            source="x",
            enabled=True,
            handlers={
                "restart_process": restart,
                "mode_loiter": loiter,
                "filter_commands": filter_,
            },
        )

        _run(ex.execute(_request(action="mode_loiter")))
        assert len(restart.calls) == 0
        assert len(loiter.calls) == 1
        assert len(filter_.calls) == 0

        _run(ex.execute(_request(action="restart_process")))
        _run(ex.execute(_request(action="restart_process")))
        assert len(restart.calls) == 2

    def test_handler_violating_contract_normalized(self):
        """Handler returns (True, "spam"). Ack must have error=None."""
        ex = RecoveryExecutor(
            source="x",
            enabled=True,
            handlers={"restart_process": FakeBadContractHandler()},
        )
        ack = _run(ex.execute(_request()))
        assert ack.success is True
        assert ack.error is None


# ---------------------------------------------------------------------------
# Handler returns failure
# ---------------------------------------------------------------------------


class TestHandlerFailure:
    def test_failure_propagates_error(self):
        ex = RecoveryExecutor(
            source="x",
            enabled=True,
            handlers={"restart_process": FakeFailureHandler(error="px4_not_running")},
        )
        ack = _run(ex.execute(_request()))
        assert ack.success is False
        assert ack.error == "px4_not_running"
        assert ex.stats["failed"] == 1
        assert ex.stats["succeeded"] == 0
        # handler_exceptions stays 0 — this was a handled failure, not a crash
        assert ex.stats["handler_exceptions"] == 0

    def test_failure_with_no_message_uses_default(self):
        ex = RecoveryExecutor(
            source="x",
            enabled=True,
            handlers={"restart_process": FakeFailureHandler(error="")},
        )
        ack = _run(ex.execute(_request()))
        assert ack.success is False
        assert ack.error == "handler_returned_failure"


# ---------------------------------------------------------------------------
# Handler raises
# ---------------------------------------------------------------------------


class TestHandlerException:
    def test_exception_caught_and_reported(self):
        ex = RecoveryExecutor(
            source="x",
            enabled=True,
            handlers={"restart_process": FakeRaisingHandler()},
        )
        ack = _run(ex.execute(_request()))
        assert ack.success is False
        assert ack.error.startswith("handler_exception:")
        assert "simulated handler crash" in ack.error
        assert ex.stats["handler_exceptions"] == 1
        assert ex.stats["failed"] == 1


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


class TestDiagnostics:
    def test_supported_actions(self):
        ex = RecoveryExecutor(
            source="x",
            enabled=True,
            handlers={
                "restart_process": FakeSuccessHandler(),
                "mode_loiter": FakeSuccessHandler(),
            },
        )
        assert ex.supported_actions == frozenset(
            {"restart_process", "mode_loiter"}
        )

    def test_enabled_property(self):
        on = RecoveryExecutor(source="x", enabled=True, handlers={})
        off = RecoveryExecutor(source="x", enabled=False, handlers={})
        assert on.enabled is True
        assert off.enabled is False

    def test_reset_clears_stats(self):
        ex = RecoveryExecutor(
            source="x",
            enabled=True,
            handlers={"restart_process": FakeSuccessHandler()},
        )
        _run(ex.execute(_request()))
        _run(ex.execute(_request(action="unknown")))
        assert ex.stats["succeeded"] == 1
        assert ex.stats["unknown_action"] == 1

        ex.reset()
        s = ex.stats
        assert s["succeeded"] == 0
        assert s["unknown_action"] == 0
        assert s["executed"] == 0
        assert s["failed"] == 0
        assert s["handler_exceptions"] == 0
        assert s["disabled_short_circuits"] == 0


# ---------------------------------------------------------------------------
# Mixed sequence — realistic scenario
# ---------------------------------------------------------------------------


class TestMixedSequence:
    def test_realistic_run(self):
        """Several requests, mix of success/failure/unknown."""
        success = FakeSuccessHandler()
        failure = FakeFailureHandler(error="boom")
        ex = RecoveryExecutor(
            source="enforcer",
            enabled=True,
            handlers={
                "restart_process": success,
                "mode_loiter": failure,
            },
        )

        a = _run(ex.execute(_request(action="restart_process", target_uav="uav_1")))
        b = _run(ex.execute(_request(action="mode_loiter", target_uav="uav_2")))
        c = _run(ex.execute(_request(action="filter_commands", target_uav="uav_2")))
        d = _run(ex.execute(_request(action="restart_process", target_uav="uav_2")))

        assert a.success and a.target_uav == "uav_1"
        assert not b.success and b.error == "boom"
        assert not c.success and c.error.startswith("unknown_action:")
        assert d.success and d.target_uav == "uav_2"

        s = ex.stats
        assert s["executed"] == 3        # a, b, d (c didn't dispatch)
        assert s["succeeded"] == 2       # a, d
        assert s["failed"] == 1          # b
        assert s["unknown_action"] == 1  # c
        assert s["handler_exceptions"] == 0
        assert s["disabled_short_circuits"] == 0

