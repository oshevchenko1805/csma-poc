"""Tests for FilterCommandsHandler's guard + mission-restore wiring.

Command-injection recovery must do two things: actuate the in-path guard
(block the attacker) and re-command the mission (undo a hijack that
landed before the filter engaged). These tests pin both, plus the
backward-compatible no-op path, with duck-typed stand-ins so no MAVSDK,
sockets, or real RecoveryRequest plumbing are needed.
"""

from __future__ import annotations

import asyncio

from enforcement.handlers.filter import FilterCommandsHandler


class _FakeGuard:
    def __init__(self) -> None:
        self.filtering = False

    def start_filtering(self) -> None:
        self.filtering = True


class _FakeResume:
    def __init__(self) -> None:
        self.calls = 0

    async def resume(self) -> None:
        self.calls += 1


class _BoomResume:
    async def resume(self) -> None:
        raise RuntimeError("mavsdk down")


class _Req:
    """Minimal stand-in: execute() only reads target_uav."""

    def __init__(self, uav: str = "uav_0") -> None:
        self.target_uav = uav


def test_execute_actuates_guard_and_resume():
    guard = _FakeGuard()
    resume = _FakeResume()
    h = FilterCommandsHandler(uav_id="uav_0", guard=guard)
    h.set_resume_runner(resume)
    ok, err = asyncio.run(h.execute(_Req()))
    assert ok is True and err is None
    assert guard.filtering is True
    assert resume.calls == 1
    assert h.is_filtered("uav_0")


def test_without_resume_runner_still_filters():
    guard = _FakeGuard()
    h = FilterCommandsHandler(uav_id="uav_0", guard=guard)
    ok, err = asyncio.run(h.execute(_Req()))
    assert ok is True and err is None
    assert guard.filtering is True


def test_no_args_backward_compatible():
    h = FilterCommandsHandler()
    ok, err = asyncio.run(h.execute(_Req()))
    assert ok is True and err is None
    assert h.is_filtered("uav_0")


def test_resume_failure_is_reported():
    h = FilterCommandsHandler(uav_id="uav_0", guard=_FakeGuard())
    h.set_resume_runner(_BoomResume())
    ok, err = asyncio.run(h.execute(_Req()))
    assert ok is False
    assert err is not None and "resume_failed" in err


def test_target_uav_property():
    assert FilterCommandsHandler(uav_id="uav_2").target_uav == "uav_2"
    assert FilterCommandsHandler().target_uav is None
