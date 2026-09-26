#!/usr/bin/env python3
"""
Stage-2 SITL probe: does a "do not trust position" hold action stop the
spoof-induced drift that LOITER suffers? Criteria are pre-registered in
metrics/trust_hold_probe.py — read them before flying.

One UAV (uav_0), hover, no mesh / monitors / coordinator: the probe tests
the ACTION only. Detection is emulated by a fixed delay (--t-action,
default 3.0 s ≈ campaign C MTTD 2.95 s). Nothing in the experiment
pipeline is touched.

Actions
-------
  loiter   control arm: MAVSDK action.hold() (= PX4 LOITER, current C action)
  zerovel  candidate: OFFBOARD with body velocity (0, 0, 0), yawspeed 0.
           Holds zero velocity from the velocity estimate; the spoof
           falsifies GPS position only, so this channel stays true.
  land     fallback (damage limitation, not mission recovery). NB: PX4
           LAND holds horizontal position on the same estimate, so it is
           expected to be exposed to the same jump — flown only if asked.

Prerequisites (same as a campaign run)
--------------------------------------
  scripts/kill_px4.sh; scripts/kill_router.sh
  rm -f ~/PX4-Autopilot/build/px4_sitl_default/rootfs/{0,1,2}/parameters*.bson
  scripts/launch_px4.sh && scripts/launch_router.sh

Usage
-----
  python3 scripts/probe_trust_hold.py --action loiter
  python3 scripts/probe_trust_hold.py --action zerovel
  python3 scripts/probe_trust_hold.py --analyze ~/probe_runs/<dir>

Stage-3b pilot extension (review stage 3, 2026-09-26)
-----------------------------------------------------
  --mission    fly the campaign route (configs/experiment.yaml, 5 m/s)
               instead of hovering; the injection instant is taken once
               the UAV is cruising (ground speed >= --min-speed, true
               velocity from Gazebo is not needed: before injection the
               PX4 velocity estimate is unspoofed).
  --offset 0   no attack: the action is fired at the same relative time
               and post_response_drift is the plain braking/hold distance
               of that action at cruise — the reference the H2 magnitude
               bound is derived from. Labelled REFERENCE, never PASS/FAIL.

  python3 scripts/probe_trust_hold.py --mission --offset 0 --action zerovel
  python3 scripts/probe_trust_hold.py --mission --offset 0 --action loiter

Output: ~/probe_runs/<action>_<unix>/ with trajectory.jsonl (Gazebo truth),
belief.jsonl (PX4 NED), modes.jsonl, meta.json, summary.json. Raw data
stays out of git.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metrics.trust_hold_probe import (  # noqa: E402
    ACTION_T_S,
    WINDOW_S,
    belief_ne,
    read_jsonl,
    summarize,
    truth_ne,
    verdict,
)
from runners.trajectory import TrajectoryRecorder  # noqa: E402

PARAM = "SIM_GPS_OFF_N"
EXPECTED_MODE = {"loiter": "HOLD", "zerovel": "OFFBOARD", "land": "LAND"}


def _w(fh, rec: dict) -> None:
    fh.write(json.dumps(rec) + "\n")
    fh.flush()


async def _first(aiter, pred, timeout: float, what: str):
    async def _run():
        async for x in aiter:
            if pred(x):
                return x
    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except asyncio.TimeoutError:
        raise RuntimeError(f"timeout waiting for {what}") from None


async def _log_belief(drone, fh) -> None:
    async for pv in drone.telemetry.position_velocity_ned():
        p, v = pv.position, pv.velocity
        _w(fh, {"t_wall": time.time(), "n": p.north_m, "e": p.east_m,
                "d": p.down_m, "vn": v.north_m_s, "ve": v.east_m_s,
                "vd": v.down_m_s})


async def _log_modes(drone, fh) -> None:
    last = None
    async for m in drone.telemetry.flight_mode():
        name = str(m).split(".")[-1]
        if name != last:
            _w(fh, {"t_wall": time.time(), "mode": name})
            last = name


async def _do_action(drone, action: str) -> None:
    if action == "loiter":
        await drone.action.hold()
    elif action == "zerovel":
        from mavsdk.offboard import VelocityBodyYawspeed
        # A setpoint must exist before start(); MAVSDK then re-sends it
        # at 20 Hz for as long as the System lives.
        await drone.offboard.set_velocity_body(
            VelocityBodyYawspeed(0.0, 0.0, 0.0, 0.0))
        await drone.offboard.start()
    elif action == "land":
        await drone.action.land()
    else:
        raise ValueError(action)


def speed_at(truth: list, t: float, dt: float = 1.0):
    """Ground speed (m/s) from Gazebo truth over [t - dt, t]; None if the
    samples do not cover the interval. truth = [(t_wall, north, east)]."""
    before = [s for s in truth if t - dt - 0.25 <= s[0] <= t - dt + 0.25]
    at = [s for s in truth if t - 0.25 <= s[0] <= t + 0.25]
    if not before or not at:
        return None
    a = min(before, key=lambda s: abs(s[0] - (t - dt)))
    b = min(at, key=lambda s: abs(s[0] - t))
    if b[0] <= a[0]:
        return None
    return ((b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2) ** 0.5 / (b[0] - a[0])


def reference_label(summary: dict) -> str:
    """Label of a no-attack (--offset 0) run: a measurement, not a verdict."""
    d = summary.get("post_response_drift_m")
    if d is None:
        return "REFERENCE INVALID: no ground truth after the action"
    return f"REFERENCE (no attack): post_response_drift {d:.2f} m"


async def _start_route(drone, min_speed: float, lead_max: float) -> float:
    """Upload + start the campaign route; return once cruising.

    Same items as MavsdkDroneController.upload_mission (5 m/s, fly-through,
    2 m acceptance). Returns the ground speed seen at the trigger.
    """
    from mavsdk.mission import MissionItem as MItem, MissionPlan

    from core.config import load_experiment_config
    from runners.mission_mavsdk import ned_to_gps

    cfg = load_experiment_config(
        Path(__file__).resolve().parent.parent / "configs" / "experiment.yaml")
    home = await _first(drone.telemetry.home(), lambda h: True, 30, "home")
    items = [
        MItem(
            latitude_deg=it.lat, longitude_deg=it.lon,
            relative_altitude_m=it.relative_alt_m, speed_m_s=5.0,
            is_fly_through=True, gimbal_pitch_deg=0.0, gimbal_yaw_deg=0.0,
            camera_action=MItem.CameraAction.NONE, loiter_time_s=0.0,
            camera_photo_interval_s=0.0, acceptance_radius_m=2.0,
            yaw_deg=float("nan"), camera_photo_distance_m=float("nan"),
            vehicle_action=MItem.VehicleAction.NONE,
        )
        for it in (
            ned_to_gps(home_lat=home.latitude_deg, home_lon=home.longitude_deg,
                       north_m=wp.north_m, east_m=wp.east_m, alt_m=wp.alt_m)
            for wp in cfg.mission.waypoints
        )
    ]
    await drone.mission.upload_mission(MissionPlan(items))
    await drone.mission.start_mission()
    # Skip the first leg's acceleration, then wait for cruise speed.
    await asyncio.sleep(8.0)
    pv = await _first(
        drone.telemetry.position_velocity_ned(),
        lambda p: (p.velocity.north_m_s ** 2 + p.velocity.east_m_s ** 2) ** 0.5
        >= min_speed,
        lead_max, f"cruise speed >= {min_speed} m/s")
    return (pv.velocity.north_m_s ** 2 + pv.velocity.east_m_s ** 2) ** 0.5


async def fly(args, out: Path) -> dict:
    from mavsdk import System

    meta = {"action": args.action, "offset_m": args.offset,
            "t_action_s": args.t_action, "window_s": args.window,
            "alt_m": args.alt, "t_inject": None, "t_action": None,
            "action_error": None, "restore_readback": None,
            "mission": bool(args.mission), "speed_at_trigger_mps": None}

    drone = System(port=args.grpc_port)
    await drone.connect(system_address=f"udpin://0.0.0.0:{args.mavsdk_port}")
    await _first(drone.core.connection_state(), lambda s: s.is_connected,
                 30, "connection")
    await _first(drone.telemetry.health(),
                 lambda h: h.is_global_position_ok and h.is_home_position_ok
                 and h.is_local_position_ok, 120, "position health")

    cur = await drone.param.get_param_float(PARAM)
    if abs(cur) > 1e-6:
        print(f"[probe] WARNING {PARAM}={cur} before flight -> resetting to 0")
        await drone.param.set_param_float(PARAM, 0.0)
        await asyncio.sleep(10)

    bfh = open(out / "belief.jsonl", "w")
    mfh = open(out / "modes.jsonl", "w")
    tasks = [asyncio.ensure_future(_log_belief(drone, bfh)),
             asyncio.ensure_future(_log_modes(drone, mfh))]
    try:
        await drone.action.set_takeoff_altitude(args.alt)
        await drone.action.arm()
        await drone.action.takeoff()
        await _first(drone.telemetry.position(),
                     lambda p: p.relative_altitude_m >= args.alt - 1.0,
                     60, "takeoff altitude")
        print(f"[probe] at {args.alt} m, settling {args.settle} s")
        await asyncio.sleep(args.settle)
        if args.mission:
            meta["speed_at_trigger_mps"] = await _start_route(
                drone, args.min_speed, args.lead_max)
            print(f"[probe] cruising at {meta['speed_at_trigger_mps']:.2f} m/s")

        meta["t_inject"] = time.time()
        if args.offset != 0.0:
            await drone.param.set_param_float(PARAM, args.offset)
            print(f"[probe] injected {PARAM}={args.offset}")
        else:
            print("[probe] no attack (--offset 0): reference instant only")

        await asyncio.sleep(max(0.0, meta["t_inject"] + args.t_action - time.time()))
        meta["t_action"] = time.time()
        try:
            await asyncio.wait_for(_do_action(drone, args.action), timeout=5.0)
            print(f"[probe] action {args.action} accepted "
                  f"at +{meta['t_action'] - meta['t_inject']:.2f} s")
        except Exception as exc:  # recorded, judged by verdict()
            meta["action_error"] = repr(exc)
            print(f"[probe] action {args.action} FAILED: {exc!r}")

        await asyncio.sleep(max(0.0, meta["t_inject"] + args.window - time.time()))
        print("[probe] window closed")
    finally:
        try:
            await drone.param.set_param_float(PARAM, 0.0)
            meta["restore_readback"] = await drone.param.get_param_float(PARAM)
        except Exception as exc:
            print(f"[probe] WARNING restore failed: {exc!r}")
        try:
            await drone.action.land()
            await _first(drone.telemetry.in_air(), lambda a: not a, 90, "landing")
        except Exception as exc:
            print(f"[probe] WARNING land: {exc!r}")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        bfh.close()
        mfh.close()
    return meta


def fallback_mode(out: Path, meta: dict) -> str | None:
    """First mode other than the expected one inside the window after the
    action reached the expected mode. None if the action held.

    modes.jsonl logs changes only, so the mode already in effect at
    t_action counts (loiter: PX4 is in HOLD after takeoff already)."""
    exp = EXPECTED_MODE[meta["action"]]
    if meta.get("t_action") is None or not (out / "modes.jsonl").exists():
        return None
    t_end = meta["t_inject"] + meta["window_s"]
    recs = sorted(read_jsonl(str(out / "modes.jsonl")), key=lambda r: r["t_wall"])
    at_action = None
    for r in recs:
        if r["t_wall"] <= meta["t_action"]:
            at_action = r["mode"]
    seen = at_action == exp
    for r in recs:
        if r["t_wall"] <= meta["t_action"] or r["t_wall"] > t_end:
            continue
        if r["mode"] == exp:
            seen = True
        elif seen:
            return r["mode"]
    return None if seen else "never entered " + exp


def analyze(out: Path) -> dict:
    meta = json.loads((out / "meta.json").read_text())
    if meta.get("t_inject") is None:
        raise SystemExit(f"[probe] no injection recorded in {out} — flight aborted early")
    truth = truth_ne(read_jsonl(str(out / "trajectory.jsonl")))
    belief = belief_ne(read_jsonl(str(out / "belief.jsonl")))
    s = summarize(truth, belief, meta["t_inject"], meta["t_action"],
                  window=meta["window_s"])
    fb = fallback_mode(out, meta)
    s["action"] = meta["action"]
    s["fallback_mode"] = fb
    s["action_error"] = meta["action_error"]
    s["restore_readback"] = meta["restore_readback"]
    s["mission"] = meta.get("mission", False)
    s["offset_m"] = meta.get("offset_m")
    s["speed_at_action_mps"] = (
        None if meta["t_action"] is None else speed_at(truth, meta["t_action"]))
    if meta.get("offset_m") == 0.0:
        s["verdict"] = reference_label(s)
    else:
        s["verdict"] = verdict(meta["action"], s, meta["action_error"], fb)
    (out / "summary.json").write_text(json.dumps(s, indent=2))
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--action", choices=sorted(EXPECTED_MODE))
    ap.add_argument("--analyze", metavar="DIR", help="re-analyse a probe dir")
    ap.add_argument("--offset", type=float, default=50.0)
    ap.add_argument("--t-action", type=float, default=ACTION_T_S)
    ap.add_argument("--window", type=float, default=WINDOW_S)
    ap.add_argument("--alt", type=float, default=15.0)
    ap.add_argument("--settle", type=float, default=10.0)
    ap.add_argument("--mavsdk-port", type=int, default=14560)
    ap.add_argument("--grpc-port", type=int, default=50051)
    ap.add_argument("--out", default=os.path.expanduser("~/probe_runs"))
    ap.add_argument("--mission", action="store_true",
                    help="fly the campaign route; act while cruising (stage 3b)")
    ap.add_argument("--min-speed", type=float, default=4.0,
                    help="cruise ground speed that arms the trigger (m/s)")
    ap.add_argument("--lead-max", type=float, default=60.0,
                    help="max seconds to wait for cruise speed")
    args = ap.parse_args()

    if args.analyze:
        out = Path(args.analyze)
    else:
        if not args.action:
            ap.error("--action is required unless --analyze is given")
        out = Path(args.out) / f"{args.action}_{int(time.time())}"
        out.mkdir(parents=True, exist_ok=False)
        rec = TrajectoryRecorder(out_path=out / "trajectory.jsonl")
        rec.start()
        try:
            meta = asyncio.run(fly(args, out))
        finally:
            rec.stop()
        (out / "meta.json").write_text(json.dumps(meta, indent=2))
        print(f"[probe] trajectory samples: {rec.stats['samples_written']}")

    s = analyze(out)
    print(json.dumps(s, indent=2))
    print(f"[probe] {out}")
    print(f"[probe] VERDICT: {s['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
