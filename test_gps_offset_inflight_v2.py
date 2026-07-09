#!/usr/bin/env python3
"""
test_gps_offset_inflight_v2.py — step 10e in-flight mechanism test.

Answers ONLY: does setting SIM_GPS_OFF_N on a flying PX4 produce a
sustained ESTIMATOR_STATUS.pos_horiz_ratio > 1.0?

Why this design (v2):
  - v1 (pure pymavlink) hit "Arming denied: system health failures" —
    raw arm doesn't wait through PX4's prearm the way MAVSDK does.
  - MAVSDK arm/takeoff/param is the PROVEN path (repo baseline flies).
  - But mavsdk-python 3.15.3 has NO mavlink_passthrough, so it cannot
    read ESTIMATOR_STATUS.pos_horiz_ratio.
  => Split channels through the EXISTING router fan-out on inst 0:
        PX4 14540 --router--> 14560 (MAVSDK: fly + param)
                          \--> 14570 (pymavlink: read ratio)
     Both are existing 3-endpoint config ports — no new endpoint, so
     blocker B (mission param routing) is NOT in scope. Only ONE
     drone flies here.

Run order (VM, venv):
    ./scripts/kill_router.sh ; ./scripts/kill_px4.sh
    ./scripts/launch_px4.sh
    ./scripts/launch_router.sh
    python test_gps_offset_inflight_v2.py            # offset 50 m, monitor 90 s
    python test_gps_offset_inflight_v2.py --offset 80 --monitor-sec 120

ALWAYS restores SIM_GPS_OFF_N=0 (finally block). If it dies uncleanly
after INJECT, manually zero the param or clean rootfs/*/parameters*.bson
after killing procs (per-instance storage pollution lesson).
"""

from __future__ import annotations

import argparse
import asyncio
import math
import threading
import time

from pymavlink import mavutil
from mavsdk import System

PARAM = "SIM_GPS_OFF_N"
MAVSDK_ADDR = "udpin://0.0.0.0:14560"   # router MAVSDK fan-out, inst 0
MAVSDK_GRPC = 50051
PYMAVLINK_CONN = "udpin:0.0.0.0:14570"  # router Monitor fan-out, inst 0
ESTIMATOR_STATUS_ID = 230


def log(msg: str) -> None:
    print(f"[test] {msg}", flush=True)


# ---------------------------------------------------------------------------
# pymavlink ratio reader (background thread) — reads ESTIMATOR_STATUS only
# ---------------------------------------------------------------------------
class RatioReader(threading.Thread):
    def __init__(self, conn: str):
        super().__init__(daemon=True)
        self._conn = conn
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.samples: list[tuple[float, float, float, float]] = []
        self.ready = threading.Event()

    def run(self) -> None:
        m = mavutil.mavlink_connection(self._conn)
        m.wait_heartbeat()
        if m.target_component == 0:
            m.target_component = 1
        # bump ESTIMATOR_STATUS to 2 Hz on this link
        m.mav.command_long_send(
            m.target_system, m.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
            ESTIMATOR_STATUS_ID, 500000, 0, 0, 0, 0, 0,
        )
        self.ready.set()
        while not self._stop.is_set():
            msg = m.recv_match(type="ESTIMATOR_STATUS", blocking=True, timeout=1.0)
            if msg is None:
                continue
            with self._lock:
                self.samples.append(
                    (time.time(), msg.pos_horiz_ratio, msg.vel_ratio, msg.pos_vert_ratio)
                )

    def snapshot(self):
        with self._lock:
            return list(self.samples)

    def stop(self):
        self._stop.set()


# ---------------------------------------------------------------------------
# MAVSDK flight helpers
# ---------------------------------------------------------------------------
async def wait_armable(drone: System, timeout: float) -> bool:
    log("waiting for is_armable (MAVSDK health)...")
    t0 = time.time()
    async for health in drone.telemetry.health():
        if health.is_armable:
            log("is_armable=True")
            return True
        if time.time() - t0 > timeout:
            log(f"  still not armable: gyro={health.is_gyrometer_calibration_ok} "
                f"accel={health.is_accelerometer_calibration_ok} "
                f"mag={health.is_magnetometer_calibration_ok} "
                f"local_pos={health.is_local_position_ok} "
                f"global_pos={health.is_global_position_ok} "
                f"home={health.is_home_position_ok}")
            return False
    return False


