"""
MavsdkMissionRunner — concrete MissionRunner driving N PX4 instances.

Drives a coordinated waypoint mission across N UAVs simultaneously
via MAVSDK. Each UAV runs the same NED-relative waypoint sequence
(converted to GPS coordinates relative to its own home position),
which produces a tight formation flight suitable for measuring
detection and recovery during operational missions.

Architecture
------------
- Per UAV: one DroneController (interface) wraps connect / takeoff /
  upload / start / wait / RTL / disconnect.
- The runner holds N controllers and runs each operation in parallel
  via asyncio.gather.
- DI: a controller_factory callable produces controllers. Default is
  MavsdkDroneController (lazy mavsdk import); tests pass a factory
  returning FakeDroneController.

Param access for attacks (step 10e)
-----------------------------------
During flight the mission controller owns the UDP fan-out port
(14560+i); no second MAVSDK client can bind it. A param-writing attack
(gps_spoofing) therefore cannot open its own connection mid-flight and
must borrow the live mission connection. DroneController exposes
`get_param_float` / `set_param_float`, and MavsdkMissionRunner offers
`controller_for(uav_id)` so the experiment layer can hand the attack a
ParamWriter backed by the already-connected controller. This keeps the
single working param channel and avoids a second mavsdk_server.

Coordinate frame
----------------
Config waypoints are in local NED frame (north/east/down meters
relative to home). At runtime, we query each UAV's home position
via MAVSDK (after takeoff) and convert NED → GPS using a small-area
spherical-earth approximation:

  lat_offset_deg = north_m / 111111
  lon_offset_deg = east_m / (111111 * cos(home_lat))

This is accurate to ~0.1% for distances under 1 km, which matches
our mission scale.

Altitude convention (step 10d fix)
----------------------------------
MAVSDK's MissionItem takes `relative_altitude_m` — height above the
home/takeoff point, NOT absolute MSL. Our internal MissionItem.alt
field therefore carries the *relative* altitude (= the waypoint's
alt_m offset above home), and upload_mission feeds it straight
through. A previous version stored absolute MSL altitude here but
hard-coded `relative_altitude_m=0.0` in the upload, which made every
waypoint command "descend to home altitude". After takeoff to 15 m
the drone would immediately try to descend to 0 m above home, trip
mc_pos_control "invalid setpoints", and enter a Failsafe blind-land
loop (observed in step 10d baseline on uav_0: chronic EKF horizontal
residual + cross_check false positives downstream).

PoC caveats (Chapter 4)
-----------------------
- Each call to MAVSDK is a fresh System() instance bound to one UDP
  endpoint. There is no shared connection state across calls; this
  keeps the runner simple at the cost of ~1 s connect overhead per
  controller. Acceptable for missions whose lifecycle is "connect
  once at start, disconnect at end".
- Mission complete is detected via `is_mission_complete()` polling.
  MAVSDK's MissionProgress stream is also available but its
  semantics across PX4 versions are inconsistent.
- Takeoff altitude is fixed (15 m default) and not configurable per
  waypoint. Real missions would parameterise this.

Lifecycle
---------
  start():            connect all → arm+takeoff all → upload+start mission
  wait_until_complete: poll all controllers, return True iff all done
  abort():            best-effort RTL all, then disconnect
"""

from __future__ import annotations

import asyncio
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

from attacks.base import ParamWriter
from core.config import Waypoint
from enforcement.handlers.loiter import MavsdkRunner
from runners.missions import MissionRunner


@dataclass(frozen=True)
class MissionItem:
    """A GPS waypoint to feed MAVSDK MissionItem.

    `relative_alt_m` is height ABOVE HOME (positive = up), matching
    MAVSDK MissionItem.relative_altitude_m — NOT absolute MSL.
    """

    lat: float
    lon: float
    relative_alt_m: float  # height above home, m (positive = up)


