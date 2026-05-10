# PROJECT_STATE.md

Context handoff document for new chat sessions. Read this first if you
are picking up where the previous session left off.

## Where we are

**Step 8.6a complete.** Structural code for the PoC is essentially
finished. 312 unit + integration tests passing.

```
✅ Step 5  Foundation: events, logger, mesh, telemetry, config
✅ Step 6  Detectors: heartbeat, command, gps, cross_check
✅ Step 7  Decision + enforcement: isolation, recovery
✅ Step 8  Runners:
   ✅ 8.1  Monitor (observation-only)
   ✅ 8.2  Monitor + isolation pipeline
   ✅ 8.3  Monitor + mesh (peer publisher + cross-check subscriber)
   ✅ 8.4  Coordinator (election + recovery orchestration)
   ✅ 8.5  Real ActionHandlers (restart, loiter, filter)
   ✅ 8.6a Factory (configs → wired fleet)
⏳ 8.6b Experiment runner (lifecycle + mission + attack injection)
⏳ Step 9   Attack injection modules
⏳ Step 10  First end-to-end integration test (Arch C + comm_disruption)
⏳ Step 11  3×3 architecture×attack matrix smoke
⏳ Step 12  Full 100-runs-per-arch experiment + analyzer
```

## Working style (preserve in new chats)

- Russian throughout. Кратко и по сути, no filler.
- Step-by-step, one micro-step per turn. After each step: stage files,
  user copies and runs `pytest`, confirms count.
- File workflow: claude writes to `/home/claude/csma_poc_v2/`, runs
  pytest, stages to `/mnt/user-data/outputs/csma_poc_v2/`, presents
  via `present_files`.
- User wants PhD-quality (no shortcuts, no hacks). Document all PoC
  simplifications explicitly — they go in Chapter 4.

## Architectural discipline (do not violate)

The single most important design principle:

> **Architecture difference is deployment, not code branches.**
> No `if architecture == 'A'` in domain code. Differences are
> expressed via config (yaml) + dependency injection.

Concretely:
- Detectors: pure (no I/O)
- Deciders: pure state machines (no I/O)
- Enforcers + Handlers: side effects with DI seams
- Factory picks the right components for each architecture

If you find yourself wanting to write `if architecture == ...` in
`detectors/`, `decision/`, or `runners/monitor.py` — stop. The right
answer is a config switch or a different DI choice.

## Environment

- **OS**: Ubuntu 22.04 ARM64 in UTM VM (Apple M4 Pro Mac host)
- **Python**: 3.10.12 (venv at `~/csma_poc_v2/.venv`)
- **PX4**: `~/PX4-Autopilot`, SITL + Gazebo
- **MAVSDK**: lazy-imported in `enforcement/handlers/loiter.py`
- **Mesh**: ZeroMQ PUB/SUB brokerless (`pyzmq`)
- **Disk**: 30 GB partition. Periodically clean PX4 logs:
  `rm -rf ~/PX4-Autopilot/build/px4_sitl_default/rootfs/*/log/`

### Verified telemetry stream rates (live SITL smoke test)

- HEARTBEAT 1 Hz  ← detection-loss timeout floor for `heartbeat`
- ESTIMATOR_STATUS 1 Hz  ← **MTTD floor for GPS spoofing = ~3 s**
  (PX4 stream rate limit, not detector limitation — document in Ch. 4)
- GLOBAL_POSITION_INT 49.8 Hz
- ATTITUDE 99.5 Hz
- GPS_RAW_INT 30 Hz
- LOCAL_POSITION_NED 30 Hz
- SYS_STATUS 5 Hz

### Process layout

| UAV | PX4 instance | sysid | MAVLink endpoint | MAVSDK endpoint |
|-----|--------------|-------|------------------|-----------------|
| uav_0 | `-i 0` | 1 | `udpin:127.0.0.1:14540` | `udp://127.0.0.1:14540` |
| uav_1 | `-i 1` | 2 | `udpin:127.0.0.1:14541` | `udp://127.0.0.1:14541` |
| uav_2 | `-i 2` | 3 | `udpin:127.0.0.1:14542` | `udp://127.0.0.1:14542` |

