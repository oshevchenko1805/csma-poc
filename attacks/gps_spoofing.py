"""
gps_spoofing — EKF residual divergence via PX4 SITL param manipulation.

Approximates a GPS spoofing attack by setting a PX4 SITL simulator
parameter (default: SIM_GPS_NOISE) to an extreme value, which causes
the autopilot's EKF position-horizontal residual to diverge. The
GpsSpoofingDetector flags `pos_horiz_ratio > 1.0` sustained over
3 samples and reports the anomaly.

Why this approach
-----------------
The dissertation evaluates the *detection and recovery pipeline*, not
the cryptography of RF GPS spoofing. Parameter manipulation gives a
reproducible, instantaneous EKF residual signature that exercises the
same detector code path that a real RF spoofer would trigger. The
attack mechanism is acknowledged as approximation in Chapter 4; the
*observed pipeline behaviour* is the contribution.

Alternative attack mechanisms (ranked by realism / difficulty)
--------------------------------------------------------------
1. SIM_GPS_NOISE bump (this implementation) — reproducible, deterministic,
   easy. Loss of realism: doesn't model selective falsification.
2. HIL_GPS message injection on MAVLink — more realistic but requires
   disabling the simulated GPS source first; brittle across PX4 versions.
3. Gazebo plugin manipulation — most realistic (in-simulation RF), but
   requires Gazebo-side code and is hard to script reliably.

Option 1 is the default; the others would be future work for a
follow-up dissertation chapter.

PoC caveat (Chapter 4)
----------------------
MTTD floor for this attack is bounded by PX4's ESTIMATOR_STATUS stream
rate (1 Hz) and the detector's 3-sample sustained-anomaly requirement.
Floor ≈ 3 seconds, documented as a tool limitation rather than an
architecture limitation. See PROJECT_STATE.md section 9 (PoC
simplifications) for full discussion.

DI seam
-------
GpsSpoofingRunner abstracts MAVSDK Param API. Tests pass a fake;
production uses DefaultGpsSpoofingRunner (lazy mavsdk import).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Union

from attacks.base import AttackContext, AttackInjector


# A param value can be an int or a float. We dispatch in the runner.
ParamValue = Union[int, float]


# ---------------------------------------------------------------------------
# DI seam
# ---------------------------------------------------------------------------


class GpsSpoofingRunner(ABC):
    """Abstract MAVSDK Param interface for spoof / restore."""

    @abstractmethod
    async def get_param(
        self, *, mavsdk_endpoint: str, param_name: str
    ) -> ParamValue:
        """Read current value (int or float per PX4 convention)."""

    @abstractmethod
    async def set_param(
        self,
        *,
        mavsdk_endpoint: str,
        param_name: str,
        value: ParamValue,
    ) -> None:
        """Write the value. Raises on failure."""

    @abstractmethod
    async def close(self) -> None:
        """Release any held MAVSDK connections. Idempotent."""


class DefaultGpsSpoofingRunner(GpsSpoofingRunner):
    """Real MAVSDK-driven param runner. Lazy import so tests don't
    pay the cost of importing mavsdk.

    A short-lived MAVSDK System is created per call. This adds ~1 s
    of overhead per operation (connect + handshake) which is acceptable
    for a PoC where the injector is called only at arm/fire/cleanup —
    three times per run, not a hot path.

    gRPC port (step 10c)
    --------------------
    mavsdk.System(port=N) spawns a local mavsdk_server subprocess on
    gRPC port N (default 50051). When the injector runs concurrently
    with three MavsdkDroneControllers driving the mission (50051-50053)
    and per-UAV loiter handlers (50054-50056), it needs its own gRPC
    port to avoid `AioRpcError: Socket closed`. Pass `grpc_port=50057`
    in the construction path from run_one.py; default `None` preserves
    legacy `System()` for tests injecting FakeGpsSpoofingRunner.

    Note on the UDP endpoint (separate concern, step-10c follow-up):
    the injector currently constructs `udp://127.0.0.1:14540+i` as the
    MAVSDK system address. Post-router-topology (step 10b) that port
    is bound by mavlink-routerd as a UDP Server; MAVSDK opening
    `udpin` on the same port will collide. This is a UDP-layer
    problem, distinct from gRPC port collision, and will be addressed
    when `--attack gps_spoofing` is run end-to-end against the live
    PX4 SITL fleet.
    """

    DEFAULT_TIMEOUT_SEC: float = 5.0

    def __init__(
        self,
        *,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        grpc_port: Optional[int] = None,
    ) -> None:
        if timeout_sec <= 0:
            raise ValueError("timeout_sec must be positive")
        self._timeout = timeout_sec
        self._grpc_port = grpc_port

    @property
    def grpc_port(self) -> Optional[int]:
        return self._grpc_port

    async def _connect(self, endpoint: str):
        import asyncio

        from mavsdk import System  # lazy

        drone = (
            System(port=self._grpc_port)
            if self._grpc_port is not None
            else System()
        )
        await asyncio.wait_for(
            drone.connect(system_address=endpoint), timeout=self._timeout
        )
        # Wait for connection to actually establish.
        async for state in drone.core.connection_state():
            if state.is_connected:
                break
        return drone

    async def get_param(
        self, *, mavsdk_endpoint: str, param_name: str
    ) -> ParamValue:
        import asyncio

        drone = await self._connect(mavsdk_endpoint)
        # Try float first; if PX4 says wrong type, retry as int.
        try:
            return await asyncio.wait_for(
                drone.param.get_param_float(param_name),
                timeout=self._timeout,
            )
        except Exception:
            return await asyncio.wait_for(
                drone.param.get_param_int(param_name),
                timeout=self._timeout,
            )

    async def set_param(
        self,
        *,
        mavsdk_endpoint: str,
        param_name: str,
        value: ParamValue,
    ) -> None:
        import asyncio

        drone = await self._connect(mavsdk_endpoint)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"unsupported param value type: {type(value).__name__}")
        if isinstance(value, int):
            await asyncio.wait_for(
                drone.param.set_param_int(param_name, value),
                timeout=self._timeout,
            )
        else:
            await asyncio.wait_for(
                drone.param.set_param_float(param_name, float(value)),
                timeout=self._timeout,
            )

    async def close(self) -> None:
        # MAVSDK System is short-lived per call; nothing to clean up
        # explicitly. Method exists for symmetry with other runners.
        return None


# ---------------------------------------------------------------------------
# Injector
# ---------------------------------------------------------------------------


class GpsSpoofingInjector(AttackInjector):
    """Set a SITL GPS parameter to an extreme value to spoof EKF state."""

    name_: str = "gps_spoofing"

    DEFAULT_PARAM_NAME: str = "SIM_GPS_NOISE"
    """Default param. Real PX4 SITL exposes this as a float (m std-dev)."""

    DEFAULT_SPOOFED_VALUE: float = 100.0
    """Large noise std-dev (in metres) — far above what EKF tolerates."""

    DEFAULT_PORT_BASE: int = 14540

    def __init__(
        self,
        *,
        runner: Optional[GpsSpoofingRunner] = None,
        param_name: str = DEFAULT_PARAM_NAME,
        spoofed_value: ParamValue = DEFAULT_SPOOFED_VALUE,
        explicit_endpoint: Optional[str] = None,
        port_base: int = DEFAULT_PORT_BASE,
        restore_value: Optional[ParamValue] = None,
    ) -> None:
        if not param_name:
            raise ValueError("param_name must be non-empty")
        if isinstance(spoofed_value, bool):
            raise TypeError("spoofed_value cannot be bool")
        if not isinstance(spoofed_value, (int, float)):
            raise TypeError("spoofed_value must be int or float")

        self._runner: GpsSpoofingRunner = runner or DefaultGpsSpoofingRunner()
        self._param_name = param_name
        self._spoofed_value = spoofed_value
        self._explicit_endpoint = explicit_endpoint
        self._port_base = port_base
        self._restore_value = restore_value  # if None, captured during arm

        self._target_endpoint: Optional[str] = None
        self._armed: bool = False
        self._fired: bool = False
        self._original_value: Optional[ParamValue] = None

    @property
    def name(self) -> str:
        return self.name_

    @property
    def target_endpoint(self) -> Optional[str]:
        return self._target_endpoint

    @property
    def original_value(self) -> Optional[ParamValue]:
        return self._original_value

    async def arm(self, ctx: AttackContext) -> None:
        if self._explicit_endpoint is not None:
            self._target_endpoint = self._explicit_endpoint
        else:
            port = self._port_base + (ctx.target_sysid - 1)
            self._target_endpoint = f"udp://127.0.0.1:{port}"

        # Capture the value we'll restore on cleanup.
        if self._restore_value is not None:
            self._original_value = self._restore_value
        else:
            try:
                self._original_value = await self._runner.get_param(
                    mavsdk_endpoint=self._target_endpoint,
                    param_name=self._param_name,
                )
            except Exception:
                # If reading fails, fall back to a safe default. The
                # PX4 SITL default for SIM_GPS_NOISE is "small"; using
                # 0 puts the simulator into a clean state — possibly
                # different from the experiment's starting state, but
                # not dangerous. Document in Ch. 4 if needed.
                self._original_value = (
                    0 if isinstance(self._spoofed_value, int) else 0.0
                )

        self._armed = True

    async def fire(self) -> None:
        if not self._armed:
            raise RuntimeError("fire() called before arm()")
        assert self._target_endpoint is not None
        await self._runner.set_param(
            mavsdk_endpoint=self._target_endpoint,
            param_name=self._param_name,
            value=self._spoofed_value,
        )
        self._fired = True

    async def cleanup(self) -> None:
        # Restore even if fire never ran — the runner's set_param is
        # idempotent at the PX4 level (writing the same value is a no-op).
        if self._armed and self._original_value is not None:
            try:
                assert self._target_endpoint is not None
                await self._runner.set_param(
                    mavsdk_endpoint=self._target_endpoint,
                    param_name=self._param_name,
                    value=self._original_value,
                )
            except Exception:
                pass
        try:
            await self._runner.close()
        except Exception:
            pass