def ned_to_gps(
    *,
    home_lat: float,
    home_lon: float,
    north_m: float,
    east_m: float,
    alt_m: float,
) -> MissionItem:
    """Convert NED offset to a GPS lat/lon plus home-relative altitude.

    Accurate to ~0.1% for distances < 1 km.

    Inputs:
      home_lat, home_lon (degrees)
      north_m, east_m  (offsets, m)
      alt_m            (offset above home, m, positive = up)

    The altitude is passed through unchanged as `relative_alt_m`
    because MAVSDK wants height above home, not absolute MSL — so the
    home altitude is not needed here.
    """
    # 1 degree lat ≈ 111,111 m at the equator and is essentially
    # constant. 1 degree lon shrinks toward the poles.
    lat_offset = north_m / 111_111.0
    cos_lat = math.cos(math.radians(home_lat))
    if abs(cos_lat) < 1e-9:
        # Polar singularity — defensive only; PX4 SITL isn't at the poles.
        cos_lat = 1e-9
    lon_offset = east_m / (111_111.0 * cos_lat)
    return MissionItem(
        lat=home_lat + lat_offset,
        lon=home_lon + lon_offset,
        relative_alt_m=alt_m,
    )


# ---------------------------------------------------------------------------
# DroneController — DI seam for one UAV
# ---------------------------------------------------------------------------