async def latest_pos_h(reader: RatioReader) -> float | None:
    s = reader.snapshot()
    return s[-1][1] if s else None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offset", type=float, default=50.0)
    ap.add_argument("--alt", type=float, default=20.0)
    ap.add_argument("--monitor-sec", type=float, default=90.0)
    ap.add_argument("--armable-timeout", type=float, default=90.0)
    args = ap.parse_args()

    # start ratio reader
    reader = RatioReader(PYMAVLINK_CONN)
    reader.start()
    log(f"pymavlink ratio reader starting on {PYMAVLINK_CONN} ...")
    if not reader.ready.wait(timeout=30):
        log("ABORT: ratio reader never got a heartbeat on 14570. "
            "Is the router up? (ss -ulnp | grep 1457)")
        return 2
    log("ratio reader ready")

    # connect MAVSDK
    log(f"MAVSDK connecting {MAVSDK_ADDR} (grpc {MAVSDK_GRPC}) ...")
    drone = System(port=MAVSDK_GRPC)
    await drone.connect(system_address=MAVSDK_ADDR)
    async for state in drone.core.connection_state():
        if state.is_connected:
            log("MAVSDK connected")
            break

    if not await wait_armable(drone, args.armable_timeout):
        log("ABORT: not armable within timeout (see health flags above).")
        reader.stop()
        return 3

    breached_at = None
    try:
        log(f"set_takeoff_altitude({args.alt})")
        await drone.action.set_takeoff_altitude(args.alt)
        log("arm...")
        await drone.action.arm()
        log("takeoff...")
        await drone.action.takeoff()

        # climb
        log("climbing...")
        t0 = time.time()
        async for pos in drone.telemetry.position():
            log(f"  rel_alt={pos.relative_altitude_m:.1f} m")
            if pos.relative_altitude_m >= args.alt * 0.9 or time.time() - t0 > 40:
                break
        log("holding 8 s for stable hover")
        await asyncio.sleep(8)

        # baseline
        log("=== BASELINE (no offset) ===")
        base = reader.snapshot()[-6:]
        for (_, ph, vel, pv) in base:
            log(f"  pos_h={ph:.3f} vel={vel:.3f} pos_v={pv:.3f}")

        # inject
        log(f"=== INJECT {PARAM}={args.offset} m (via MAVSDK param) ===")
        await drone.param.set_param_float(PARAM, args.offset)
        rb = await drone.param.get_param_float(PARAM)
        log(f"  param readback: {PARAM}={rb}")

        # monitor
        log(f"=== MONITOR {args.monitor_sec:.0f}s (threshold=1.0, sustained=3) ===")
        start_len = len(reader.snapshot())
        t0 = time.time()
        consec = 0
        seen = start_len
        while time.time() - t0 < args.monitor_sec:
            s = reader.snapshot()
            for (ts, ph, vel, pv) in s[seen:]:
                elapsed = time.time() - t0
                if ph > 1.0:
                    consec += 1
                else:
                    consec = 0
                flag = ""
                if consec >= 3 and breached_at is None:
                    breached_at = elapsed
                    flag = "  <<< DETECTED (3 sustained >1.0)"
                log(f"  t+{elapsed:5.1f}s  pos_h={ph:6.3f}  consec={consec}{flag}")
            seen = len(s)
            await asyncio.sleep(0.5)

        log("=== VERDICT ===")
        if breached_at is not None:
            log(f"MECHANISM CONFIRMED: pos_horiz_ratio sustained >1.0 at "
                f"t+{breached_at:.1f}s. GZBridge patch works in flight.")
        else:
            log("MECHANISM NOT CONFIRMED: ratio never sustained >1.0. "
                "Try --offset 80/120; check ramp SIM_GPS_OFF_R; verify "
                "OFFSET_INJECT is in the running binary.")

    finally:
        # ALWAYS restore
        log(f"RESTORE: {PARAM}=0 ...")
        try:
            await drone.param.set_param_float(PARAM, 0.0)
            rb = await drone.param.get_param_float(PARAM)
            log(f"RESTORE readback: {PARAM}={rb}")
        except Exception as e:
            log(f"RESTORE ERROR: {e!r} — zero it manually / clean bson!")
        log("landing...")
        try:
            await drone.action.land()
        except Exception:
            pass
        reader.stop()

    return 0 if breached_at is not None else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

