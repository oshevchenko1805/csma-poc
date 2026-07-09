#!/usr/bin/env python3
"""
test_gps_offset_inflight.py — standalone mechanism test for step 10e.

Question it answers (and ONLY this):
    Does setting SIM_GPS_OFF_N on a FLYING PX4 instance produce a
    sustained ESTIMATOR_STATUS.pos_horiz_ratio > 1.0 (the spoofing
    signature GpsSpoofingDetector fires on)?

Deliberately decoupled from the production stack:
  - single PX4 instance (inst 0, port 14540), NO mavlink-router
  - NO mission pipeline, NO MAVSDK, NO gRPC
  - one pymavlink socket does everything: arm -> takeoff -> inject
    -> read ratio -> restore
  => blocker B (router param routing) is structurally out of scope.

Run (on the VM, venv active), AFTER `scripts/launch_px4.sh` has all
3 instances up and inst 0 is armable:

    python test_gps_offset_inflight.py            # offset=50 m, monitor 90 s
    python test_gps_offset_inflight.py --offset 80 --monitor-sec 120

MANDATORY: the script always restores SIM_GPS_OFF_N=0 at the end
(and on Ctrl-C / error), per the per-instance parameters.bson
pollution lesson. If it dies uncleanly, manually verify:
    (in a fresh script) param read SIM_GPS_OFF_N  -> must be 0.0
or clean rootfs/{0,1,2}/parameters*.bson after killing all procs.
"""

from __future__ import annotations

import argparse
import math
import sys
import threading
import time

from pymavlink import mavutil

PARAM = b"SIM_GPS_OFF_N"
CONN = "udpin:0.0.0.0:14540"  # inst 0, direct (no router bound here)
ESTIMATOR_STATUS_ID = 230
GLOBAL_POSITION_INT_ID = 33


def log(msg: str) -> None:
    print(f"[test] {msg}", flush=True)


def ack_result_name(res: int) -> str:
    names = {
        0: "ACCEPTED", 1: "TEMPORARILY_REJECTED", 2: "DENIED",
        3: "UNSUPPORTED", 4: "FAILED", 5: "IN_PROGRESS",
    }
    return names.get(res, f"result={res}")


SEVERITY = {0: "EMERG", 1: "ALERT", 2: "CRIT", 3: "ERR",
            4: "WARN", 5: "NOTICE", 6: "INFO", 7: "DEBUG"}


def drain_statustext(m) -> None:
    """Print any pending STATUSTEXT — PX4's arm/prearm rejection reasons."""
    while True:
        st = m.recv_match(type="STATUSTEXT", blocking=False)
        if st is None:
            return
        txt = st.text if isinstance(st.text, str) else st.text.decode(errors="replace")
        log(f"  PX4[{SEVERITY.get(st.severity, st.severity)}]: {txt}")


def request_message_interval(m, msg_id: int, hz: float) -> None:
    interval_us = int(1e6 / hz)
    m.mav.command_long_send(
        m.target_system, m.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
        msg_id, interval_us, 0, 0, 0, 0, 0,
    )