class DroneController(ABC):
    """Per-UAV mission interface. Lifecycle:
    connect → arm_and_takeoff → upload → start → poll/abort → disconnect.
    """

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def get_home_position(self) -> tuple[float, float, float]:
        """Returns (lat, lon, alt_msl_m). Call only after connected."""

    @abstractmethod
    async def arm_and_takeoff(self, *, altitude_m: float) -> None: ...

    @abstractmethod
    async def upload_mission(self, items: list[MissionItem]) -> None: ...

    @abstractmethod
    async def start_mission(self) -> None: ...

    @abstractmethod
    async def is_mission_complete(self) -> bool: ...

    @abstractmethod
    async def return_to_launch(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    # --- Optional param access (borrowed by param-writing attacks) ---
    # Concrete (non-abstract) defaults so controllers that don't support
    # param access — e.g. test fakes — still instantiate unchanged.
    # MavsdkDroneController overrides both with real MAVSDK Param calls.
    async def get_param_float(self, name: str) -> float:
        raise NotImplementedError("param access not supported by this controller")

    async def set_param_float(self, name: str, value: float) -> None:
        raise NotImplementedError("param access not supported by this controller")

    # --- Optional loiter/hold (borrowed by recovery via mission conn) ---
    # Concrete default so controllers that don't support it (test fakes)
    # still instantiate. MavsdkDroneController overrides with action.hold().
    async def hold(self) -> None:
        raise NotImplementedError("hold not supported by this controller")


class MavsdkDroneController(DroneController):
    """Real MAVSDK-driven controller. Lazy mavsdk import."""

    DEFAULT_CONNECT_TIMEOUT_SEC: float = 30.0
    DEFAULT_ACTION_TIMEOUT_SEC: float = 30.0

    def __init__(
        self,
        endpoint: str,
        *,
        connect_timeout_sec: float = DEFAULT_CONNECT_TIMEOUT_SEC,
        action_timeout_sec: float = DEFAULT_ACTION_TIMEOUT_SEC,
        grpc_port: Optional[int] = None,
    ) -> None:
        self._endpoint = endpoint
        self._connect_timeout = connect_timeout_sec
        self._action_timeout = action_timeout_sec
        # Per-instance gRPC port; required to avoid 50051 collisions when
        # multiple Systems run in parallel (step 10b empirically verified).
        self._grpc_port = grpc_port
        self._drone = None  # mavsdk.System, set on connect

    async def connect(self) -> None:
        from mavsdk import System  # lazy

        # Per-instance gRPC port: default port 50051 collides between
        # parallel mavsdk_server subprocesses, only one wins the bind.
        if self._grpc_port is None:
            self._drone = System()
        else:
            self._drone = System(port=self._grpc_port)
        await asyncio.wait_for(
            self._drone.connect(system_address=self._endpoint),
            timeout=self._connect_timeout,
        )
        # First, wait until the first heartbeat arrives ('discovered').
        async for state in self._drone.core.connection_state():
            if state.is_connected:
                break
        # Then wait until the drone is actually ready. PX4 reports
        # is_connected on first heartbeat, but param subsystem and
        # EKF/GPS take much longer to converge. Without this wait any
        # immediate param op (set_takeoff_altitude) is silently ignored.
        # Step 10b diagnosed empirically: PX4 SITL on M4 Pro ARM64
        # reaches is_armable in ~30-60s.
        async def _wait_armable():
            async for h in self._drone.telemetry.health():
                if h.is_armable:
                    return
        print('[mission] waiting is_armable (GPS/EKF converge)...', flush=True)
        try:
            await asyncio.wait_for(_wait_armable(), timeout=90.0)
        except asyncio.TimeoutError:
            print('[mission] TIMEOUT in _wait_armable: is_armable never True (no position estimate)', flush=True)
            raise
        print('[mission] is_armable OK', flush=True)

    async def get_home_position(self) -> tuple[float, float, float]:
        assert self._drone is not None
        # Wait for a global position fix (GPS lock), then read home.
        async for hp in self._drone.telemetry.home():
            return (hp.latitude_deg, hp.longitude_deg, hp.absolute_altitude_m)
        raise RuntimeError("no home position available")

    async def arm_and_takeoff(self, *, altitude_m: float) -> None:
        assert self._drone is not None
        print('[mission] set_takeoff_altitude...', flush=True)
        await asyncio.wait_for(
            self._drone.action.set_takeoff_altitude(altitude_m),
            timeout=self._action_timeout,
        )
        print('[mission] arm...', flush=True)
        await asyncio.wait_for(
            self._drone.action.arm(), timeout=self._action_timeout
        )
        print('[mission] takeoff...', flush=True)
        await asyncio.wait_for(
            self._drone.action.takeoff(), timeout=self._action_timeout
        )
        # Wait until we're actually airborne (in_air state).
        async for in_air in self._drone.telemetry.in_air():
            if in_air:
                return

    async def upload_mission(self, items: list[MissionItem]) -> None:
        from mavsdk.mission import MissionItem as MItem, MissionPlan

        assert self._drone is not None
        mitems = [
            MItem(
                latitude_deg=it.lat,
                longitude_deg=it.lon,
                relative_altitude_m=it.relative_alt_m,
                speed_m_s=5.0,
                is_fly_through=True,
                gimbal_pitch_deg=0.0,
                gimbal_yaw_deg=0.0,
                camera_action=MItem.CameraAction.NONE,
                loiter_time_s=0.0,
                camera_photo_interval_s=0.0,
                acceptance_radius_m=2.0,
                yaw_deg=float("nan"),
                camera_photo_distance_m=float("nan"),
                vehicle_action=MItem.VehicleAction.NONE,
            )
            for it in items
        ]
        plan = MissionPlan(mitems)
        await asyncio.wait_for(
            self._drone.mission.upload_mission(plan),
            timeout=self._action_timeout,
        )

    async def start_mission(self) -> None:
        assert self._drone is not None
        await asyncio.wait_for(
            self._drone.mission.start_mission(),
            timeout=self._action_timeout,
        )

    async def is_mission_complete(self) -> bool:
        assert self._drone is not None
        try:
            return await asyncio.wait_for(
                self._drone.mission.is_mission_finished(),
                timeout=2.0,
            )
        except Exception:
            return False

    async def return_to_launch(self) -> None:
        assert self._drone is not None
        try:
            await asyncio.wait_for(
                self._drone.action.return_to_launch(),
                timeout=self._action_timeout,
            )
        except Exception:
            pass

    async def disconnect(self) -> None:
        # MAVSDK Python doesn't expose explicit disconnect — letting
        # the System go out of scope is the convention.
        self._drone = None

    # --- Param access (borrowed by gps_spoofing during flight) ---
    async def get_param_float(self, name: str) -> float:
        assert self._drone is not None
        return await asyncio.wait_for(
            self._drone.param.get_param_float(name),
            timeout=self._action_timeout,
        )

    async def set_param_float(self, name: str, value: float) -> None:
        assert self._drone is not None
        await asyncio.wait_for(
            self._drone.param.set_param_float(name, value),
            timeout=self._action_timeout,
        )

    async def hold(self) -> None:
        # MAVSDK action.hold() == PX4 LOITER mode. Uses the live mission
        # connection — the only channel that reaches the target in flight.
        assert self._drone is not None
        await asyncio.wait_for(
            self._drone.action.hold(),
            timeout=self._action_timeout,
        )


# ---------------------------------------------------------------------------
# Mission runner
# ---------------------------------------------------------------------------


ControllerFactory = Callable[[str], DroneController]
"""(mavsdk_endpoint) -> DroneController instance."""


class MissionParamWriter:
    """ParamWriter backed by a live mission controller.

    Resolves the target controller lazily on each call via
    MavsdkMissionRunner.controller_for, so it can be handed to an attack
    at arm() time (before the mission has started and controllers
    exist) and used later at fire()/cleanup() when they do. Delegates
    param ops to the controller's borrowed MAVSDK connection — the only
    channel that reaches PX4 params while the mission holds the UDP
    fan-out port. Satisfies the attacks.base.ParamWriter Protocol
    structurally.
    """

    def __init__(self, runner: "MavsdkMissionRunner", uav_id: str) -> None:
        self._runner = runner
        self._uav_id = uav_id

    async def get_param_float(self, name: str) -> float:
        controller = self._runner.controller_for(self._uav_id)
        return await controller.get_param_float(name)

    async def set_param_float(self, name: str, value: float) -> None:
        controller = self._runner.controller_for(self._uav_id)
        await controller.set_param_float(name, value)


class MissionLoiterRunner(MavsdkRunner):
    """MavsdkRunner (loiter DI seam) backed by a live mission controller.

    Symmetric to MissionParamWriter: instead of opening its own MAVSDK
    System (which can't bind the target's port mid-flight), it borrows
    the mission controller and issues action.hold() on it. The `endpoint`
    argument of set_loiter is ignored — the controller already holds the
    connection.

    Cross-loop bridge (step 10e)
    ----------------------------
    The mission controller's MAVSDK System (and its gRPC channel) lives
    in the main ExperimentRunner event loop. Recovery, however, is driven
    from the Coordinator's mesh-receiver thread via a short-lived
    `asyncio.run()` (see runners/coordinator.py) — a different loop and
    thread. A gRPC future is bound to the loop that created the System, so
    awaiting hold() directly from the recovery loop fails with
    "attached to a different loop". We therefore schedule hold() back onto
    the main loop with run_coroutine_threadsafe and block for the result.
    This is the run_coroutine_threadsafe path anticipated in the
    coordinator module docstring; the main loop is idle (awaiting the
    observation-window sleep) during recovery, so it is free to run it.
    """

    DEFAULT_BRIDGE_TIMEOUT_SEC: float = 10.0

    def __init__(
        self,
        runner: "MavsdkMissionRunner",
        uav_id: str,
        *,
        main_loop=None,
        bridge_timeout_sec: float = DEFAULT_BRIDGE_TIMEOUT_SEC,
    ) -> None:
        self._runner = runner
        self._uav_id = uav_id
        self._main_loop = main_loop
        self._bridge_timeout = bridge_timeout_sec

    async def set_loiter(self, endpoint: str, *, timeout_sec: float) -> None:
        controller = self._runner.controller_for(self._uav_id)

        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None

        # Same loop as the mission connection (or no main loop captured):
        # await directly.
        if self._main_loop is None or current is self._main_loop:
            await controller.hold()
            return

        # Different loop/thread: schedule hold() on the main loop where the
        # MAVSDK System lives, and block this recovery loop until it's done.
        future = asyncio.run_coroutine_threadsafe(
            controller.hold(), self._main_loop
        )
        # future.result() is blocking; run it off the recovery loop so we
        # don't stall it, and honour a timeout so recovery can't hang.
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: future.result(timeout=self._bridge_timeout)
        )


