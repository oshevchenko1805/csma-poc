"""Tests for runners.mission_mavsdk (via FakeDroneController)."""

from __future__ import annotations

import asyncio

import pytest

from core.config import Waypoint
from runners.mission_mavsdk import (
    DroneController,
    MavsdkMissionRunner,
    MissionItem,
    MissionParamWriter,
    ned_to_gps,
)
from runners.missions import NullMissionRunner


# ---------------------------------------------------------------------------
# Test double
# ---------------------------------------------------------------------------


class FakeDroneController(DroneController):
    """Records every call; configurable failure points."""

    def __init__(
        self,
        endpoint: str,
        *,
        home: tuple[float, float, float] = (47.4, 8.5, 500.0),
        complete_after_calls: int = 1,
        raise_on: str | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.home = home
        self._complete_after = complete_after_calls
        self._raise_on = raise_on

        self.calls: list[str] = []
        self.uploaded: list[MissionItem] = []
        self.connected: bool = False
        self.takeoff_alt: float | None = None
        self.disconnected: bool = False
        self.rtl_called: bool = False
        self._mission_poll_count: int = 0
        # PX4 param store for param-access tests.
        self.params: dict[str, float] = {}

    def _maybe_raise(self, name: str) -> None:
        if self._raise_on == name:
            raise RuntimeError(f"{name} failed")

    async def connect(self):
        self.calls.append("connect")
        self._maybe_raise("connect")
        self.connected = True

    async def get_home_position(self):
        self.calls.append("get_home")
        return self.home

    async def arm_and_takeoff(self, *, altitude_m):
        self.calls.append("arm_and_takeoff")
        self._maybe_raise("takeoff")
        self.takeoff_alt = altitude_m

    async def upload_mission(self, items):
        self.calls.append("upload_mission")
        self._maybe_raise("upload")
        self.uploaded = list(items)

    async def start_mission(self):
        self.calls.append("start_mission")
        self._maybe_raise("start")

    async def is_mission_complete(self):
        self._mission_poll_count += 1
        return self._mission_poll_count >= self._complete_after

    async def return_to_launch(self):
        self.calls.append("rtl")
        self.rtl_called = True

    async def disconnect(self):
        self.calls.append("disconnect")
        self.disconnected = True

    async def get_param_float(self, name):
        self.calls.append("get_param")
        return self.params.get(name, 0.0)

    async def set_param_float(self, name, value):
        self.calls.append("set_param")
        self.params[name] = value


def _wps() -> list[Waypoint]:
    return [
        Waypoint(north_m=10.0, east_m=0.0, alt_m=5.0),
        Waypoint(north_m=20.0, east_m=10.0, alt_m=10.0),
    ]


def _make_runner(
    *,
    n_drones: int = 3,
    factory_failure: str | None = None,
    complete_after: int = 1,
    uav_ids: list[str] | None = None,
) -> tuple[MavsdkMissionRunner, list[FakeDroneController]]:
    created: list[FakeDroneController] = []

    def factory(ep: str) -> DroneController:
        c = FakeDroneController(
            ep,
            complete_after_calls=complete_after,
            raise_on=factory_failure,
        )
        created.append(c)
        return c

    runner = MavsdkMissionRunner(
        endpoints=[
            f"udp://127.0.0.1:{14540 + i}" for i in range(n_drones)
        ],
        waypoints=_wps(),
        controller_factory=factory,
        poll_period_sec=0.01,
        uav_ids=uav_ids,
    )
    return runner, created


# ---------------------------------------------------------------------------
# NED → GPS conversion
# ---------------------------------------------------------------------------


class TestNedToGps:
    def test_zero_offset(self):
        item = ned_to_gps(
            home_lat=47.4, home_lon=8.5,
            north_m=0.0, east_m=0.0, alt_m=0.0,
        )
        assert item.lat == 47.4
        assert item.lon == 8.5
        assert item.relative_alt_m == 0.0

    def test_north_offset(self):
        item = ned_to_gps(
            home_lat=47.4, home_lon=8.5,
            north_m=111.111, east_m=0.0, alt_m=0.0,
        )
        # 111.111 m north ≈ 0.001 degree lat
        assert abs(item.lat - 47.401) < 1e-5
        assert item.lon == 8.5

    def test_east_offset_scaled_by_cos_lat(self):
        # At lat=0 (equator), 111.111 m east = 0.001 deg lon exactly.
        item = ned_to_gps(
            home_lat=0.0, home_lon=0.0,
            north_m=0.0, east_m=111.111, alt_m=0.0,
        )
        assert abs(item.lon - 0.001) < 1e-5

    def test_alt_offset(self):
        item = ned_to_gps(
            home_lat=47.4, home_lon=8.5,
            north_m=0.0, east_m=0.0, alt_m=20.0,
        )
        # Altitude is now home-relative (passed through unchanged),
        # NOT absolute MSL.
        assert item.relative_alt_m == 20.0


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_empty_endpoints_rejected(self):
        with pytest.raises(ValueError, match="endpoints"):
            MavsdkMissionRunner(endpoints=[], waypoints=_wps())

    def test_empty_waypoints_rejected(self):
        with pytest.raises(ValueError, match="waypoints"):
            MavsdkMissionRunner(
                endpoints=["udp://x:1"], waypoints=[]
            )

    def test_invalid_takeoff_alt(self):
        with pytest.raises(ValueError, match="takeoff_altitude_m"):
            MavsdkMissionRunner(
                endpoints=["x"], waypoints=_wps(), takeoff_altitude_m=0
            )

    def test_invalid_poll_period(self):
        with pytest.raises(ValueError, match="poll_period_sec"):
            MavsdkMissionRunner(
                endpoints=["x"], waypoints=_wps(), poll_period_sec=-1
            )

    def test_uav_ids_length_mismatch_rejected(self):
        with pytest.raises(ValueError, match="uav_ids"):
            MavsdkMissionRunner(
                endpoints=["x:1", "x:2"],
                waypoints=_wps(),
                uav_ids=["uav_0"],  # only one, needs two
            )


# ---------------------------------------------------------------------------
# start() — lifecycle phases
# ---------------------------------------------------------------------------


class TestStart:
    def test_creates_one_controller_per_endpoint(self):
        runner, created = _make_runner(n_drones=3)
        asyncio.run(runner.start())
        assert len(created) == 3
        assert [c.endpoint for c in created] == [
            "udp://127.0.0.1:14540",
            "udp://127.0.0.1:14541",
            "udp://127.0.0.1:14542",
        ]

    def test_call_order_per_controller(self):
        runner, created = _make_runner(n_drones=2)
        asyncio.run(runner.start())
        for c in created:
            assert c.calls == [
                "connect",
                "arm_and_takeoff",
                "get_home",
                "upload_mission",
                "start_mission",
            ]

    def test_takeoff_altitude_passed_through(self):
        runner = MavsdkMissionRunner(
            endpoints=["udp://x:1"],
            waypoints=_wps(),
            controller_factory=lambda ep: FakeDroneController(ep),
            takeoff_altitude_m=25.0,
            poll_period_sec=0.01,
        )
        asyncio.run(runner.start())
        c = runner.controllers[0]
        assert isinstance(c, FakeDroneController)
        assert c.takeoff_alt == 25.0

    def test_mission_items_are_per_drone_home_relative(self):
        """Each drone gets waypoints in its own GPS frame derived
        from its own home position."""
        created: list[FakeDroneController] = []

        def factory(ep):
            # Distinct home positions per drone
            idx = int(ep.split(":")[-1]) - 14540
            home = (47.4 + 0.001 * idx, 8.5, 500.0)
            c = FakeDroneController(ep, home=home)
            created.append(c)
            return c

        runner = MavsdkMissionRunner(
            endpoints=["udp://x:14540", "udp://x:14541"],
            waypoints=[Waypoint(north_m=100.0, east_m=0.0, alt_m=10.0)],
            controller_factory=factory,
            poll_period_sec=0.01,
        )
        asyncio.run(runner.start())
        # Both drones should have one item each, with lat ≈
        # their_home_lat + 100/111111 ≈ + 0.0009
        for c in created:
            assert len(c.uploaded) == 1
            expected_lat = c.home[0] + 100.0 / 111_111.0
            assert abs(c.uploaded[0].lat - expected_lat) < 1e-6
            # Altitude is home-relative: the waypoint's alt_m passed through.
            assert c.uploaded[0].relative_alt_m == 10.0

    def test_double_start_raises(self):
        runner, _ = _make_runner(n_drones=1)
        asyncio.run(runner.start())
        with pytest.raises(RuntimeError, match="already started"):
            asyncio.run(runner.start())

    def test_failure_in_one_controller_aborts_start(self):
        """If any controller's connect fails, the gather raises."""
        runner, _ = _make_runner(n_drones=3, factory_failure="connect")
        with pytest.raises(RuntimeError, match="connect failed"):
            asyncio.run(runner.start())


# ---------------------------------------------------------------------------
# wait_until_complete
# ---------------------------------------------------------------------------


class TestWaitUntilComplete:
    def test_returns_true_when_all_complete(self):
        async def scenario():
            runner, _ = _make_runner(n_drones=2, complete_after=1)
            await runner.start()
            done = await runner.wait_until_complete(timeout_sec=1.0)
            await runner.abort()
            return done

        assert asyncio.run(scenario()) is True

    def test_returns_false_on_timeout(self):
        async def scenario():
            runner, _ = _make_runner(n_drones=2, complete_after=10_000)
            await runner.start()
            done = await runner.wait_until_complete(timeout_sec=0.1)
            await runner.abort()
            return done

        assert asyncio.run(scenario()) is False

    def test_waits_for_slowest(self):
        """If one drone completes immediately but another doesn't,
        the runner waits for the slowest."""
        created: list[FakeDroneController] = []

        def factory(ep):
            idx = int(ep.split(":")[-1]) - 14540
            # Drone 0 is done immediately, drone 1 takes 5 polls.
            c = FakeDroneController(
                ep, complete_after_calls=(1 if idx == 0 else 5)
            )
            created.append(c)
            return c

        runner = MavsdkMissionRunner(
            endpoints=["udp://x:14540", "udp://x:14541"],
            waypoints=_wps(),
            controller_factory=factory,
            poll_period_sec=0.01,
        )
        asyncio.run(runner.start())
        done = asyncio.run(runner.wait_until_complete(timeout_sec=1.0))
        asyncio.run(runner.abort())
        assert done is True

    def test_wait_before_start_returns_true(self):
        """If start() never ran, wait should not hang."""
        runner = MavsdkMissionRunner(
            endpoints=["x"],
            waypoints=_wps(),
            controller_factory=lambda ep: FakeDroneController(ep),
            poll_period_sec=0.01,
        )
        assert asyncio.run(runner.wait_until_complete(timeout_sec=0.1)) is True


# ---------------------------------------------------------------------------
# abort
# ---------------------------------------------------------------------------


class TestAbort:
    def test_abort_rtls_all_controllers(self):
        async def scenario():
            runner, created = _make_runner(n_drones=3)
            await runner.start()
            await runner.abort()
            return created

        created = asyncio.run(scenario())
        for c in created:
            assert c.rtl_called is True
            assert c.disconnected is True

    def test_abort_swallows_per_controller_failure(self):
        class FailingRtlController(FakeDroneController):
            async def return_to_launch(self):
                raise RuntimeError("RTL failed")

        async def factory(ep):
            return FailingRtlController(ep)

        runner = MavsdkMissionRunner(
            endpoints=["x:1", "x:2"],
            waypoints=_wps(),
            controller_factory=lambda ep: FailingRtlController(ep),
            poll_period_sec=0.01,
        )
        asyncio.run(runner.start())
        # Must not raise
        asyncio.run(runner.abort())

    def test_abort_before_start_is_safe(self):
        runner = MavsdkMissionRunner(
            endpoints=["x"],
            waypoints=_wps(),
            controller_factory=lambda ep: FakeDroneController(ep),
            poll_period_sec=0.01,
        )
        # Must not raise even though nothing was started
        asyncio.run(runner.abort())


# ---------------------------------------------------------------------------
# controller_for — uav_id lookup (step 10e)
# ---------------------------------------------------------------------------


class TestControllerFor:
    def test_resolves_controller_by_uav_id(self):
        runner, created = _make_runner(
            n_drones=3, uav_ids=["uav_0", "uav_1", "uav_2"]
        )
        asyncio.run(runner.start())
        assert runner.controller_for("uav_1") is created[1]
        assert runner.controller_for("uav_0") is created[0]

    def test_without_uav_ids_raises(self):
        runner, _ = _make_runner(n_drones=2)  # no uav_ids
        asyncio.run(runner.start())
        with pytest.raises(RuntimeError, match="uav_ids"):
            runner.controller_for("uav_0")

    def test_before_start_raises(self):
        runner, _ = _make_runner(n_drones=2, uav_ids=["uav_0", "uav_1"])
        with pytest.raises(RuntimeError, match="before start"):
            runner.controller_for("uav_0")

    def test_unknown_uav_id_raises(self):
        runner, _ = _make_runner(n_drones=2, uav_ids=["uav_0", "uav_1"])
        asyncio.run(runner.start())
        with pytest.raises(KeyError):
            runner.controller_for("uav_9")


# ---------------------------------------------------------------------------
# param_writer_for / MissionParamWriter (step 10e)
# ---------------------------------------------------------------------------


class TestParamWriter:
    def test_param_writer_for_returns_writer(self):
        runner, _ = _make_runner(n_drones=2, uav_ids=["uav_0", "uav_1"])
        pw = runner.param_writer_for("uav_1")
        assert isinstance(pw, MissionParamWriter)

    def test_writer_set_then_get_roundtrips_to_controller(self):
        runner, created = _make_runner(
            n_drones=2, uav_ids=["uav_0", "uav_1"]
        )
        asyncio.run(runner.start())
        pw = runner.param_writer_for("uav_1")

        asyncio.run(pw.set_param_float("SIM_GPS_OFF_N", 50.0))
        val = asyncio.run(pw.get_param_float("SIM_GPS_OFF_N"))
        assert val == 50.0
        # Written to the correct controller only (uav_1 = index 1).
        assert created[1].params["SIM_GPS_OFF_N"] == 50.0
        assert "SIM_GPS_OFF_N" not in created[0].params

    def test_writer_resolves_controller_lazily(self):
        """Writer can be created before start(); it only touches the
        controller on first use."""
        runner, _ = _make_runner(n_drones=1, uav_ids=["uav_0"])
        pw = runner.param_writer_for("uav_0")  # before start()
        asyncio.run(runner.start())
        asyncio.run(pw.set_param_float("SIM_GPS_OFF_N", 7.0))
        assert runner.controller_for("uav_0").params["SIM_GPS_OFF_N"] == 7.0

    def test_null_mission_runner_has_no_param_writer(self):
        assert NullMissionRunner(duration_sec=1.0).param_writer_for("uav_0") is None