PX4 launch (configured in `runners/factory.py::_default_process_spec`):
```
PX4_SYS_AUTOSTART=4001 PX4_GZ_MODEL=x500 PX4_GZ_MODEL_POSE="<offset>"
  ./build/px4_sitl_default/bin/px4 -i <instance>
```

## Test count snapshot

312 tests across 17 files. If number drops after changes — something
broke. Quick sanity: `python -m pytest tests/ -q | tail -3`.

## Three representative attacks (in scope)

1. **comm_disruption** — iptables drop rule on UAV's MAVLink port.
   Detected by `HeartbeatDetector` (3 s timeout w/ hysteresis).
2. **command_injection** — MAVLink command with sysid not in
   `{1, 2, 3, 255}`. Detected by `CommandInjectionDetector` (no
   hysteresis — every spoofed command fires).
3. **gps_spoofing** — Approximated via PX4 SITL position
   manipulation. Detected by `GpsSpoofingDetector`
   (`pos_horiz_ratio > 1.0` sustained 3 samples) and by
   `CrossCheckDetector` (peer-position kinematic feasibility).

## Three recovery actions

| Action | Handler | Implementation |
|--------|---------|----------------|
| `restart_process` | `RestartProcessHandler` | `subprocess.Popen` with tracked handles. PoC sim of node hot-restart. |
| `mode_loiter` | `ModeLoiterHandler` | MAVSDK `await drone.action.hold()` |
| `filter_commands` | `FilterCommandsHandler` | State flag only. **Real deployment = iptables/mavlink-router** |

## Known PoC simplifications (Chapter 4 caveats)

These are NOT bugs — they're intentional, documented gaps between
PoC and production. The dissertation describes the generalized
architecture; Chapter 4 enumerates what is full vs simplified:

- **Transport**: ZeroMQ TCP loopback ≠ FANET radio mesh. Same
  PUB/SUB semantics, different physical channel.
- **Recovery time**: subprocess.Popen kill+restart = sim of node
  cold-restart. MTTR dominated by PX4 cold-start time. **Decompose
  in Ch. 5 results**: detection / isolation / action / stable.
- **Filtering**: `FilterCommandsHandler` is state-only. Real deploy
  would invoke iptables / mavlink-router on the host.
- **MAVSDK overhead**: connection-per-call adds ~1 s. Acceptable for
  PoC; document in MTTR breakdown.
- **Deployment**: all on single VM with logical process separation
  via IPC. Real: distributed companion computers.
- **Clocks**: wall-clock timestamps assume coherent clocks (single
  VM). Real: NTP/PTP between companions.
- **MTTD floor**: GPS spoofing detection bounded by 3 s due to
  PX4's ESTIMATOR_STATUS 1 Hz stream rate, not detector logic.
- **Coordinator async**: currently `asyncio.run()` per recovery
  request. May need long-lived loop in step 8.5+ if persistent
  MAVSDK gRPC matters.

## Files written (all in current repo)

```
core/{events,logger,mesh,telemetry,config}.py
configs/{architecture_a,architecture_b,architecture_c,experiment}.yaml
detectors/{base,heartbeat,command,gps,cross_check}.py
decision/{isolation,recovery}.py
enforcement/{isolation,recovery}.py
enforcement/handlers/{__init__,restart,loiter,filter}.py
runners/{__init__,monitor,coordinator,factory}.py
scripts/smoke_telemetry.py
tests/test_*.py  (17 files)
```

## Test-count timeline (sanity check on history)

```
55 → 83 → 100 → 122 → 143 → 164 → 200 → 218 → 231 → 244 → 252
→ 259 → 278 → 296 → 312  (current)
```

## What's next (8.6b)

`runners/experiment.py` — orchestrator that:
1. Reads configs, calls `build_fleet()`
2. Manages lifecycle: `mesh.start()` → `monitor.start()` →
   `coordinator.start()` → fly mission → trigger attack →
   `wait observation_after_attack_sec` → stop in reverse
3. Drives a MAVSDK mission across 3 UAVs (coordinated waypoint)
4. Emits `AttackEvent` ground-truth markers around attack triggers
5. Merges per-monitor JSONLs into `run_<id>/merged.jsonl`
6. Writes `run_summary.json` with counters

Then step 9: attack injection modules.
