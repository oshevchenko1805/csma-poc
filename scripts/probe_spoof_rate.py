#!/usr/bin/env python3
"""
B0 spoof-rate sweep (review stage 5). Rules: B0_PREREGISTRATION.md,
executable form metrics/spoof_rate_probe.py — read them before flying.

One UAV (uav_0) on the campaign route, detect-only (no response action),
no monitors / mesh / coordinator: detectors are replayed offline from the
log with the campaign classes. Nothing in the experiment pipeline is
touched.

Prerequisites before EVERY flight (SIM_GPS_OFF_R persists in bson):
  scripts/kill_px4.sh; scripts/kill_router.sh
  rm -f ~/PX4-Autopilot/build/px4_sitl_default/rootfs/{0,1,2}/parameters*.bson
  scripts/launch_px4.sh && scripts/launch_router.sh

Usage
-----
  python3 scripts/probe_spoof_rate.py --level L30          # fly one flight
  python3 scripts/probe_spoof_rate.py --analyze ~/b0_runs/L30_<unix>
  python3 scripts/probe_spoof_rate.py --report ~/b0_runs   # all flights -> decision

Output: ~/b0_runs/<level>_<unix>/ with trajectory.jsonl (Gazebo truth),
mav.jsonl (ESTIMATOR_STATUS, GPS_RAW_INT, GLOBAL_POSITION_INT,
LOCAL_POSITION_NED from the monitor endpoint 14570), meta.json,
summary.json. Raw data stays out of git.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metrics import spoof_rate_probe as B  # noqa: E402
from metrics.trust_hold_probe import read_jsonl, truth_ne  # noqa: E402

P_N, P_R = "SIM_GPS_OFF_N", "SIM_GPS_OFF_R"
MAV_TYPES = ["ESTIMATOR_STATUS", "GPS_RAW_INT", "GLOBAL_POSITION_INT",
             "LOCAL_POSITION_NED"]
KEEP = {"ESTIMATOR_STATUS": ("pos_horiz_ratio", "vel_ratio"),
        "GPS_RAW_INT": ("lat", "lon", "fix_type"),
        "GLOBAL_POSITION_INT": ("lat", "lon", "relative_alt"),
        "LOCAL_POSITION_NED": ("x", "y", "z")}
LAP_S = 36.0          # measured lap time of the campaign route (OPEN-1)
LEAD_S = 60.0         # takeoff-to-cruise margin inside the route


# --- logging -------------------------------------------------------------

def mav_logger(path: Path, endpoint: str, stop: threading.Event,
               stats: dict) -> None:
    from pymavlink import mavutil
    conn = mavutil.mavlink_connection(endpoint)
    with open(path, "w") as fh:
        while not stop.is_set():
            msg = conn.recv_match(type=MAV_TYPES, blocking=True, timeout=0.5)
            if msg is None or msg.get_srcSystem() != 1:
                continue
            typ = msg.get_type()
            d = msg.to_dict()
            rec = {"t_wall": time.time(), "type": typ}
            rec.update({k: d.get(k) for k in KEEP[typ]})
            fh.write(json.dumps(rec) + "\n")
            stats[typ] = stats.get(typ, 0) + 1
    conn.close()


async def _first(aiter, pred, timeout: float, what: str):
    async def _run():
        async for x in aiter:
            if pred(x):
                return x
    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except asyncio.TimeoutError:
        raise RuntimeError(f"timeout waiting for {what}") from None


async def _start_route(drone, laps: int, min_speed: float, lead_max: float) -> float:
    """Campaign lap pattern x `laps` (5 m/s, fly-through, 2 m acceptance);
    returns once cruising."""
    from mavsdk.mission import MissionItem as MItem, MissionPlan

    from core.config import load_experiment_config
    from runners.mission_mavsdk import ned_to_gps

    cfg = load_experiment_config(
        Path(__file__).resolve().parent.parent / "configs" / "experiment.yaml")
    home = await _first(drone.telemetry.home(), lambda h: True, 30, "home")
    wps = list(cfg.mission.lap_waypoints) * laps
    items = [
        MItem(
            latitude_deg=g.lat, longitude_deg=g.lon,
            relative_altitude_m=g.relative_alt_m, speed_m_s=5.0,
            is_fly_through=True, gimbal_pitch_deg=0.0, gimbal_yaw_deg=0.0,
            camera_action=MItem.CameraAction.NONE, loiter_time_s=0.0,
            camera_photo_interval_s=0.0, acceptance_radius_m=2.0,
            yaw_deg=float("nan"), camera_photo_distance_m=float("nan"),
            vehicle_action=MItem.VehicleAction.NONE,
        )
        for g in (
            ned_to_gps(home_lat=home.latitude_deg, home_lon=home.longitude_deg,
                       north_m=wp.north_m, east_m=wp.east_m, alt_m=wp.alt_m)
            for wp in wps
        )
    ]
    await drone.mission.upload_mission(MissionPlan(items))
    await drone.mission.start_mission()
    await asyncio.sleep(8.0)
    pv = await _first(
        drone.telemetry.position_velocity_ned(),
        lambda p: math.hypot(p.velocity.north_m_s, p.velocity.east_m_s) >= min_speed,
        lead_max, f"cruise speed >= {min_speed} m/s")
    return math.hypot(pv.velocity.north_m_s, pv.velocity.east_m_s)


async def fly(args, out: Path) -> dict:
    from mavsdk import System

    p = B.level_params(args.level)
    laps = math.ceil((p["window_s"] + LEAD_S) / LAP_S)
    meta = {"level": args.level, **p, "laps": laps, "t_inject": None,
            "readback_before": None, "readback_injected": None,
            "readback_restored": None, "speed_at_inject_mps": None,
            "error": None}

    drone = System(port=args.grpc_port)
    await drone.connect(system_address=f"udpin://0.0.0.0:{args.mavsdk_port}")
    await _first(drone.core.connection_state(), lambda s: s.is_connected,
                 30, "connection")
    n0 = await drone.param.get_param_float(P_N)
    r0 = await drone.param.get_param_float(P_R)
    meta["readback_before"] = {P_N: n0, P_R: r0}
    if abs(n0) > 1e-6 or abs(r0 - B.CAMPAIGN_R) > 1e-6:
        raise SystemExit(f"[b0] REFUSED: {P_N}={n0}, {P_R}={r0} before flight "
                         f"(expected 0 and {B.CAMPAIGN_R}). Kill PX4, clear "
                         f"parameters*.bson, relaunch.")
    await _first(drone.telemetry.health(),
                 lambda h: h.is_global_position_ok and h.is_home_position_ok
                 and h.is_local_position_ok, 120, "position health")
    try:
        await drone.action.set_takeoff_altitude(args.alt)
        await drone.action.arm()
        await drone.action.takeoff()
        await _first(drone.telemetry.position(),
                     lambda q: q.relative_altitude_m >= args.alt - 1.0,
                     60, "takeoff altitude")
        await asyncio.sleep(args.settle)
        meta["speed_at_inject_mps"] = await _start_route(
            drone, laps, args.min_speed, args.lead_max)
        print(f"[b0] {args.level}: cruising at {meta['speed_at_inject_mps']:.2f} m/s, "
              f"v0={p['v0_mps']} m/s r={p['r']:.7f} tau={p['tau_s']:.2f} s "
              f"W={p['window_s']:.0f} s")

        await drone.param.set_param_float(P_R, p["r"])      # rate BEFORE target
        meta["t_inject"] = time.time()
        await drone.param.set_param_float(P_N, B.TARGET_M)
        meta["readback_injected"] = {
            P_N: await drone.param.get_param_float(P_N),
            P_R: await drone.param.get_param_float(P_R)}
        print(f"[b0] injected {meta['readback_injected']}")

        while time.time() < meta["t_inject"] + p["window_s"]:
            await asyncio.sleep(5.0)
            print(f"[b0] +{time.time() - meta['t_inject']:.0f} s")
        print("[b0] window closed")
    except Exception as exc:
        meta["error"] = repr(exc)
        print(f"[b0] ERROR {exc!r}")
    finally:
        try:
            await drone.param.set_param_float(P_N, 0.0)
            await drone.param.set_param_float(P_R, B.CAMPAIGN_R)
            meta["readback_restored"] = {
                P_N: await drone.param.get_param_float(P_N),
                P_R: await drone.param.get_param_float(P_R)}
        except Exception as exc:
            print(f"[b0] WARNING restore failed: {exc!r}")
        try:
            await drone.action.land()
            await _first(drone.telemetry.in_air(), lambda a: not a, 120, "landing")
        except Exception as exc:
            print(f"[b0] WARNING landing: {exc!r}")
    return meta


# --- analysis ------------------------------------------------------------

def load_series(out: Path) -> dict:
    mav = read_jsonl(str(out / "mav.jsonl"))
    by = {t: [r for r in mav if r["type"] == t] for t in MAV_TYPES}
    return {
        "truth": truth_ne(read_jsonl(str(out / "trajectory.jsonl"))),
        "belief": sorted((r["t_wall"], float(r["x"]), float(r["y"]))
                         for r in by["LOCAL_POSITION_NED"]),
        "gps": sorted((r["t_wall"], r["lat"] / 1e7, r["lon"] / 1e7)
                      for r in by["GPS_RAW_INT"] if (r.get("fix_type") or 0) >= 3),
        "est": sorted((r["t_wall"], float(r["pos_horiz_ratio"]))
                      for r in by["ESTIMATOR_STATUS"]
                      if r.get("pos_horiz_ratio") is not None),
        "gpi": sorted((r["t_wall"], r["lat"] / 1e7, r["lon"] / 1e7)
                      for r in by["GLOBAL_POSITION_INT"]),
    }


def analyze(out: Path) -> dict:
    meta = json.loads((out / "meta.json").read_text())
    if meta.get("t_inject") is None:
        s = {"level": meta["level"], "class": "INVALID",
             "error": meta.get("error") or "no injection"}
    else:
        ser = load_series(out)
        s = B.summarize_flight(meta["level"], meta["t_inject"], ser["truth"],
                               ser["belief"], ser["gps"], ser["est"], ser["gpi"])
        s["class"] = B.classify_flight(s, meta.get("error"))
        s["detected_by"] = B.detected_by(s)
        s["error"] = meta.get("error")
        s["n"] = {k: len(v) for k, v in ser.items()}
    s["dir"] = out.name
    s["t_start"] = meta.get("t_inject")
    (out / "summary.json").write_text(json.dumps(s, indent=2))
    return s


def report(root: Path) -> dict:
    flights = []
    for d in sorted(root.iterdir()):
        if (d / "meta.json").exists():
            flights.append(analyze(d))
    flights.sort(key=lambda s: s.get("t_start") or 0.0)
    levels = {}
    for s in flights:
        levels.setdefault(s["level"], []).append(s)
    l30 = [s for s in levels.get("L30", []) if s["class"] != "INVALID"]
    rep = {
        "ramp_ok_first_L30": l30[0].get("ramp_ok") if l30 else None,
        "control_ok": B.control_ok(l30[:2]),
        "levels": {l: B.classify_level([s["class"] for s in ss])
                   for l, ss in levels.items()},
    }
    if not rep["ramp_ok_first_L30"]:
        rep["decision"] = "STOP: ramp check failed or no L30 flight — re-register levels"
    elif not rep["control_ok"]:
        rep["decision"] = "STOP: L30 does not reproduce the campaign (or < 2 flights)"
    else:
        rep["decision"] = B.decision(rep["levels"])
    cols = ("dir", "class", "detected_by", "t_gps_s", "t_cc_s", "t_jump_s",
            "max_step_1s_m", "nav_error_end_m", "harm_at_alarm_m",
            "spoof_at_tau_m", "ramp_ok")
    rep["flights"] = [{c: s.get(c) for c in cols} for s in flights]
    (root / "b0_report.json").write_text(json.dumps(rep, indent=2))
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--level", choices=sorted(B.LEVELS))
    ap.add_argument("--analyze", metavar="DIR")
    ap.add_argument("--report", metavar="ROOT")
    ap.add_argument("--alt", type=float, default=20.0)
    ap.add_argument("--settle", type=float, default=5.0)
    ap.add_argument("--min-speed", type=float, default=4.0)
    ap.add_argument("--lead-max", type=float, default=60.0)
    ap.add_argument("--mavsdk-port", type=int, default=14560)
    ap.add_argument("--grpc-port", type=int, default=50051)
    ap.add_argument("--mav-endpoint", default="udpin:127.0.0.1:14570")
    ap.add_argument("--out", default=os.path.expanduser("~/b0_runs"))
    a = ap.parse_args()

    if a.report:
        rep = report(Path(a.report))
        print(json.dumps(rep, indent=2))
        print(f"[b0] DECISION: {rep['decision']}")
        return 0
    if a.analyze:
        out = Path(a.analyze)
    else:
        if not a.level:
            ap.error("--level is required unless --analyze/--report is given")
        from runners.trajectory import TrajectoryRecorder
        out = Path(a.out) / f"{a.level}_{int(time.time())}"
        out.mkdir(parents=True, exist_ok=False)
        stop, stats = threading.Event(), {}
        th = threading.Thread(target=mav_logger, daemon=True,
                              args=(out / "mav.jsonl", a.mav_endpoint, stop, stats))
        th.start()
        rec = TrajectoryRecorder(out_path=out / "trajectory.jsonl")
        rec.start()
        try:
            meta = asyncio.run(fly(a, out))
        finally:
            rec.stop()
            stop.set()
            th.join(timeout=3.0)
        meta["mav_counts"] = stats
        meta["truth_samples"] = rec.stats["samples_written"]
        (out / "meta.json").write_text(json.dumps(meta, indent=2))
        print(f"[b0] mav {stats}, truth {meta['truth_samples']}")

    s = analyze(out)
    print(json.dumps(s, indent=2))
    print(f"[b0] {out}")
    print(f"[b0] FLIGHT: {s['class']}  ({s.get('detected_by')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
