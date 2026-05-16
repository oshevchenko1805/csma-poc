# Step 10b — Live MAVSDK Mission Integration (Closeout)

Closing document for the chat that resolved the port-14540 conflict
(PROJECT_STATE.md §13) and ran the first end-to-end live trial with
an active MAVSDK-driven mission.

## What was achieved

Three live PX4 SITL instances flying a coordinated waypoint mission
under Architecture C, attacked at t+90s with comm_disruption (iptables
DROP on UAV-0's 14542 ingress), with the full detection → isolation →
real PX4 restart → ack pipeline running for real.

Single trial, single attack, single target — but the WHOLE pipeline
was active for the first time including MAVSDK-controlled flight,
which step 10a had bypassed via NullMissionRunner because of the
port-14540 conflict.

## Final metrics (first live trial)

| Metric              | Value                         |
|---------------------|-------------------------------|
| MTTD                | 3.28 s                        |
| MTTR                | 8.07 s                        |
| Detected            | True                          |
| Recovery success    | True                          |
| Impact scope        | 1 (only target affected)      |
| Affected UAVs       | `['uav_0']`                   |
| Has false positive  | False                         |
| Run duration        | 159.2 s                       |
| PX4 inst 0 PID      | 2421 → 3826 (real restart)    |

These numbers are essentially identical to step 10a (2.88 / 8.07).
That's the right outcome: the detect/isolate/recover pipeline is the
same regardless of whether the drone is "flying" (MAVSDK) or only
"powered on" (Null). Step 10a's metrics were valid PoC measurements,
not artefacts of NullMissionRunner.

## How port-14540 conflict was resolved (Option A from §13)

One `mavlink-routerd` instance per UAV, each one consumes PX4's
onboard MAVLink stream from a single source and fans it out to two
independent consumers:

```
PX4 inst i  (sysid i+1, sends to 1454{i})
     │
     ▼  UDP
mavlink-routerd inst i   (Server-mode bind on 1454{i})
     ├──► Monitor (pymavlink, udpin)          on 1457{i}
     └──► MAVSDK   (mavsdk_server, udpin://)  on 1456{i}
```

Three processes per UAV-side: PX4 + router + (optionally) Monitor +
mission's mavsdk_server. Total 12 processes for 3 UAVs not counting
gRPC servers.

### Critical port mapping (this supersedes PROJECT_STATE §10's table)

| UAV   | PX4 -i | sysid | Router bind (PX4→Router) | Monitor reads               | MAVSDK reads                | MAVSDK gRPC |
|-------|--------|-------|--------------------------|-----------------------------|-----------------------------|-------------|
| uav_0 | 0      | 1     | UDP 14540                | `udpin:127.0.0.1:14570`     | `udpin://0.0.0.0:14560`     | 50051       |
| uav_1 | 1      | 2     | UDP 14541                | `udpin:127.0.0.1:14571`     | `udpin://0.0.0.0:14561`     | 50052       |
| uav_2 | 2      | 3     | UDP 14542                | `udpin:127.0.0.1:14572`     | `udpin://0.0.0.0:14562`     | 50053       |

### Two unobvious URL details

1. **MAVSDK uses `udpin://0.0.0.0:`, NOT `udpin://127.0.0.1:`.**
   `mavsdk_server` 3.15.3 binds successfully when given the loopback
   address but never reports `System discovered` — heartbeats arrive
   but are silently dropped. Switching to `0.0.0.0` fixes it. The
   router on the other side still sends to `127.0.0.1:1456{i}` — the
   asymmetry is empirically required.

2. **MAVSDK URL scheme is `udpin://`, NOT `udp://`.**
   `udp://` triggers a deprecation warning in MAVSDK 3.x and behaves
   inconsistently. New form: `udpin://` for "bind and listen",
   `udpout://` for "connect to remote".

## New files (configs + scripts)

```
configs/router/router_inst0.conf      # mavlink-router config, UAV-0
configs/router/router_inst1.conf      # …UAV-1
configs/router/router_inst2.conf      # …UAV-2
scripts/launch_router.sh              # start all three routers
scripts/kill_router.sh                # tear them down by PID file
```

Each `router_inst{i}.conf` is ~30 lines, three endpoint blocks
(Server px4_inst{i}, Normal monitor_inst{i}, Normal mavsdk_inst{i}),
TCP server disabled to avoid 5760 collision across instances.

## Modified files

### `configs/experiment.yaml`
`telemetry.endpoints[*].endpoint` shifted `udpin:127.0.0.1:14540+i`
→ `udpin:127.0.0.1:14570+i`. Monitor now reads from the router's
Monitor-side fan-out port instead of where PX4 sends.

### `scripts/run_one.py::build_mavsdk_mission`
Three semantic changes:
- MAVSDK port `14540+i` → `14560+i` (router's MAVSDK-side fan-out).
- URL scheme `udp://127.0.0.1:` → `udpin://0.0.0.0:`.
- Custom controller factory that passes a distinct gRPC port
  (50051+i) to each `MavsdkDroneController`. Without this all three
  controllers race for default port 50051 and only one wins.

Updated docstring documents Option A architecture rationale.

### `runners/mission_mavsdk.py::MavsdkDroneController`

Two patches in this class. Both required to run multiple controllers
in parallel against live PX4. Tests (`FakeDroneController`) untouched;
test count remains 438.

**Patch 1 — `grpc_port: Optional[int] = None` kwarg.**
Stored as `self._grpc_port`. Used in `connect()` to instantiate
`System(port=self._grpc_port)` when not None. Without this, the
default `System()` uses gRPC port 50051 and parallel controllers
fail with `AioRpcError: Socket closed` (only one wins the bind, the
losers get their gRPC channel torn down).

**Patch 2 — `_wait_armable()` in `connect()`.**
After the existing wait for `is_connected=True` (first heartbeat),
also wait for `telemetry.health()` to report `is_armable=True`
(timeout 90s). Without this, the very first action after connect
(`drone.action.set_takeoff_altitude(15.0)`) fails with
`ActionError: PARAMETER_ERROR` — PX4 silently retries-and-drops
param sets while the param subsystem isn't synced and EKF/GPS
aren't converged. SITL on M4 Pro ARM64: ~30-60s from first HB to
is_armable.

## Environment changes

### VM disk: 30 GB → 100 GB
The 30 GB ceiling was hit four times during this session. PX4 SITL
fills disks both at idle (300-500 MB/h cumulative across 3 instances,
mostly ulog) and at flight (100-200 MB/inst/run). Resized via UTM
"Drives → Resize…" then in-VM:

```
sudo apt install -y cloud-guest-utils
sudo growpart /dev/vda 3         # or /dev/sda 3
sudo pvresize /dev/vda3
sudo lvextend -l +100%FREE /dev/mapper/ubuntu--vg-ubuntu--lv
sudo resize2fs /dev/mapper/ubuntu--vg-ubuntu--lv
```

Step 12 (full experiment, ~300 trials) at flight ulog rates needs
~30-90 GB cumulative if no rotation. 100 GB gives headroom.

### `mavlink-router` installed
Built from source at `~/mavlink-router/` (commit v4-16-g2362c62),
installed to `/usr/bin/mavlink-routerd`. Not available in Ubuntu
22.04 apt repos. Build deps: `git meson ninja-build pkg-config gcc
g++ python3-future libtool autoconf`. Submodule
`modules/mavlink_c_library_v2` must be initialised or the build
silently produces a non-working binary.

### `spice-vdagent` known to flap
Clipboard from host (Mac) to VM occasionally stops working. Fix
without reboot: `sudo systemctl restart spice-vdagentd; pkill -USR1
spice-vdagent; spice-vdagent`.

## Known limitations for future steps

### Other MAVSDK consumers still use default gRPC port (50051)

`DefaultMavsdkRunner` (`enforcement/handlers/loiter.py`, recovery
action for gps_spoofing detection) and `DefaultGpsSpoofingRunner`
(`attacks/gps_spoofing.py`, the GPS attack injector) both call
`System()` with no port argument. They will collide with the three
already-running mission controllers (50051-50053) when any of:

- `--attack gps_spoofing` (injector spawns a short-lived System)
- recovery action `loiter` (handler spawns a short-lived System)

These need the same `grpc_port` parameter pattern, with ports
e.g. 50054 (injector) and 50055-50057 (per-UAV loiter). Must be
done before:

- running `--attack gps_spoofing` against any architecture
- running `--attack command_injection` IF its recovery uses loiter
  (currently it uses restart, so it's safe for now)
- running multi-architecture matrix smokes

### `launch_router.sh` had a `tail -5` bug
Fixed in committed version: `tail -n 5` for multi-file usage on
modern coreutils.

### Disk hygiene checklist between trials
Even with 100 GB, repeated runs accumulate ulogs and Gazebo logs.
Between batches:
```
./scripts/kill_px4.sh
rm -rf ~/PX4-Autopilot/build/px4_sitl_default/rootfs/*/log/* 2>/dev/null
rm -rf ~/.gz/log/* /tmp/.gz* 2>/dev/null
rm -f /tmp/px4_inst_*.log /tmp/router_inst_*.log 2>/dev/null
```
After PX4 dies, deleted-but-held ulog files are released and `df` jumps.

## Test status
`python -m pytest tests/ -q` → **438 passed**. No regressions.
`FakeDroneController` path unaffected — neither `grpc_port` nor
`_wait_armable` runs in tests.

## Reproducing the closing trial

```bash
# 1. Bring up PX4 (3 instances)
./scripts/launch_px4.sh

# 2. Bring up routers (3 instances, fan-out)
./scripts/launch_router.sh

# 3. Run one trial
source .venv/bin/activate
python scripts/run_one.py \
    --arch c \
    --attack comm_disruption \
    --mission mavsdk \
    --target-uav uav_0 \
    --attack-at-sec 90 \
    --observation-after-attack-sec 60 \
    --px4-pid-file /tmp/px4_pids

# 4. Analyse
python -c "
from pathlib import Path
from metrics.analyzer import analyze_run
from pprint import pp
pp(analyze_run(sorted(Path('runs').iterdir())[-1]))
"
```

Expected wall time: ~3 minutes. Expected outcome: `DONE in ~160s
error=none`, then analyzer outputs MTTD ≈ 3 s, MTTR ≈ 8 s,
`detected=True`, `recovery_success=True`, `impact_scope=1`,
`has_false_positive=False`.

## Suggested next steps (priority order)

1. **Patch `DefaultMavsdkRunner` and `DefaultGpsSpoofingRunner`**
   to accept a per-call `grpc_port`. Without this, gps_spoofing
   attacks and loiter recovery actions will fail.
2. **3 single-trial smokes** against `command_injection` and any
   other attack we can run safely. Verify analyser output for each.
3. **Step 11**: 3×3 matrix smoke — 3 architectures × 3 attacks ×
   ≥1 baseline = 12 trials, ~40 min wall time.
4. **Step 12**: full experiment (300 trials at 10 trials/cell, ~30 h
   total wall time, requires the 100 GB disk).
