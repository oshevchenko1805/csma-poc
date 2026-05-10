# PROJECT_STATE.md — Full Handoff

This is the onboarding document for a new chat picking up this work.
Read this **before** doing anything else. The repo + this file
together contain everything needed to continue.

---

## 1. Executive summary

**Project**: PhD dissertation practical implementation. A multi-UAV
swarm cybersecurity PoC evaluating a self-healing Cybersecurity Mesh
Architecture (CSMA) against two baselines.

**Status**: Structural code complete (steps 5–8.6b). **326 tests
passing**. The remaining work is concrete attack injection and live
PX4 SITL integration runs.

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
│  Runners (Monitor, Coordinator)                  │
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
| `mesh_factory` (factory.py) | ZmqMesh/NoOpMesh | `RecordingMesh` |
| `ProcessRunner` (restart.py) | `subprocess.Popen` | `FakeProcessRunner` |
| `MavsdkRunner` (loiter.py) | real MAVSDK with lazy import | `FakeMavsdkRunner` |
| `MissionRunner` (missions.py) | (TBD) MavsdkMissionRunner | `NullMissionRunner` |
| `AttackInjector` (attacks/base.py) | concrete attacks (step 9) | `RecordingInjector`, `NullAttackInjector` |

---

## 4. What's done (completed steps)

### Step 5: Foundation
- `core/events.py` — `BaseEvent` + 8 typed event dataclasses with
  registry: `TelemetryEvent`, `SecurityEvent`, `IsolationAnnounce`,
  `RecoveryRequest`, `RecoveryAck`, `AttackEvent`, `MissionEvent`,
  `PeerPositionAnnounce`
- `core/logger.py` — JSONL `EventLogger` (thread-safe), `read_jsonl`,
  `merge_jsonl` for post-hoc analysis
- `core/mesh.py` — `MeshBus` ABC + `NoOpMesh` + `ZmqMesh` (PUB/SUB,
  brokerless, with slow-joiner workaround)
- `core/telemetry.py` — `TelemetryListener` with sysid+type whitelist,
  injects `_src_sysid` into `event.data`
- `core/config.py` — typed config loader (`ArchitectureConfig`,
  `ExperimentConfig`) with strict invariants
- 4 YAML configs: `configs/{architecture_a,b,c,experiment}.yaml`
- `scripts/smoke_telemetry.py` — live PX4 SITL verification

### Step 6: Detectors
- `detectors/base.py` — `Detector` ABC with `feed`/`tick`/`reset`
- `detectors/heartbeat.py` — 3s timeout default, hysteresis (recovery
  cycles before re-fire)
- `detectors/command.py` — sysid whitelist `{1, 2, 3, 255}`, no
  hysteresis (every spoofed command fires)
- `detectors/gps.py` — EKF `pos_horiz_ratio > 1.0` sustained 3
  samples (≈3s with 1Hz ESTIMATOR_STATUS)
- `detectors/cross_check.py` — does **NOT** inherit `Detector` (it
  has a different contract `feed_peer_position`); haversine distance
  + kinematic feasibility per peer

### Step 7: Decision + enforcement
- `decision/isolation.py` — severity threshold, dedup,
  un_isolate/reset, detector→reason mapping
- `decision/recovery.py` — `REASON_TO_ACTION` table (heartbeat_loss →
  restart_process, command_injection → filter_commands, gps_anomaly →
  mode_loiter, cross_check_anomaly → mode_loiter); `enabled` flag for
  A/B
- `enforcement/isolation.py` — `IsolationEnforcer` ABC +
  `LocalIsolationEnforcer` (for A/B) + `MeshAnnouncingIsolationEnforcer`
  (for C). **Composition, not inheritance.**
- `enforcement/recovery.py` — `RecoveryExecutor` async dispatcher,
  `ActionHandler` ABC, structured error codes, never raises

### Step 8: Runners (the big one)

**8.1 Monitor — observation only.** Single-UAV scope, listener+tick
threads under `detector_lock`, `log_telemetry` default False, buggy
detector exceptions swallowed.

**8.2 Monitor + isolation.** Added optional `IsolationDecider` +
`IsolationEnforcer`. Pipeline: SecurityEvent → log → decider → enforcer
→ log. Cross-field invariant: enforcer requires decider; decider
without enforcer is OK (diagnostic mode).

**8.3 Monitor + mesh.** Added optional `mesh` + `CrossCheckDetector`.
Peer-position publisher daemon thread reads last GLOBAL_POSITION_INT,
publishes `PeerPositionAnnounce` every `peer_publish_period_sec`.
CrossCheck requires mesh; mesh without cross_check is allowed.
**CRITICAL**: monitor does **NOT** call `mesh.start()/stop()` — caller's
responsibility so mesh can be shared with coordinator.

