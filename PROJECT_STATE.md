# PROJECT_STATE.md — Full Handoff

This is the onboarding document for a new chat picking up this work.
Read this **before** doing anything else. The repo + this file
together contain everything needed to continue.

---

## 1. Executive summary

**Project**: PhD dissertation practical implementation. A multi-UAV
swarm cybersecurity PoC evaluating a self-healing Cybersecurity Mesh
Architecture (CSMA) against two baselines.

**Status**: **All non-PX4 code complete.** 422 tests passing. What
remains is **only live PX4 integration runs** — step 10 forward.

**User**: V, PhD researcher, writing in Ukrainian. The dissertation is
a monograph. Chapters 2–3 are complete and reviewed. This repo is the
practical part referenced by Chapters 4–5.

**Tooling**: Ubuntu 22.04 ARM64 VM (UTM) on Apple M4 Pro Mac, PX4
SITL + Gazebo, Python 3.10.12.

---

## 2. Working style (must read before responding)

These are the user's stated preferences. Follow them.

- **Russian throughout.** Replies are in Russian unless code/comments.
- **Кратко и по сути.** No fluff, no preamble. Direct answers.
- **Honest about limits.** If something won't work or there's not enough
  info — say so immediately. Don't guess.
- **Step-by-step, one micro-step per turn.** Never batch multiple
  changes. After each step:
  1. Write code in claude's sandbox: `/home/claude/csma_poc_v2/`
  2. Run pytest, verify count
  3. Stage to `/mnt/user-data/outputs/csma_poc_v2/`
  4. `present_files` the new/changed files
  5. Tell the user exactly which files to copy + expected test count
- **Wait for the count.** User runs pytest locally and confirms.
  Only then move to next step.
- **PhD-quality, no shortcuts.** If a PoC simplification is
  needed, document it explicitly for Chapter 4. No silent hacks.
- **Don't overuse formatting.** Bullets/headers when they add clarity,
  prose otherwise.

---

## 3. Architectural philosophy (do not violate)

### The one rule

> **Architecture difference is deployment, not code branches.**

There are no `if architecture == 'A'` checks anywhere in the domain
code (`detectors/`, `decision/`, `runners/monitor.py`,
`runners/coordinator.py`). Differences live in:
- **YAML configs** (`configs/architecture_*.yaml`) that select which
  detectors and which enforcer type to use
- **Dependency injection** at component boundaries
  (`NoOpMesh` vs `ZmqMesh`, `LocalIsolationEnforcer` vs
  `MeshAnnouncingIsolationEnforcer`)
- **The factory** (`runners/factory.py`) that reads configs and
  picks the right components

If you ever feel like writing `if arch == ...` in domain code: stop.
The right answer is either a config switch, a different DI choice,
or a new class. Violating this turns the dissertation's "single
architecture, three deployments" claim into a lie.

### Component layering

```
┌──────────────────────────────────────────────────┐
│  Detectors (pure)                                │
│    feed(TelemetryEvent) → Optional[SecurityEvent]│
│    tick(now) → Optional[SecurityEvent]           │
│    No I/O. No threads. No logging.               │
├──────────────────────────────────────────────────┤
│  Deciders (pure state machines)                  │
│    evaluate(Event) → Optional[Event]             │
│    No I/O. Track state across calls.             │
├──────────────────────────────────────────────────┤
│  Enforcers / Handlers (side effects)             │
│    Have DI seams (ProcessRunner, MavsdkRunner,   │
│    mesh, etc.) so unit tests can swap fakes.     │
├──────────────────────────────────────────────────┤
│  Runners (Monitor, Coordinator, Experiment)      │
│    Own threading. Own logging. Wire everything.  │
└──────────────────────────────────────────────────┘
```

Threading and logging are the **monitor's responsibility**, not the
detector's. This is why every Detector can be tested with simple
synchronous calls.

### DI seams (where fakes plug in for tests)

