"""Flight-mode timeline (review stage 3a-3).

The mode record is what shows whether a response mode (HOLD, OFFBOARD)
was entered and held, or whether PX4 fell back. It must never fail a
flight, and an empty record must read as NOT OBSERVED.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core.config import Waypoint
from runners.experiment import RunResult
from runners.mission_mavsdk import (
    DroneController,
    MavsdkDroneController,
    MavsdkMissionRunner,
)
from tests.test_mission_mavsdk import FakeDroneController


class _Mode:
    def __init__(self, name):
        self.name = name


def _fake_drone(names, *, fail_after=None):
    async def flight_mode():
        for i, n in enumerate(names):
            if fail_after is not None and i == fail_after:
                raise RuntimeError("stream broke")
            yield _Mode(n)
            await asyncio.sleep(0)
        await asyncio.sleep(3600)  # stream stays open, like MAVSDK

    return SimpleNamespace(telemetry=SimpleNamespace(flight_mode=flight_mode))


def _ctrl(drone):
    c = MavsdkDroneController("udp://:14540")
    c._drone = drone
    return c


async def _watch(c, secs=0.05):
    await c.start_flight_mode_watch()
    await asyncio.sleep(secs)
    await c.stop_flight_mode_watch()


class TestControllerTimeline:
    def test_records_changes_only(self):
        c = _ctrl(_fake_drone(["MISSION", "MISSION", "HOLD", "HOLD", "OFFBOARD"]))
        asyncio.run(_watch(c))
        log = c.flight_mode_log
        assert [e["mode"] for e in log] == ["MISSION", "HOLD", "OFFBOARD"]
        ts = [e["t_wall"] for e in log]
        assert ts == sorted(ts) and all(t > 1e9 for t in ts)

    def test_stream_error_is_marked_not_raised(self):
        c = _ctrl(_fake_drone(["MISSION", "HOLD"], fail_after=1))
        asyncio.run(_watch(c))
        log = c.flight_mode_log
        assert log[0]["mode"] == "MISSION"
        assert log[-1]["mode"] is None and "stream broke" in log[-1]["error"]

    def test_watch_before_connect_is_noop(self):
        c = MavsdkDroneController("udp://:14540")
        asyncio.run(_watch(c))
        assert c.flight_mode_log == []

    def test_stop_without_start_is_safe(self):
        asyncio.run(MavsdkDroneController("udp://:1").stop_flight_mode_watch())

    def test_log_is_a_copy(self):
        c = _ctrl(_fake_drone(["MISSION"]))
        asyncio.run(_watch(c))
        c.flight_mode_log.clear()
        assert len(c.flight_mode_log) == 1

    def test_base_controller_records_nothing(self):
        class Bare(FakeDroneController):
            pass
        b = Bare("x")
        asyncio.run(b.start_flight_mode_watch())
        assert b.flight_mode_log == []
        assert DroneController.flight_mode_log.fget(b) == []


class _Watching(FakeDroneController):
    def __init__(self, ep, **kw):
        super().__init__(ep, **kw)
        self._log = []

    @property
    def flight_mode_log(self):
        return list(self._log)

    async def start_flight_mode_watch(self):
        self.calls.append("watch_start")
        self._log.append({"t_wall": 1.0, "mode": "MISSION"})

    async def stop_flight_mode_watch(self):
        self.calls.append("watch_stop")


def _runner(uav_ids):
    made = []

    def factory(ep):
        c = _Watching(ep)
        made.append(c)
        return c

    r = MavsdkMissionRunner(
        endpoints=["udp://:14540", "udp://:14541"],
        waypoints=[Waypoint(north_m=10.0, east_m=0.0, alt_m=5.0)],
        controller_factory=factory,
        poll_period_sec=0.01,
        uav_ids=uav_ids,
    )
    return r, made


class TestMissionRunnerTimeline:
    def test_watch_starts_after_connect_and_stops_before_rtl(self):
        r, made = _runner(["uav_0", "uav_1"])

        async def go():
            await r.start()
            await r.abort()

        asyncio.run(go())
        for c in made:
            assert c.calls.index("connect") < c.calls.index("watch_start")
            assert c.calls.index("watch_start") < c.calls.index("arm_and_takeoff")
            assert c.calls.index("watch_stop") < c.calls.index("rtl")

    def test_flight_modes_keyed_by_uav_and_survive_abort(self):
        r, _ = _runner(["uav_0", "uav_1"])

        async def go():
            await r.start()
            await r.abort()

        asyncio.run(go())
        fm = r.flight_modes()
        assert set(fm) == {"uav_0", "uav_1"}
        assert fm["uav_0"] == [{"t_wall": 1.0, "mode": "MISSION"}]

    def test_keyed_by_endpoint_without_uav_ids(self):
        r, _ = _runner(None)
        asyncio.run(r.start())
        assert set(r.flight_modes()) == {"udp://:14540", "udp://:14541"}


def test_run_result_has_flight_modes_field():
    assert "flight_modes" in RunResult.__dataclass_fields__
