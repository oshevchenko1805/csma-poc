"""Tests for enforcement.handlers.filter."""

from __future__ import annotations

import asyncio
import threading

from core.events import RecoveryRequest
from enforcement.handlers.filter import FilterCommandsHandler


def _request(target: str) -> RecoveryRequest:
    return RecoveryRequest(
        source="c", target_uav=target, action="filter_commands", requester="c"
    )


class TestFilterCommandsHandler:
    def test_execute_marks_filtered(self):
        h = FilterCommandsHandler()
        assert not h.is_filtered("uav_2")
        ok, err = asyncio.run(h.execute(_request("uav_2")))
        assert ok is True
        assert err is None
        assert h.is_filtered("uav_2")
        assert h.filtered_uavs == frozenset({"uav_2"})

    def test_empty_target_rejected(self):
        h = FilterCommandsHandler()
        ok, err = asyncio.run(h.execute(_request("")))
        assert ok is False
        assert "empty target_uav" in err
        assert h.filtered_uavs == frozenset()

    def test_idempotent(self):
        h = FilterCommandsHandler()
        for _ in range(3):
            ok, _ = asyncio.run(h.execute(_request("uav_2")))
            assert ok
        assert h.filtered_uavs == frozenset({"uav_2"})

    def test_clear_specific_uav(self):
        h = FilterCommandsHandler()
        asyncio.run(h.execute(_request("uav_1")))
        asyncio.run(h.execute(_request("uav_2")))
        h.clear("uav_1")
        assert h.filtered_uavs == frozenset({"uav_2"})

    def test_clear_unknown_silent(self):
        h = FilterCommandsHandler()
        h.clear("never_filtered")  # no exception

    def test_reset_clears_all(self):
        h = FilterCommandsHandler()
        asyncio.run(h.execute(_request("uav_1")))
        asyncio.run(h.execute(_request("uav_2")))
        h.reset()
        assert h.filtered_uavs == frozenset()

    def test_thread_safe(self):
        h = FilterCommandsHandler()
        n_threads = 50
        per_thread = 10

        def worker(uav_id: str):
            for _ in range(per_thread):
                asyncio.run(h.execute(_request(uav_id)))

        threads = [
            threading.Thread(target=worker, args=(f"uav_{i % 5}",))
            for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 5 distinct uavs touched many times — set semantics guarantee
        # exactly 5 entries.
        assert h.filtered_uavs == frozenset({f"uav_{i}" for i in range(5)})