| Seam | Default | Used in tests |
|------|---------|---------------|
| `connection_factory` (factory.py) | real pymavlink | `FakeConnection` |
| `mesh_factory` (factory.py) | ZmqMesh / NoOpMesh | `RecordingMesh` |
| `ProcessRunner` (restart.py) | `subprocess.Popen` | `FakeProcessRunner` |
| `MavsdkRunner` (loiter.py) | real MAVSDK (lazy import) | `FakeMavsdkRunner` |
| `IptablesRunner` (comm_disruption) | `subprocess` with sudo | `FakeIptablesRunner` |
| `MavlinkSender` (command_injection) | `PymavlinkSender` (lazy) | `FakeMavlinkSender` |
| `GpsSpoofingRunner` (gps_spoofing) | MAVSDK Param API (lazy) | `FakeGpsSpoofingRunner` |
| `DroneController` (mission_mavsdk) | `MavsdkDroneController` (lazy) | `FakeDroneController` |
| `MissionRunner` (missions.py) | `MavsdkMissionRunner` | `NullMissionRunner` |
| `AttackInjector` (attacks/base.py) | concrete attacks | `NullAttackInjector`, `RecordingInjector` |

---

## 4. What's done (completed steps)

### Step 5: Foundation
- `core/events.py` — `BaseEvent` + 8 typed event dataclasses with
  registry: `TelemetryEvent`, `SecurityEvent`, `IsolationAnnounce`,
  `RecoveryRequest`, `RecoveryAck`, `AttackEvent`, `MissionEvent`,
  `PeerPositionAnnounce`
- `core/logger.py` — JSONL `EventLogger` (thread-safe), `read_jsonl`,
  `merge_jsonl` for post-hoc analysis
- `core/mesh.py` — `MeshBus` ABC + `NoOpMesh` + `ZmqMesh`
- `core/telemetry.py` — `TelemetryListener`
- `core/config.py` — typed config loader
- 4 YAML configs: `configs/{architecture_a,b,c,experiment}.yaml`
- `scripts/smoke_telemetry.py` — live PX4 SITL verification

### Step 6: Detectors
- `detectors/base.py` — `Detector` ABC
- `detectors/heartbeat.py` — 3s timeout + hysteresis
- `detectors/command.py` — sysid whitelist `{1, 2, 3, 255}`
- `detectors/gps.py` — EKF `pos_horiz_ratio > 1.0` sustained 3 samples
- `detectors/cross_check.py` — peer-position kinematic feasibility
  (does NOT inherit `Detector`; separate contract `feed_peer_position`)

### Step 7: Decision + enforcement
- `decision/isolation.py` — severity threshold, dedup
- `decision/recovery.py` — `REASON_TO_ACTION` table
- `enforcement/isolation.py` — `LocalIsolationEnforcer` (A/B),
  `MeshAnnouncingIsolationEnforcer` (C)
- `enforcement/recovery.py` — `RecoveryExecutor` (async), `ActionHandler` ABC

### Step 8: Runners
- 8.1 `runners/monitor.py` — observation-only Monitor
- 8.2 same — added isolation pipeline (decider + enforcer optional)
- 8.3 same — added mesh + cross_check (Monitor does NOT own mesh lifecycle)
- 8.4 `runners/coordinator.py` — election (lowest alive sysid) +
  recovery orchestration. Uses `asyncio.run()` per recovery (PoC)
- 8.5 `enforcement/handlers/{restart,loiter,filter}.py` — real
  action handlers with `ProcessRunner` / `MavsdkRunner` DI seams
- 8.6a `runners/factory.py` — configs → `WiredFleet`
- 8.6b `runners/experiment.py` — `ExperimentRunner` orchestrator +
  `RunResult`. Cleanup ALWAYS runs (try/finally)
- 8.6b `runners/missions.py` — `MissionRunner` ABC + `NullMissionRunner`
- 8.6b `attacks/base.py` — `AttackInjector` ABC + `NullAttackInjector`

### Step 9: Attack injectors
- `attacks/comm_disruption.py` — iptables DROP rule via
  `SubprocessIptablesRunner` (default uses `sudo -n`)
- `attacks/command_injection.py` — periodic MAVLink COMMAND_LONG with
  spoofed sysid in background asyncio task. `PymavlinkSender` wraps
  pymavlink sync API via `asyncio.to_thread`
- `attacks/gps_spoofing.py` — PX4 SIM_GPS_NOISE param manipulation
  via MAVSDK Param API. arm() captures original, cleanup() restores
- All three attacks: arm/fire/cleanup lifecycle with try/finally
  safety; cleanup ALWAYS runs and swallows exceptions