class MavsdkMissionRunner(MissionRunner):
    """Drive N UAVs through a coordinated NED waypoint sequence."""

    DEFAULT_TAKEOFF_ALT_M: float = 15.0
    DEFAULT_POLL_PERIOD_SEC: float = 1.0

    def __init__(
        self,
        *,
        endpoints: list[str],
        waypoints: list[Waypoint],
        controller_factory: Optional[ControllerFactory] = None,
        takeoff_altitude_m: float = DEFAULT_TAKEOFF_ALT_M,
        poll_period_sec: float = DEFAULT_POLL_PERIOD_SEC,
        uav_ids: Optional[list[str]] = None,
    ) -> None:
        if not endpoints:
            raise ValueError("endpoints must be non-empty")
        if not waypoints:
            raise ValueError("waypoints must be non-empty")
        if takeoff_altitude_m <= 0:
            raise ValueError("takeoff_altitude_m must be positive")
        if poll_period_sec <= 0:
            raise ValueError("poll_period_sec must be positive")
        if uav_ids is not None and len(uav_ids) != len(endpoints):
            raise ValueError("uav_ids must match endpoints length")

        self._endpoints = list(endpoints)
        self._waypoints = list(waypoints)
        self._factory: ControllerFactory = (
            controller_factory
            if controller_factory is not None
            else (lambda ep: MavsdkDroneController(ep))
        )
        self._takeoff_alt = takeoff_altitude_m
        self._poll_period = poll_period_sec
        # Parallel to _endpoints: uav_ids[i] flies on endpoints[i]. Lets
        # controller_for() resolve a controller by uav_id without relying
        # on endpoint-string parsing. None = mapping not provided.
        self._uav_ids: Optional[list[str]] = (
            list(uav_ids) if uav_ids is not None else None
        )

        self._controllers: list[DroneController] = []
        self._started: bool = False

    @property
    def controllers(self) -> list[DroneController]:
        return list(self._controllers)

    def controller_for(self, uav_id: str) -> DroneController:
        """Return the live controller driving `uav_id`.

        Requires uav_ids to have been supplied at construction and
        start() to have built the controllers. Errors are explicit so a
        wiring bug surfaces loudly instead of silently targeting the
        wrong UAV.
        """
        if self._uav_ids is None:
            raise RuntimeError(
                "controller_for requires uav_ids to be set at construction"
            )
        if not self._controllers:
            raise RuntimeError("controller_for called before start()")
        try:
            idx = self._uav_ids.index(uav_id)
        except ValueError:
            raise KeyError(f"unknown uav_id: {uav_id!r}")
        return self._controllers[idx]

    def param_writer_for(self, uav_id: str) -> Optional[ParamWriter]:
        """Lend this UAV's live MAVSDK connection as a ParamWriter.

        Returned eagerly (the writer resolves the controller lazily on
        first use), so it can be created before start(). If uav_ids
        wasn't supplied, the writer's first call raises a clear error
        via controller_for rather than silently no-op'ing.
        """
        return MissionParamWriter(self, uav_id)

    def loiter_runner_for(self, uav_id: str, *, main_loop=None) -> MavsdkRunner:
        """Lend this UAV's live connection as a loiter MavsdkRunner.

        `main_loop` is the event loop that owns the mission MAVSDK
        connection; when recovery calls set_loiter from another loop/
        thread, the runner bridges hold() back onto it. Same lazy-resolve
        contract as param_writer_for.
        """
        return MissionLoiterRunner(self, uav_id, main_loop=main_loop)

    async def start(self) -> None:
        """Connect all, takeoff, upload, start — fully in parallel."""
        if self._started:
            raise RuntimeError("already started")

        # Build controllers
        self._controllers = [self._factory(ep) for ep in self._endpoints]

        # Phase 1: connect everyone in parallel
        await asyncio.gather(*(c.connect() for c in self._controllers))

        # Phase 2: arm + takeoff in parallel
        await asyncio.gather(
            *(
                c.arm_and_takeoff(altitude_m=self._takeoff_alt)
                for c in self._controllers
            )
        )

        # Phase 3: convert NED → GPS per controller's home, upload, start
        async def _per_controller_setup(c: DroneController) -> None:
            # home_alt is unused for waypoint altitude (MAVSDK takes
            # home-relative altitude), but get_home_position still
            # returns it; we only need lat/lon for the NED→GPS conversion.
            home_lat, home_lon, _home_alt = await c.get_home_position()
            items = [
                ned_to_gps(
                    home_lat=home_lat,
                    home_lon=home_lon,
                    north_m=wp.north_m,
                    east_m=wp.east_m,
                    alt_m=wp.alt_m,
                )
                for wp in self._waypoints
            ]
            await c.upload_mission(items)
            await c.start_mission()

        await asyncio.gather(
            *(_per_controller_setup(c) for c in self._controllers)
        )

        self._started = True

    async def wait_until_complete(self, timeout_sec: float) -> bool:
        if not self._started:
            return True
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            statuses = await asyncio.gather(
                *(c.is_mission_complete() for c in self._controllers),
                return_exceptions=True,
            )
            # If everyone reports complete (and didn't raise), we're done.
            if all(s is True for s in statuses):
                return True
            await asyncio.sleep(self._poll_period)
        return False

    async def abort(self) -> None:
        # Best-effort RTL all, then disconnect all. Each operation is
        # wrapped to not let one controller's failure stop the others.
        async def _safe_rtl(c: DroneController) -> None:
            try:
                await c.return_to_launch()
            except Exception:
                pass

        async def _safe_disconnect(c: DroneController) -> None:
            try:
                await c.disconnect()
            except Exception:
                pass

        if self._controllers:
            await asyncio.gather(*(_safe_rtl(c) for c in self._controllers))
            await asyncio.gather(
                *(_safe_disconnect(c) for c in self._controllers)
            )
        self._started = False
