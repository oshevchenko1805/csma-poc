"""
gps_spoofing — EKF residual divergence via PX4 SITL GPS-offset injection.

Approximates a GPS spoofing attack by setting a PX4 SITL simulator
parameter (SIM_GPS_OFF_N — a horizontal north GPS position offset, in
metres, exposed by a local GZBridge patch) to a non-zero value while the
UAV is flying. The offset drags the reported GPS position away from
truth, driving the autopilot's EKF position-horizontal residual up:
ESTIMATOR_STATUS.pos_horiz_ratio ramps above 1.0. The GpsSpoofingDetector
flags `pos_horiz_ratio > 1.0` sustained over 3 samples.

Verified in flight (step 10e)
-----------------------------
Hover @ 20 m: baseline pos_horiz_ratio ~0.006 → SIM_GPS_OFF_N = 50 →
ratio ramps, clips at 2.0 over ~7 s → detector fires at +1.5 s (2 Hz).
On restore (OFF_N = 0) ratio returns to baseline. The detected signature
is the *onset transient of the ramp*, not a stationary offset — the EKF
re-converges around the biased position after a few seconds. Reported
honestly for Chapters 4/5: detection happens during divergence, not at
steady state.

Param channel (step 10e)
------------------------
During flight the mission MAVSDK connection owns the target's UDP
fan-out port; a second MAVSDK client cannot attach (bind conflict), and
raw pymavlink PARAM_SET does not route to PX4 through the router. The
only channel that reaches PX4 params mid-flight is the *live mission
connection*. So this injector does not open its own connection: the
experiment layer hands it a `ParamWriter` (backed by the mission
controller for the target UAV) via `AttackContext.param_writer`. See
runners/mission_mavsdk.py::MissionParamWriter.

Timing
------
arm() runs before the mission starts, so no controller exists yet and
the param cannot be read. Therefore the pre-attack value is captured in
fire() (mission flying, controller live), immediately before the spoof
is applied; cleanup() restores it.

Restore discipline
------------------
The offset persists in per-instance SITL param storage, so it MUST be
restored or it leaks into the next run's baseline. fire() reads the real
pre-attack value and cleanup() writes it back. If the read fails, we
fall back to `restore_value` (default 0.0 — the patched OFF_N default),
so a transient read error can't strand a non-zero offset.

Why this approach
-----------------
The dissertation evaluates the detection/recovery pipeline, not RF GPS
cryptography. Offset injection gives a reproducible EKF residual that
exercises the same detector path a real spoofer would trigger; it is
acknowledged as an approximation in Chapter 4.
"""

from __future__ import annotations

from typing import Optional

from attacks.base import AttackContext, AttackInjector


class GpsSpoofingInjector(AttackInjector):
    """Inject a horizontal GPS position offset (SIM_GPS_OFF_N) mid-flight
    through the mission-provided ParamWriter to drive the EKF horizontal
    residual above threshold."""

    name_: str = "gps_spoofing"

    DEFAULT_PARAM_NAME: str = "SIM_GPS_OFF_N"
    """GZBridge-patched param: north GPS position offset in metres."""

    DEFAULT_SPOOFED_VALUE: float = 50.0
    """Offset (m) large enough to ramp pos_horiz_ratio well past 1.0."""

    DEFAULT_RESTORE_VALUE: float = 0.0
    """Fallback restore target if the pre-attack read fails. 0.0 = the
    patched OFF_N default (no offset)."""

    def __init__(
        self,
        *,
        param_name: str = DEFAULT_PARAM_NAME,
        spoofed_value: float = DEFAULT_SPOOFED_VALUE,
        restore_value: Optional[float] = None,
    ) -> None:
        if not param_name:
            raise ValueError("param_name must be non-empty")
        if isinstance(spoofed_value, bool):
            raise TypeError("spoofed_value cannot be bool")
        if not isinstance(spoofed_value, (int, float)):
            raise TypeError("spoofed_value must be int or float")

        self._param_name = param_name
        self._spoofed_value = float(spoofed_value)
        # If set, skip the pre-attack read and restore to this value.
        self._restore_value = (
            float(restore_value) if restore_value is not None else None
        )

        self._param_writer = None  # set in arm() from ctx
        self._armed: bool = False
        self._fired: bool = False
        self._original_value: Optional[float] = None

    @property
    def name(self) -> str:
        return self.name_

    @property
    def original_value(self) -> Optional[float]:
        return self._original_value

    async def arm(self, ctx: AttackContext) -> None:
        # Grab the param channel the experiment layer provided. It may be
        # None (e.g. NullMissionRunner); we don't fail here so arm-time
        # resource checks stay decoupled from whether a real flight is
        # present. fire() raises loudly if it's still None.
        self._param_writer = ctx.param_writer
        self._armed = True

    async def fire(self) -> None:
        if not self._armed:
            raise RuntimeError("fire() called before arm()")
        if self._param_writer is None:
            raise RuntimeError(
                "gps_spoofing requires a param_writer, but none was provided "
                "by the mission (is this a real MAVSDK flight, not a null "
                "mission?)"
            )

        # Capture the pre-attack value to restore later (unless an explicit
        # restore_value was configured). Read failure falls back to the
        # default so a transient error can't strand a non-zero offset.
        if self._restore_value is not None:
            self._original_value = self._restore_value
        else:
            try:
                self._original_value = await self._param_writer.get_param_float(
                    self._param_name
                )
            except Exception:
                self._original_value = self.DEFAULT_RESTORE_VALUE

        await self._param_writer.set_param_float(
            self._param_name, self._spoofed_value
        )
        self._fired = True

    async def cleanup(self) -> None:
        # Only restore if we actually applied the spoof; if fire() didn't
        # complete its set, the param was never changed. Restore uses the
        # still-live mission connection (ExperimentRunner runs attack
        # cleanup before mission.abort()).
        if not self._fired or self._param_writer is None:
            return
        restore_to = (
            self._original_value
            if self._original_value is not None
            else self.DEFAULT_RESTORE_VALUE
        )
        try:
            await self._param_writer.set_param_float(
                self._param_name, restore_to
            )
        except Exception:
            pass