### Mission infrastructure (for step 10)
- `runners/mission_mavsdk.py` — `MavsdkMissionRunner` orchestrates N
  PX4 instances via MAVSDK; `DroneController` ABC + real implementation
  + `ned_to_gps` conversion. `start()` runs connect/takeoff/upload/start
  in parallel via `asyncio.gather`

### Step 12 analyzer (computed metrics)
- `metrics/analyzer.py` — `RunMetrics` (per-run) + `AggregateMetrics`
  (across runs). Reads `merged.jsonl` + `run_summary.json`,
  computes MTTD/MTTR/impact/FP/FN. Linear-interpolation percentiles,
  no numpy dependency. Graceful error handling: missing/corrupt files
  → `error` field, not exceptions

---

## 5. What's not done (only PX4-live work)

### Step 10 — First end-to-end integration test
Simplest combo: **Architecture C + comm_disruption + real PX4 SITL**.

Tasks:
- Launch 3 PX4 instances with `MavsdkMissionRunner`-compatible setup
- Verify telemetry flows to monitors
- Verify mesh peers reach each other (cross_check fires on real positions)
- Trigger iptables drop → measure MTTD
- Verify RestartProcessHandler launches new PX4 → heartbeats resume
- Verify RecoveryAck propagates → `un_isolate` lifts
- **Expected blockers**: port conflicts (MAVSDK vs telemetry listener
  both want 14540?), home-position GPS lock timing, `sudo -n` for
  iptables (CAP_NET_ADMIN setup), PX4 cold-start time

This will take several iterations of run → see error → fix → repeat.

### Step 11 — 3×3 matrix smoke
For each (architecture, attack) combo: 1 trial. 9 total. Sanity that
nothing crashes catastrophically. Not full statistics yet.

### Step 12 (runs portion) — Full experiment + plots
- Run the experiment (probably 100 trials per cell, ~30 wall-hours of SITL)
- Run analyzer over results (analyzer code is done, just point it at
  the results directory)
- Generate plots for Chapter 5 (matplotlib code is NOT yet written —
  add `metrics/plots.py` in this step)
- Optional: add `psutil` sampling to `ExperimentRunner` for resource
  overhead (CPU%, RAM) — NOT yet wired

---

## 6. File inventory

```
csma_poc_v2/
├── README.md
├── PROJECT_STATE.md (this file)
├── .gitignore
├── requirements.txt
│
├── core/                        (foundation)
│   ├── events.py
│   ├── logger.py
│   ├── mesh.py
│   ├── telemetry.py
│   └── config.py
│
├── configs/                     (architecture + experiment configs)
│   ├── architecture_a.yaml
│   ├── architecture_b.yaml
│   ├── architecture_c.yaml
│   └── experiment.yaml
│
├── detectors/                   (pure detectors)
│   ├── base.py
│   ├── heartbeat.py
│   ├── command.py
│   ├── gps.py
│   └── cross_check.py
│
├── decision/                    (pure deciders)
│   ├── isolation.py
│   └── recovery.py
│
├── enforcement/                 (side effects)
│   ├── isolation.py
│   ├── recovery.py
│   └── handlers/
│       ├── __init__.py
│       ├── restart.py           (subprocess + Popen tracking)
│       ├── loiter.py            (MAVSDK action.hold())
│       └── filter.py            (state-only; PoC simplification)
│
├── runners/                     (orchestrators)
│   ├── __init__.py
│   ├── monitor.py               (per-UAV obs + isolation + mesh)
│   ├── coordinator.py           (election + recovery orchestration)
│   ├── factory.py               (configs → WiredFleet)
│   ├── missions.py              (MissionRunner ABC + NullMissionRunner)
│   ├── mission_mavsdk.py        (MavsdkMissionRunner for step 10)
│   └── experiment.py            (full lifecycle orchestrator)
│
├── attacks/                     (concrete attacks)
│   ├── __init__.py
│   ├── base.py                  (AttackInjector ABC + Null)
│   ├── comm_disruption.py       (iptables DROP)
│   ├── command_injection.py     (MAVLink spoofed sysid loop)
│   └── gps_spoofing.py          (MAVSDK param manipulation)
│
├── metrics/                     (analysis)
│   ├── __init__.py
│   └── analyzer.py              (MTTD/MTTR/FP/FN/impact)
│
├── scripts/
│   └── smoke_telemetry.py
│
└── tests/                       (24 test files, 422 tests)
```

