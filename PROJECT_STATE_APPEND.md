<!--
Append this to the END of PROJECT_STATE.md, after the existing
"## Step 10b — CLOSED (live MAVSDK mission)" section.
Do NOT replace anything above.
-->

---

## Step 10c — CLOSED (live `command_injection`)

**Status:** Live arch-C `command_injection` end-to-end works. Three orthogonal fixes:

1. `core/telemetry.py` — `SYSID_FILTER_PASSTHROUGH = frozenset({"COMMAND_LONG","COMMAND_INT"})`. Listener no longer drops command messages from non-whitelist sysids; `CommandInjectionDetector.DEFAULT_WHITELIST = {1,2,3,255}` is now the gatekeeper.
2. `scripts/run_one.py` — `command_injection` lambda uses `port_base=14570` (Monitor listener) instead of class default 14540 (router Server endpoint that drops loop-prevention).
3. Per-UAV gRPC ports — `DefaultMavsdkRunner` and `DefaultGpsSpoofingRunner` both accept `grpc_port` kwarg; factory wires loiter handlers on 50054-50056 (`LOITER_GRPC_PORT_BASE`), run_one.py pins GPS injector to 50057.

**See [STEP_10C_NOTES.md](STEP_10C_NOTES.md)** for full closeout.

**Open at 10c close:** Gazebo physics divergence during simultaneous takeoff at 2 m spawn separation (uav_2 reached ~54 m/s lateral, DART aborted). Resolved in 10d.

---

## Step 10d — CLOSED (clean baseline + clean command_injection)

**Status:** **Zero false positives** on arch-C baseline. `command_injection` × arch-C: `detected=True, mttd=0.012s, mttr=0.0004s, impact_scope=1, affected_uavs=['uav_0'], has_false_positive=False`. 439 tests passing.

Two root causes (both SITL-setup, not CSMA defects):

1. **Spawn separation 2 m → 5 m** (`scripts/launch_px4.sh` + `runners/factory.py::_default_px4_pose`). At 2 m, simultaneous `asyncio.gather` takeoff coupled the three X500s via downwash/DART → Gazebo crash → CSMA observed heartbeat loss everywhere → false `impact_scope=3`. 5 m is stable.

2. **Mission relative-altitude bug** (`runners/mission_mavsdk.py`). `MissionItem.alt` (absolute MSL) was stored but `upload_mission` hardcoded `relative_altitude_m=0.0` → drone took off to 15 m then mission commanded descent to 0 m AGL → mc_pos_control "invalid setpoints" → Failsafe blind-land loop → chronic EKF horizontal residual → gps detector false positives + cross_check cascade. Fix: `MissionItem.alt` → `MissionItem.relative_alt_m`, `ned_to_gps` drops `home_alt` param, upload feeds `relative_altitude_m=it.relative_alt_m`.

**Useful property surfaced for dissertation Chapter 5:** the detection layer is robust to flight-layer failures (the `command_injection` attacker writes UDP directly to Monitor listener, bypassing router and PX4; detection survives even when PX4 instances die).

**See [STEP_10D_NOTES.md](STEP_10D_NOTES.md)** for full closeout and reproduction.

---

## Step 10e — OPEN (`gps_spoofing` redesign)

**Status:** Not started in code. Two independent blockers identified during an attempted gps_spoofing smoke; rolled back to keep `main` clean.

### Blocker A — `SIM_GPS_NOISE` does not exist in current PX4 build

PX4 SITL at `~/PX4-Autopilot` uses **gz-sim** (Gazebo Garden/Harmonic; `gz::sim::v8` in logs), not Gazebo Classic. The default param targeted by `attacks/gps_spoofing.py::GpsSpoofingInjector.DEFAULT_PARAM_NAME = "SIM_GPS_NOISE"` is from the old Gazebo Classic plugin. PX4 responds with `ERROR [mavlink] Unknown param name: SIM_GPS_NOISE`.

**Redesign options (ranked):**
1. Find the gz-sim equivalent — search `~/PX4-Autopilot/src/modules/simulation/` and `Tools/simulation/gz/` for navsat-related params (`SIM_GZ_*`?). Inspect `gz_x500` model SDF's `navsat_sensor` block.
2. Switch to `HIL_GPS` message injection (alt #2 in `gps_spoofing.py` module docstring). More realistic but brittle across PX4 versions.
3. Gazebo plugin manipulation. Most realistic, hardest.

### Blocker B — Router 4th-endpoint approach broke mission MAVSDK

Adding `[UdpEndpoint gps_inj_instN]` (Normal mode, 14550+N) alongside the existing `px4 / monitor / mavsdk` endpoints in `configs/router/router_inst*.conf` caused mission MAVSDK `set_takeoff_altitude()` to timeout in 7 s with `Retrying failed set param timeout: MIS_TAKEOFF_ALT`. Router log spammed `5 messages to unknown endpoints in the last 5 seconds` continuously.

Root cause unconfirmed — likely a mavlink-routerd discovery/learning edge case when a Normal-mode endpoint has no active peer to learn sysid from. 3-endpoint config restored, pipeline confirmed working (command_injection re-verified clean after rollback). Reverted files: `attacks/gps_spoofing.py`, `scripts/run_one.py`, `tests/test_attack_gps_spoofing.py` (the `udpin://0.0.0.0:` + `port_base=14550` wiring was correct in form but pointless without a working router fan-out).

**Wiring redesign candidate:** TCP server endpoint per router instance (`TcpServerPort = 5761+i` in `router_inst*.conf` — currently disabled because three instances would collide on default 5760, but distinct ports avoid that). Injector connects via `tcp://127.0.0.1:5761` etc. Structurally different from the failing UDP Normal-mode path.

### Remaining for step 11 readiness

- gps_spoofing live on arch C (after A + B resolved).
- arch A and arch B baseline + one attack each — never run live through current MAVSDK pipeline.

---

## Current pipeline state (post-10d)

| Combo                              | Status         |
|------------------------------------|----------------|
| arch C × baseline                  | ✅ clean       |
| arch C × comm_disruption           | ✅ (step 10b)  |
| arch C × command_injection         | ✅ (step 10d)  |
| arch C × gps_spoofing              | ⏸️ blocked (step 10e) |
| arch A × any                       | ⏸️ never run live |
| arch B × any                       | ⏸️ never run live |

439 pytest tests passing. Repo on `main`, working tree clean (only untracked `runs/` directory with local SITL logs).