def wait_command_ack(m, cmd: int, timeout: float = 5.0):
    """Wait for COMMAND_ACK of `cmd`, printing any STATUSTEXT seen meanwhile."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        msg = m.recv_match(blocking=True, timeout=0.5)
        if msg is None:
            continue
        t = msg.get_type()
        if t == "STATUSTEXT":
            txt = msg.text if isinstance(msg.text, str) else msg.text.decode(errors="replace")
            log(f"  PX4[{SEVERITY.get(msg.severity, msg.severity)}]: {txt}")
        elif t == "COMMAND_ACK" and msg.command == cmd:
            return msg
    return None


def _heartbeat_loop(m, stop_evt: threading.Event) -> None:
    """Announce ourselves as a GCS at 1 Hz so PX4 keeps datalink 'up'.
    Without this PX4 treats the link as lost and refuses to arm
    (persistent TEMPORARILY_REJECTED)."""
    while not stop_evt.is_set():
        try:
            m.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_GCS,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                0, 0, 0,
            )
        except Exception:
            pass
        stop_evt.wait(1.0)


def read_ratio(m, timeout: float = 3.0):
    """Return (pos_horiz_ratio, vel_ratio, pos_vert_ratio) or None."""
    msg = m.recv_match(type="ESTIMATOR_STATUS", blocking=True, timeout=timeout)
    if msg is None:
        return None
    return (msg.pos_horiz_ratio, msg.vel_ratio, msg.pos_vert_ratio)


def read_rel_alt(m, timeout: float = 2.0):
    msg = m.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=timeout)
    if msg is None:
        return None
    return msg.relative_alt / 1000.0  # mm -> m


def set_param(m, name: bytes, value: float) -> None:
    m.mav.param_set_send(
        m.target_system, m.target_component, name,
        float(value), mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
    )


def read_param(m, name: bytes, timeout: float = 3.0):
    m.mav.param_request_read_send(m.target_system, m.target_component, name, -1)
    t0 = time.time()
    while time.time() - t0 < timeout:
        pv = m.recv_match(type="PARAM_VALUE", blocking=True, timeout=timeout)
        if pv and pv.param_id.strip("\x00") == name.decode():
            return pv.param_value
    return None


def restore_offset(m) -> None:
    log(f"RESTORE: setting {PARAM.decode()}=0 ...")
    for _ in range(3):
        set_param(m, PARAM, 0.0)
        time.sleep(0.5)
        v = read_param(m, PARAM)
        if v is not None and abs(v) < 1e-6:
            log(f"RESTORE ok: {PARAM.decode()}={v}")
            return
    log(f"RESTORE WARNING: readback={v!r} (verify manually / clean bson!)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offset", type=float, default=50.0,
                    help="SIM_GPS_OFF_N target, metres north (default 50)")
    ap.add_argument("--alt", type=float, default=20.0,
                    help="takeoff altitude, metres (default 20)")
    ap.add_argument("--monitor-sec", type=float, default=90.0,
                    help="how long to watch ratio after injection (default 90)")
    ap.add_argument("--ekf-wait-sec", type=float, default=90.0,
                    help="max wait for EKF horizontal fusion before arming")
    ap.add_argument("--arm-wait-sec", type=float, default=60.0,
                    help="max wait/retry window for arm to be accepted")
    args = ap.parse_args()

    log(f"connecting {CONN} ...")
    m = mavutil.mavlink_connection(CONN)
    m.wait_heartbeat()
    log(f"heartbeat: sysid={m.target_system} comp={m.target_component}")
    if m.target_component == 0:
        m.target_component = 1
        log("target_component forced to 1 (PX4 autopilot)")

    # Announce ourselves as a GCS so PX4 keeps the datalink 'up' — required
    # for arming (MAVSDK does this implicitly).
    stop_hb = threading.Event()
    hb_thread = threading.Thread(target=_heartbeat_loop, args=(m, stop_hb), daemon=True)
    hb_thread.start()
    log("heartbeat sender started (GCS, 1 Hz)")

    request_message_interval(m, ESTIMATOR_STATUS_ID, 2.0)
    request_message_interval(m, GLOBAL_POSITION_INT_ID, 5.0)
    time.sleep(1.0)

    # --- wait for EKF to fuse horizontal position (ratio becomes finite) ---
    log("waiting for EKF horizontal fusion (finite pos_horiz_ratio)...")
    t0 = time.time()
    ekf_ready = False
    while time.time() - t0 < args.ekf_wait_sec:
        r = read_ratio(m)
        if r is None:
            log("  (no ESTIMATOR_STATUS yet)")
            continue
        ph = r[0]
        finite = ph == ph and not math.isinf(ph)  # not nan/inf
        log(f"  pos_horiz_ratio={ph:.3f}  finite={finite}")
        if finite and ph < 1.0:
            ekf_ready = True
            break
    if not ekf_ready:
        log("ABORT: EKF never reported a healthy finite ratio. "
            "Is inst 0 armable? (check /tmp/px4_inst_0.log)")
        return 2

    try:
        # --- arm (retry: TEMPORARILY_REJECTED = prearm not ready yet) ---
        log("arming (waiting for prearm checks to pass)...")
        armed = False
        attempt = 0
        t0 = time.time()
        while time.time() - t0 < args.arm_wait_sec:
            attempt += 1
            drain_statustext(m)
            m.mav.command_long_send(
                m.target_system, m.target_component,
                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0,
                1, 0, 0, 0, 0, 0, 0,
            )
            ack = wait_command_ack(
                m, mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, timeout=3.0)
            res = ack_result_name(ack.result) if ack else "NO ACK"
            log(f"  arm attempt {attempt}: {res}")
            drain_statustext(m)
            if ack and ack.result == 0:
                armed = True
                break
            time.sleep(3.0)
        if not armed:
            log("ABORT: arm never accepted within window. See PX4[...] lines "
                "above for the prearm reason.")
            restore_offset(m)
            return 3
        log("ARMED")

        # --- takeoff ---
        log(f"takeoff to {args.alt} m...")
        m.mav.command_long_send(
            m.target_system, m.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0,
            0, 0, 0, float("nan"), 0, 0, args.alt,
        )
        ack = wait_command_ack(m, mavutil.mavlink.MAV_CMD_NAV_TAKEOFF)
        log(f"takeoff ACK: {ack_result_name(ack.result) if ack else 'NO ACK'}")
        if not ack or ack.result not in (0, 5):  # ACCEPTED or IN_PROGRESS
            log("ABORT: takeoff rejected. See ACK above.")
            restore_offset(m)
            return 4

        # --- wait until airborne ---
        log("climbing...")
        t0 = time.time()
        while time.time() - t0 < 40:
            alt = read_rel_alt(m)
            if alt is not None:
                log(f"  rel_alt={alt:.1f} m")
                if alt >= args.alt * 0.9:
                    break
        log("reached target altitude (or timed out); holding 8 s for stable hover")
        time.sleep(8)

        # --- baseline ratio ---
        log("=== BASELINE (no offset) ===")
        for _ in range(6):
            r = read_ratio(m)
            if r:
                log(f"  pos_h={r[0]:.3f} vel={r[1]:.3f} pos_v={r[2]:.3f}")

        # --- INJECT ---
        log(f"=== INJECT {PARAM.decode()}={args.offset} m ===")
        set_param(m, PARAM, args.offset)
        time.sleep(0.5)
        rb = read_param(m, PARAM)
        log(f"  param readback: {PARAM.decode()}={rb}")

        # --- monitor ---
        log(f"=== MONITOR {args.monitor_sec:.0f}s (threshold=1.0, sustained=3) ===")
        consec = 0
        breached_at = None
        t0 = time.time()
        while time.time() - t0 < args.monitor_sec:
            r = read_ratio(m)
            if r is None:
                continue
            ph = r[0]
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

        # --- verdict ---
        log("=== VERDICT ===")
        if breached_at is not None:
            log(f"MECHANISM CONFIRMED: pos_horiz_ratio sustained >1.0 at "
                f"t+{breached_at:.1f}s after injection. GZBridge patch works "
                f"in flight.")
        else:
            log("MECHANISM NOT CONFIRMED: ratio never sustained >1.0. "
                "Either offset too small (retry --offset larger), ramp too "
                "slow (SIM_GPS_OFF_R), or patch not applied to running "
                "binary. Check /tmp/px4_inst_0.log for OFFSET_INJECT.")

    finally:
        # --- ALWAYS restore, then try to land+disarm ---
        restore_offset(m)
        log("landing...")
        m.mav.command_long_send(
            m.target_system, m.target_component,
            mavutil.mavlink.MAV_CMD_NAV_LAND, 0, 0, 0, 0, 0, 0, 0, 0,
        )
        time.sleep(2)
        stop_hb.set()

    return 0 if breached_at is not None else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("interrupted — attempting offset restore is NOT possible here "
            "(connection may be mid-op). If script was past INJECT, run a "
            "one-liner to set SIM_GPS_OFF_N=0 or clean the bson.")
        sys.exit(130)