---

## 7. Test count timeline

```
55 → 83 → 100 → 122 → 143 → 164 → 200 → 218 → 231 → 244 → 252
→ 259 → 278 → 296 → 312 → 326 → 343 → 359 → 379 → 400 → 422 (current)
```

| Increment | What was added |
|-----------|----------------|
| 55 → 164  | Steps 5–6 (foundation, detectors) |
| 164 → 231 | Step 7 (deciders + enforcers) |
| 231 → 296 | Step 8.1–8.5 (monitor + coordinator + handlers) |
| 296 → 326 | Step 8.6a + 8.6b (factory + experiment runner) |
| 326 → 379 | Step 9 (3 attacks) |
| 379 → 400 | MavsdkMissionRunner |
| 400 → 422 | Analyzer |

Quick sanity check: `python -m pytest tests/ -q | tail -3` →
should report `422 passed`.

---

## 8. Key design decisions with rationale

### Why `cross_check` doesn't inherit `Detector`
Detectors take `TelemetryEvent`s (own UAV's telemetry). CrossCheck
takes `PeerPositionAnnounce`s (other UAVs' positions from mesh). Two
different contracts → two different interfaces. Cross_check is wired
separately on `Monitor` via `cross_check=` constructor param.

### Why mesh lifecycle is caller-owned
Mesh can be shared between Monitor (publishes peer_position) and
Coordinator (subscribes to isolation, recovery_req, recovery_ack) in
the same process. If Monitor owned mesh.start/stop, the coord would
not see early subscriptions. Tests must `mesh.start()` before
`monitor.start()` and `mesh.stop()` after `monitor.stop()`.

### Why `asyncio.run()` per recovery in coordinator
Tradeoff. Pros: simple, no long-lived loop to manage. Cons: ~1 s
overhead per call (loop creation + MAVSDK connect).

For PoC this is acceptable and explicit in Chapter 4. If real
deployment needs many recoveries with persistent MAVSDK, refactor
to `asyncio.run_coroutine_threadsafe` against a long-lived loop in
a dedicated thread. Module docstring documents both paths.

### Why three sysids `{1, 2, 3, 255}`
PX4 convention: 1, 2, 3 are the UAV autopilot sysids (instance+1);
255 is the GCS (QGroundControl, MAVSDK). Anything else is an attacker.

### Why attacker_sysid defaults to 99
Outside the whitelist (so detector flags it) but innocuous-looking
(not a magic value). Could be any 4-254 except {1, 2, 3, 255}.

### Why MissionItem uses absolute GPS, not NED
PX4 mission API expects lat/lon waypoints. NED is the input format
(from config) but gets converted using each drone's own home position
at mission start. This means same NED waypoints produce a coordinated
formation flight relative to spawn positions.

### Why analyzer metrics never raise
Real experiment data is messy: missing files, runs killed mid-flight,
corrupt JSON. The analyzer's contract is "return what you found,
report what you couldn't" — populate `error` field instead of raising.
Aggregation then skips errored runs. The dissertation can report
dropout rate as a quality indicator.

---

## 9. PoC simplifications (for Chapter 4)

These are intentional gaps between PoC and a production deployment.
**Document each in Chapter 4** with reasoning.

| Simplification | Real deployment | Impact |
|----------------|-----------------|--------|
| ZeroMQ TCP loopback | FANET radio mesh | Same PUB/SUB semantics, different physical channel + latency |
| `subprocess.Popen` kill+restart | Hot-failover / mission resume | MTTR dominated by PX4 cold start (~5–8s) |
| `FilterCommandsHandler` state-only | iptables / mavlink-router | Real adds ~10–50 ms apply latency |
| MAVSDK connection-per-call | Persistent gRPC connection | ~1 s overhead per loiter recovery |
| Single-VM deployment via IPC | Distributed companion computers | Network latency = loopback, not WiFi |
| Wall-clock timestamps | NTP/PTP-synced clocks | Single VM = coherent clocks "for free" |
| GPS spoofing via SIM_GPS_NOISE | Real RF GPS spoofer | Approximation of effect, not method |
| MTTD floor = 3 s for GPS | Whatever EKF takes | PX4 streams `ESTIMATOR_STATUS` at 1 Hz; detector needs 3 samples |
| `asyncio.run()` per recovery | Long-lived event loop | OK for sync handlers; may need refactor for persistent MAVSDK |
| 3 UAVs | 5–7 UAVs (generalized model) | PoC uses 3 for resource reasons; architecture scales |
| iptables DROP rule (binary) | RF jamming (probabilistic) | Reproducible signal, less realistic |
| Spoofed sysid attack | Could also forge legitimate sysid | Detection of stolen sysid requires signed MAVLink2 — out of scope |
| Pymavlink sync API in asyncio.to_thread | Async-native MAVLink lib | Acceptable overhead; documented |

**Framing**: the architectural model is the contribution, the PoC
validates that the model can be implemented and that the metrics are
meaningful. Limitations of the PoC are not limitations of the architecture.

---

## 10. Environment specs

### Host system
- **Hardware**: Apple M4 Pro Mac
- **VM**: UTM running Ubuntu 22.04 ARM64
- **VM disk**: 30 GB. Clean PX4 logs regularly:
  `rm -rf ~/PX4-Autopilot/build/px4_sitl_default/rootfs/*/log/`
- **Python**: 3.10.12, venv at `~/csma_poc_v2/.venv`

### PX4 SITL
- **Path**: `~/PX4-Autopilot`
- **Build**: `make px4_sitl gz_x500`
- **Launch per UAV**: `PX4_SYS_AUTOSTART=4001 PX4_GZ_MODEL=x500
  PX4_GZ_MODEL_POSE="<offset>" ./build/px4_sitl_default/bin/px4 -i
  <instance>`

### Process layout (3 UAVs)
| UAV | PX4 `-i` | sysid | MAVLink in | MAVSDK out |
|-----|----------|-------|------------|------------|
| uav_0 | 0 | 1 | `udpin:127.0.0.1:14540` | `udp://127.0.0.1:14540` |
| uav_1 | 1 | 2 | `udpin:127.0.0.1:14541` | `udp://127.0.0.1:14541` |
| uav_2 | 2 | 3 | `udpin:127.0.0.1:14542` | `udp://127.0.0.1:14542` |

### Verified MAVLink stream rates (live SITL smoke test)
- `HEARTBEAT` 1 Hz
- `ESTIMATOR_STATUS` 1 Hz **← MTTD floor for GPS detector = 3s**
- `GLOBAL_POSITION_INT` 49.8 Hz
- `ATTITUDE` 99.5 Hz
- `GPS_RAW_INT` 30 Hz
- `LOCAL_POSITION_NED` 30 Hz
- `SYS_STATUS` 5 Hz

### Mesh endpoints (Architecture C)
| UAV | ZMQ endpoint |
|-----|--------------|
| uav_0 | `tcp://127.0.0.1:5550` |
| uav_1 | `tcp://127.0.0.1:5551` |
| uav_2 | `tcp://127.0.0.1:5552` |

### iptables / sudo (Step 10 requirement)
Comm_disruption attack requires either passwordless sudo or
CAP_NET_ADMIN on the python interpreter:

```bash
# Option A: passwordless sudo for iptables
sudo visudo
# Add line: youruser ALL=(ALL) NOPASSWD: /usr/sbin/iptables

# Option B: grant CAP_NET_ADMIN (preferable, no sudo)
sudo setcap cap_net_admin+ep $(realpath $(which python3))
```

---

## 11. Common mistakes to avoid

### Don't break the architecture rule
The temptation will be high. Resist. If the wiring is awkward, the
fix is usually a new config flag, a new DI seam, or a new class. Not
an `if`.

### Don't forget mesh.start() in tests with real ZmqMesh
Monitor doesn't own mesh lifecycle. If you write an integration test
with `ZmqMesh` and forget to call `mesh_a.start()` before
`monitor_a.start()`, the test will hang on receive.

### Don't use `subprocess.Popen` without tracking handles
`DefaultProcessRunner` tracks handles per uav_id. Never use
`pkill -f "px4.*-i 1"` — pattern matching can hit unrelated processes.

### Be careful with SecurityEvent fields
- `severity` is in `{low, medium, high}` (not "critical")
- No `reason` field on `SecurityEvent` — that's on `IsolationAnnounce`
- `evidence` is the dict for raw values

### AttackEvent uses `attack_type`, not `attack_name`
Got bitten once. The injector's `name` property maps to `attack_type=`
keyword in AttackEvent. Don't conflate.

### Attack phases are `inject_start` / `inject_end`
The runner emits `inject_start` after fire() and `inject_end` after
the observation window. The events.py comment mentions `inject_active`
as a possibility, but the runner uses only the two end markers.
Analyzer keys MTTD off `inject_start`.

### `attacker_sysid` MUST be outside `{1, 2, 3, 255}`
Otherwise `CommandInjectionDetector` won't flag it as spoofed and the
attack produces a null result. Defaults to 99. Constructor enforces.

### MAVSDK connection-per-call is intentional
`DefaultMavsdkRunner`, `DefaultGpsSpoofingRunner`,
`MavsdkDroneController` all create short-lived `System()` instances.
Don't try to "optimize" by sharing — the asyncio loop lifetime in
`asyncio.run()` per recovery makes that complicated.

### `sudo -n` for iptables in CI
`SubprocessIptablesRunner` uses `sudo -n` (non-interactive). If sudo
asks for password, the command fails. Either configure passwordless
sudo or use CAP_NET_ADMIN.

### PX4 cold start is slow
`ProcessSpec.start_timeout_sec=8.0` may need bumping on slower
hardware. If MTTR measurements look weird, check whether PX4 actually
came back up within the timeout.

### Disk fills fast
PX4 SITL writes ulog files to `rootfs/<instance>/log/`. Each run can
be 100–200 MB. Run counts × 3 instances × 200 MB = problem.
Clean before each batch.

### Don't bypass `present_files`
The user can't see files in `/home/claude/csma_poc_v2/` directly.
After every step:
1. Copy from sandbox to `/mnt/user-data/outputs/csma_poc_v2/`
2. Call `present_files` listing the staged paths
3. Tell user the exact source paths and expected pytest count

---

## 12. How to continue (handoff to step 10)

Assuming a new chat starts with this repo cloned and this file read:

1. **Acknowledge the state.** "422 passing tests, all non-PX4 code
   complete, ready for step 10 — first live integration run."

2. **Set up sudo / CAP_NET_ADMIN.** Before any iptables-based attack
   can fire, either:
   - Add `youruser ALL=(ALL) NOPASSWD: /usr/sbin/iptables` to sudoers, OR
   - `sudo setcap cap_net_admin+ep $(realpath $(which python3))` on
     the venv interpreter

3. **Write a step-10 integration script.** Something like
   `scripts/run_one.py` that:
   - Takes architecture and attack name as CLI args
   - Calls `build_fleet` + `ExperimentRunner.run()`
   - Reports the run directory at exit

4. **First combo to try**: Architecture C + comm_disruption.
   Simplest because iptables is binary (heartbeat dies = detected).
   Watch for:
   - **Port conflict** on 14540: telemetry listener binds (udpin)
     and MAVSDK connects (udp://) on same port. May need to use
     different MAVSDK port (PX4 SITL default has both 14540 and 14580
     available; check `mavlink start` config in PX4 startup script).
   - **Mesh peer connection timing**: ZmqMesh slow-joiner workaround
     gives 0.3s window. May need bigger window if startup is slow.
   - **Home position GPS lock**: `MavsdkDroneController.get_home_position`
     waits for `telemetry.home()` — may hang if GPS isn't ready
     within timeout. Add deadline.

5. **Once one combo works**, scale to the 3×3 matrix (step 11), then
   to the full experiment (step 12). Analyzer is ready — point it at
   the results directory and it'll produce the Chapter 5 numbers.

6. **Not yet wired**:
   - Resource overhead (CPU%/RAM) sampling via psutil
   - `metrics/plots.py` for matplotlib graphs (only JSON summary right
     now)

If anything in this document feels incomplete or contradicts what you
see in code, the **code is authoritative**. This file is a navigation
aid, not a spec.

---

## Quick-reference

- Sandbox: `/home/claude/csma_poc_v2/`
- Output staging: `/mnt/user-data/outputs/csma_poc_v2/`
- Repo (user's): `~/csma_poc_v2/`
- Run tests: `python -m pytest tests/ -q | tail -3`
- Expected count: **422 passed**
- Smoke test: `python scripts/smoke_telemetry.py` (needs live PX4)

End of handoff document.