**8.4 Coordinator.** Three-role object subscribed to mesh:
- **Election** (peer_position liveness, lowest-alive-sysid)
- **Coordinator** (isolation → RecoveryRequest if elected)
- **Target** (recovery_req → executor → RecoveryAck)

All subscribe to `recovery_ack` → `decider.mark_recovered` + optional
`on_recovery_completed(uav_id, success)` callback.

**PoC simplification**: `asyncio.run()` per recovery (short-lived
loop). Adequate for sync handlers; may need refactor to long-lived
loop with `run_coroutine_threadsafe` if persistent MAVSDK gRPC is
required. Documented.

**8.5 Real ActionHandlers.**
- `enforcement/handlers/restart.py` — `RestartProcessHandler` +
  `ProcessSpec` (frozen dataclass) + `ProcessRunner` ABC +
  `DefaultProcessRunner` via `subprocess.Popen` with tracked handles.
  **No `pkill` pattern matching.**
- `enforcement/handlers/loiter.py` — `ModeLoiterHandler` +
  `MavsdkRunner` ABC + `DefaultMavsdkRunner` with **lazy mavsdk
  import** (tests don't need mavsdk installed). `action.hold()` = PX4
  LOITER
- `enforcement/handlers/filter.py` — `FilterCommandsHandler`, state-only
  with thread-safe `set`. **PoC simplification** — real deployment
  would be iptables / mavlink-router

**8.6a Factory.** `runners/factory.py`. Reads architecture + experiment
configs, produces `WiredFleet` (monitors, coordinators, meshes, log_dir,
filter_handlers). **No side effects**: doesn't start threads/sockets.
DI seams for `connection_factory` and `mesh_factory`. Architecture-C
build wires the on_recovery_completed callback to lift local enforcer
+ un_isolate local decider on success.

**8.6b Experiment runner.** `runners/experiment.py`. Drives full
lifecycle: build_fleet → mesh.start → monitor.start → coordinator.start
→ mission start → wait attack_at_sec → fire → wait observation_after_attack_sec
→ teardown (reverse order) → merge logs → write run_summary.json →
return RunResult. **Cleanup ALWAYS runs** (try/finally).

Also delivered: `attacks/base.py` (`AttackInjector` ABC +
`NullAttackInjector` + `AttackContext`), `runners/missions.py`
(`MissionRunner` ABC + `NullMissionRunner`).

---

## 5. What's not done (steps 9–12)

### Step 9 — Attack injection modules
Three concrete classes implementing `AttackInjector`:

- **`attacks/comm_disruption.py`** — `iptables -A INPUT -p udp --dport
  14540+i -j DROP` on fire, delete rule on cleanup. Requires sudo or
  CAP_NET_ADMIN. Easiest of the three.
- **`attacks/command_injection.py`** — open a MAVLink socket,
  periodically send `COMMAND_LONG` (e.g. `MAV_CMD_DO_REPOSITION`)
  with spoofed sysid (something **outside** `{1, 2, 3, 255}`). Loop
  in a background asyncio task; cancel on cleanup.
- **`attacks/gps_spoofing.py`** — riskiest. Options ordered by
  reliability:
  1. PX4 `param set SIM_GPS_NOISE_*` via MAVSDK — moves the GPS
     reading enough to push EKF residuals over threshold
  2. Direct `HIL_GPS` message injection via MAVLink (need to disable
     real GPS first)
  3. Gazebo plugin manipulation — most realistic but hardest

  Recommend starting with option 1.

For each: write a test using a fake transport (no real iptables / no
real MAVLink socket) verifying arm/fire/cleanup behavior. Then a
single live integration test in step 10.

### Step 10 — First end-to-end integration test
Pick the simplest combo: Architecture C + comm_disruption +
real PX4 SITL. Verify:
- Three PX4 instances launch
- Three monitors connect, see telemetry
- Mesh peers reach each other (cross_check fires when ground-truth
  positions diverge)
- iptables drops UAV-0 heartbeat
- Monitor on UAV-0 detects heartbeat_loss within ~3s
- Mesh propagates IsolationAnnounce
- Coordinator on UAV-1 (lowest alive sysid) emits RecoveryRequest
- RestartProcessHandler runs on UAV-0
- New PX4 instance starts, heartbeats resume
- RecoveryAck published, all peers `un_isolate(uav_0)`

Almost certainly there will be timing / port-conflict / pose-offset
issues to discover and fix here. Allow several iterations.

Also needs **`MavsdkMissionRunner`** — concrete `MissionRunner` that
flies all three UAVs through the coordinated waypoint pattern from
`configs/experiment.yaml::mission.waypoints`. This is new code, not
yet written.

### Step 11 — 3×3 matrix smoke
For each (architecture, attack) combo: run one trial. 9 total. Sanity
that nothing crashes catastrophically. Not full statistics yet.

### Step 12 — Full experiment + analyzer
100 runs per architecture (10 baseline + 30 per attack class × 3 =
100). Roughly 30 wall-hours of SITL time. Then:

- `metrics/analyzer.py` — reads all `merged.jsonl` files, computes:
  - **MTTD** = first `SecurityEvent.timestamp` − `AttackEvent(inject_start).timestamp`
    matching the same target_uav
  - **MTTR** = first `RecoveryAck(success=True).timestamp` for
    target_uav − `IsolationAnnounce.timestamp` for same UAV
  - **Impact scope** = number of UAVs that emitted any
    SecurityEvent (or some richer mission-state metric)
  - **False positive rate** = SecurityEvents in baseline (no-attack) runs
  - **False negative rate** = (attack runs - runs with matching
    SecurityEvent) / attack runs
  - **Resource overhead** = aggregate CPU%/RAM during run (gather
    via `psutil` in experiment runner — not yet implemented)
- Outputs: tables + plots for Chapter 5

---

## 6. File inventory (everything currently in repo)

```
csma_poc_v2/
├── README.md
├── PROJECT_STATE.md (this file)
├── .gitignore
├── requirements.txt
│
├── core/
│   ├── events.py          BaseEvent + 8 typed events with registry
│   ├── logger.py          EventLogger (JSONL, thread-safe), read_jsonl, merge_jsonl
│   ├── mesh.py            MeshBus ABC, NoOpMesh, ZmqMesh
│   ├── telemetry.py       TelemetryListener (sysid+type whitelisting)
│   └── config.py          Typed config loader with invariants
│
├── configs/
│   ├── architecture_a.yaml   Centralized (single GS monitor, no mesh, no recovery)
│   ├── architecture_b.yaml   Distributed (per-UAV monitors, no mesh, no recovery)
│   ├── architecture_c.yaml   CSMA + self-healing (mesh + coordinator + recovery)
│   └── experiment.yaml       Mission, telemetry endpoints, attacks list, run counts
│
├── detectors/
│   ├── base.py            Detector ABC
│   ├── heartbeat.py       3s timeout + hysteresis
│   ├── command.py         sysid whitelist {1, 2, 3, 255}
│   ├── gps.py             EKF pos_horiz_ratio > 1.0 sustained 3 samples
│   └── cross_check.py     Peer-position kinematic feasibility (separate contract)
│
├── decision/
│   ├── isolation.py       IsolationDecider: severity threshold, dedup
│   └── recovery.py        RecoveryDecider: REASON_TO_ACTION table, dedup
│
├── enforcement/
│   ├── isolation.py       IsolationEnforcer ABC, LocalIsolationEnforcer,
│   │                      MeshAnnouncingIsolationEnforcer
│   ├── recovery.py        RecoveryExecutor (async), ActionHandler ABC
│   └── handlers/
│       ├── __init__.py    Re-exports all three handlers
│       ├── restart.py     RestartProcessHandler + ProcessRunner ABC + Default
│       ├── loiter.py      ModeLoiterHandler + MavsdkRunner ABC + Default
│       └── filter.py      FilterCommandsHandler (state only, PoC simplification)
│
├── runners/
│   ├── __init__.py        Empty
│   ├── monitor.py         Single-UAV Monitor (8.1 + 8.2 + 8.3)
│   ├── coordinator.py     Election + recovery orchestrator (8.4)
│   ├── factory.py         Configs → WiredFleet (8.6a)
│   ├── missions.py        MissionRunner ABC + NullMissionRunner (8.6b)
│   └── experiment.py      ExperimentRunner + RunResult (8.6b)
│
├── attacks/
│   ├── __init__.py        Re-exports ABC + Null
│   └── base.py            AttackInjector ABC + NullAttackInjector + AttackContext
│
├── scripts/
│   └── smoke_telemetry.py Live PX4 SITL verification of TelemetryListener
│
└── tests/                 21 test files, 326 tests total
```

---

## 7. Test count timeline (sanity check on history)

```
55 → 83 → 100 → 122 → 143 → 164 → 200 → 218 → 231 → 244
→ 252 → 259 → 278 → 296 → 312 → 326 (current)
```

| Increment | What was added |
|-----------|----------------|
| 55 → 83 | Step 5 foundation (events, logger, mesh, telemetry, config) |
| 83 → 164 | Step 6 detectors (heartbeat, command, gps, cross_check) |
| 164 → 231 | Step 7 (deciders + enforcers) |
| 231 → 244 | 8.1 monitor observation |
| 244 → 252 | 8.2 monitor + isolation |
| 252 → 259 | 8.3 monitor + mesh + cross_check |
| 259 → 278 | 8.4 coordinator |
| 278 → 296 | 8.5 real action handlers |
| 296 → 312 | 8.6a factory |
| 312 → 326 | 8.6b experiment runner |

If pytest count drops after a change, something broke. Quick sanity:
`python -m pytest tests/ -q | tail -3`.

---

## 8. Key design decisions with rationale

### Why `cross_check` doesn't inherit `Detector`
Detectors take `TelemetryEvent`s (own UAV's telemetry). CrossCheck
takes `PeerPositionAnnounce`s (other UAVs' positions from mesh). Two
different contracts → two different interfaces. Forcing inheritance
would have created a confusing `feed()` semantics. Cross_check is
wired separately on `Monitor` via `cross_check=` constructor param.

### Why mesh lifecycle is caller-owned
Mesh can be shared between Monitor (publishes peer_position) and
Coordinator (subscribes to isolation, recovery_req, recovery_ack)
in the same process. If Monitor owned mesh.start/stop, the coord
would not see early subscriptions. By making the caller (factory or
experiment_runner) own the lifecycle, one mesh instance can serve
multiple subscribers correctly.

### Why `asyncio.run()` per recovery in coordinator
Tradeoff. Pros: simple, no long-lived loop to manage, no thread
ownership issues. Cons: ~1s overhead per call (loop creation + MAVSDK
connect), no shared MAVSDK connection across recoveries.

For the PoC this is acceptable and explicit in Chapter 4. If a single
run needs many recoveries on the same UAV (unlikely given the attack
model), refactor to `asyncio.run_coroutine_threadsafe` against a
long-lived loop in a dedicated thread. Module docstring documents
both paths.

### Why ProcessSpec hardcoded in factory
The Architecture C factory needs to know how to relaunch each PX4
instance. Hardcoding (`~/PX4-Autopilot/build/px4_sitl_default/bin/px4
-i <instance>` with `PX4_SYS_AUTOSTART=4001`, `PX4_GZ_MODEL=x500`,
spaced poses) matches the user's specific setup.

If running elsewhere: pass `px4_path=` parameter, or override the
factory's `_default_process_spec` function. Tests don't exercise this
(they use FakeProcessRunner).

### Why three sysids `{1, 2, 3, 255}`
Per PX4 convention: 1, 2, 3 are the UAV autopilot sysids
(instance+1); 255 is the GCS (QGroundControl, MAVSDK in some
configurations). Anything else is an attacker.

### Why severity threshold is "high" in IsolationDecider
A `medium` severity means "anomalous but not necessarily an attack".
Isolating on medium would trigger false positives during normal SITL
startup transients. Threshold of `high` means we isolate only when
the detector is confident enough. This is configurable per-decider
in case future detectors emit different severities.

---

## 9. PoC simplifications (for Chapter 4)

These are intentional gaps between PoC and a production deployment.
**Document each in Chapter 4** with reasoning. Reviewer-proofing.

| Simplification | Real deployment would be | Impact |
|----------------|--------------------------|--------|
| ZeroMQ TCP loopback | FANET radio mesh | Same PUB/SUB semantics, different physical channel + latency profile |
| `subprocess.Popen` kill+restart | Hot-failover / mission resume | MTTR dominated by PX4 cold start (~5–8s). **Decompose MTTR in Ch. 5**: detection / isolation / action / stable phases |
| `FilterCommandsHandler` state-only | iptables / mavlink-router | Real adds ~10–50 ms apply latency. Document in MTTR breakdown |
| MAVSDK connection-per-call | Persistent gRPC connection | ~1 s overhead per loiter recovery. Acceptable for PoC |
| Single-VM deployment via IPC | Distributed companion computers | Network latency between detection and isolation is loopback, not WiFi |
| Wall-clock timestamps | NTP/PTP-synced clocks | Single VM = coherent clocks "for free". In real deployment add ±10–100 ms clock skew |
| GPS spoofing via SIM_GPS_NOISE | Real RF GPS spoofer | Approximation of effect, not method |
| MTTD floor = 3 s for GPS | (Physical lower bound is whatever EKF takes) | PX4 streams `ESTIMATOR_STATUS` at 1 Hz; detector needs 3 samples. **This is a tool limit, not the architecture's fundamental limit.** |
| `asyncio.run()` per recovery | Long-lived event loop in coordinator | OK for sync handlers (subprocess/iptables); may bite with persistent MAVSDK in some configs |
| 3 UAVs | 5–7 UAVs per dissertation generalized model | Document the gap. The PoC uses 3 for resource reasons; the architecture scales — Ch. 4 explains |

The dissertation's framing: **the architectural model is the
contribution**, the PoC validates that the model can be implemented
and that the metrics are meaningful. Limitations of the PoC are not
limitations of the architecture.

---

## 10. Environment specs

### Host system
- **Hardware**: Apple M4 Pro Mac
- **VM**: UTM running Ubuntu 22.04 ARM64
- **VM disk**: 30 GB (clean up PX4 logs regularly: `rm -rf
  ~/PX4-Autopilot/build/px4_sitl_default/rootfs/*/log/`)
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

---

## 11. Common mistakes to avoid

### Don't break the architecture rule
The temptation will be high. Resist. If the wiring is awkward, the
fix is usually a new config flag, a new DI seam, or a new class. Not
an `if`.

### Don't forget mesh.start() in tests with real ZmqMesh
Monitor doesn't own mesh lifecycle. If you write an integration test
with `ZmqMesh` and forget to call `mesh_a.start()` before
`monitor_a.start()`, the test will hang on receive. Already burned
once in 8.3 testing.

### Don't use `subprocess.Popen` without tracking handles
`DefaultProcessRunner` tracks handles per uav_id. Never use
`pkill -f "px4.*-i 1"` — pattern matching can hit unrelated
processes. Already documented in `handlers/restart.py`.

### Be careful with SecurityEvent fields
- `severity` is in `{low, medium, high}` (not "critical")
- No `reason` field on `SecurityEvent` — that's on `IsolationAnnounce`
- `evidence` is the dict for raw values

### AttackEvent uses `attack_type`, not `attack_name`
Got bitten by this in 8.6b testing. The injector's `name` property
maps to `attack_type=` keyword in AttackEvent. Don't conflate.

### Phases are `inject_start` / `inject_active` / `inject_end`
Not `armed` / `fired` / `ended`. Defined as comment in
`core/events.py::AttackEvent`. The runner emits `inject_start` after
fire() and `inject_end` after the observation window.

### PX4 cold start is slow
`ProcessSpec.start_timeout_sec=8.0` may need bumping on slower
hardware. If MTTR measurements look weird, check whether PX4 actually
came back up within the timeout.

### Disk fills fast
PX4 SITL writes ulog files to
`rootfs/<instance>/log/`. Each run can be 100–200 MB. Run
counts × 3 instances × 200 MB = problem. Clean before each batch.

### Don't bypass `present_files`
The user can't see files in `/home/claude/csma_poc_v2/` directly.
After every step:
1. Copy from sandbox to `/mnt/user-data/outputs/csma_poc_v2/`
2. Call `present_files` listing the staged paths
3. Tell user the exact source paths and expected pytest count

---

## 12. How to continue (handoff to step 9)

Assuming a new chat starts with this repo cloned and this file read:

1. **Acknowledge the state.** "326 passing tests, structure complete,
   ready for step 9 (attack injection)."
2. **Pick the easiest attack first.** comm_disruption is just iptables
   + a delete on cleanup. Write `attacks/comm_disruption.py` with the
   `AttackInjector` contract. Test with a `FakeIptablesRunner` DI
   seam so unit tests don't need sudo.
3. **Step-by-step, as before.** One attack class per turn, test it,
   ship it. After all three are done, step 10 = first real integration
   run.
4. **The hard part of step 10 will be MavsdkMissionRunner.** Need to
   connect to 3 PX4 instances concurrently, upload waypoints, takeoff,
   loiter at altitude, mission resume after recovery. Plan ahead.
5. **Resource overhead measurement (step 12).** Not yet wired. Add
   `psutil` sampling thread to ExperimentRunner that records CPU%/RAM
   per process every 1s to a `resources.jsonl` log.

If anything in this document feels incomplete or contradicts what you
see in code, the **code is authoritative**. This file is a navigation
aid, not a spec.

---

## Quick-reference

- Sandbox: `/home/claude/csma_poc_v2/`
- Output staging: `/mnt/user-data/outputs/csma_poc_v2/`
- Repo (user's): `~/csma_poc_v2/`
- Run tests: `python -m pytest tests/ -q | tail -3`
- Expected count after 8.6b: **326 passed**
- Smoke test: `python scripts/smoke_telemetry.py` (needs live PX4)

End of handoff document.
