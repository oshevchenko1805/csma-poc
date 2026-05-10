"""Tests for the Detector base contract."""

from __future__ import annotations

from typing import Optional

import pytest

from core.events import SecurityEvent, TelemetryEvent
from detectors.base import Detector


class _MinimalDetector(Detector):
    """Concrete implementation to verify the base class contract."""

    def __init__(self, target_uav: str = "uav_0") -> None:
        self._target_uav = target_uav
        self._fed: list[TelemetryEvent] = []
        self._reset_count = 0

    @property
    def name(self) -> str:
        return "minimal"

    @property
    def target_uav(self) -> str:
        return self._target_uav

    def feed(self, event: TelemetryEvent) -> Optional[SecurityEvent]:
        self._fed.append(event)
        return None

    def reset(self) -> None:
        self._reset_count += 1
        self._fed.clear()


class TestDetectorBase:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Detector()  # type: ignore[abstract]

    def test_default_tick_returns_none(self):
        d = _MinimalDetector()
        assert d.tick(now=123.0) is None

    def test_concrete_detector_works(self):
        d = _MinimalDetector()
        ev = TelemetryEvent(source="m", uav_id="uav_0", msg_type="HEARTBEAT")
        assert d.feed(ev) is None
        assert d.name == "minimal"
        assert d.target_uav == "uav_0"

    def test_reset_clears_state(self):
        d = _MinimalDetector()
        d.feed(TelemetryEvent(source="m", uav_id="uav_0", msg_type="HEARTBEAT"))
        d.reset()
        assert d._reset_count == 1
        assert d._fed == []
