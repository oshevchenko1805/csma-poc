# PROJECT_STATE.md — Full Handoff

This is the onboarding document for a new chat picking up this work.
Read this **before** doing anything else. The repo + this file
together contain everything needed to continue.

---

## 1. Executive summary

**Project**: PhD dissertation practical implementation. A multi-UAV
swarm cybersecurity PoC evaluating a self-healing Cybersecurity Mesh
Architecture (CSMA) against two baselines.

**Status**: **Step 10a complete with first real metrics from live
PX4 SITL.** 438 tests passing. The full security pipeline runs
end-to-end against real PX4 instances: detect → isolate → real
process restart → recovery acknowledgment → un_isolate. Gaps 1 and 2
that surfaced during step 10a are now closed. What remains is step
10b (add MAVSDK mission for active flight) and onwards to the 3×3
matrix and full experiment.

**First real metrics** (Architecture C, comm_disruption, null
mission, single trial against live PX4):
- **MTTD = 2.88 s** — heartbeat timeout (3 s) + dispersion
- **MTTR = 8.07 s** — dominated by `ProcessSpec.start_timeout_sec=8.0`
  (PX4 cold start)
- **detected: true, recovery_success: true** — confirmed by PID inst 0
  changing before vs after the run (real process restart, not just
  ack contract)

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
- **Important: when multi-point diffs are involved, prefer giving the
  user a full replacement file via `present_files` rather than a
  list of N edits.** Past experience: GitHub UI / manual edits lose
  one of the steps every time (e.g. the `_isolated_sysids` field, the
  `log_path` parameter). One atomic file replace is reliable; a
  6-step diff is not.

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
  `MeshAnnouncingIsolationEnforcer`, `DefaultProcessRunner` vs
  `ExternalAwareProcessRunner`)
- **The factory** (`runners/factory.py`) that reads configs and
  picks the right components

If you ever feel like writing `if arch == ...` in domain code: stop.
The right answer is either a config switch, a different DI choice,
or a new class.

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

### DI seams (where fakes plug in for tests)

| Seam | Default | Custom for live PoC |
|------|---------|---------------------|
| `connection_factory` (factory.py) | real pymavlink | `FakeConnection` in tests |
| `mesh_factory` (factory.py) | ZmqMesh / NoOpMesh | `RecordingMesh` in tests |
| `process_runner` (factory.py / experiment.py) | `DefaultProcessRunner` per handler | **`ExternalAwareProcessRunner` for live PoC** (shared across handlers) |
| `ProcessRunner` (restart.py) | `DefaultProcessRunner` | `FakeProcessRunner` in tests |
| `MavsdkRunner` (loiter.py) | real MAVSDK (lazy) | `FakeMavsdkRunner` in tests |
| `IptablesRunner` (comm_disruption) | `subprocess` with sudo | `FakeIptablesRunner` in tests |
| `MavlinkSender` (command_injection) | `PymavlinkSender` (lazy) | `FakeMavlinkSender` in tests |
| `GpsSpoofingRunner` (gps_spoofing) | MAVSDK Param API (lazy) | `FakeGpsSpoofingRunner` in tests |
| `DroneController` (mission_mavsdk) | `MavsdkDroneController` (lazy) | `FakeDroneController` in tests |
| `MissionRunner` (missions.py) | `MavsdkMissionRunner` | `NullMissionRunner` for step 10a |
| `AttackInjector` (attacks/base.py) | concrete attacks | `NullAttackInjector`, `RecordingInjector` |

---

## 4. What's done (completed steps)

### Step 5: Foundation (events, logger, mesh, telemetry, config)
[unchanged from previous PROJECT_STATE]

### Step 6: Detectors (heartbeat, command, gps, cross_check)
[unchanged]

### Step 7: Decision + enforcement
[unchanged]

### Step 8: Runners (Monitor, Coordinator, factory, experiment)
[unchanged]

### Step 9: Attack injectors (comm_disruption, command_injection, gps_spoofing)
[unchanged]

### Step 10a: First live PX4 integration WITHOUT mission ✓ NEW
Closed in this iteration. Detection + isolation + real recovery
verified end-to-end against three live PX4 SITL instances. Mission
runner deliberately deferred to step 10b (port 14540 conflict — see
§13). Architecture C used because it's the one with the value-add.

What was added in this step:

- **`scripts/run_one.py`** — CLI driver for one experiment trial.
  Flags: `--arch a|b|c`, `--attack none|comm_disruption|command_injection|gps_spoofing`,
  `--mission mavsdk|null`, `--target-uav`, `--attack-at-sec`,
  `--observation-after-attack-sec`, `--px4-pid-file`, `--dry-run`.
  Reads the PID file written by `launch_px4.sh` and builds an
  `ExternalAwareProcessRunner` so the recovery handler can kill the
  right external PX4.
- **`scripts/launch_px4.sh`** — launches 3 PX4 SITL instances
  (gz_x500) in background. Auto-cleans stale ulog dirs before
  launching (~100-200 MB per instance per run, 30 GB VM fills fast
  otherwise). Writes PIDs in sysid order to `/tmp/px4_pids` (line 1
  = sysid 1, etc.). First instance starts Gazebo; subsequent
  instances attach. Refuses to launch if 14540/41/42 are already
  bound.
- **`scripts/kill_px4.sh`** — clean teardown via the PID file plus
  pkill fallback. Also kills lingering `gz sim` / `gz-sim` /
  `ruby gz` processes.

#### Gap 1 (now closed): recovery events were missing from JSONL

Symptom: `merged.jsonl` contained only `attack`, `security`,
`isolation_announce` — but never `recovery_request` or
`recovery_ack`. The Coordinator published these to the mesh but
had no `EventLogger`, so the analyzer's MTTR computation had no
timestamps to work with.

Fix:
- `Coordinator.__init__` now accepts `log_path: Optional[Path] =
  None`. When provided it owns an `EventLogger` writing to
  `coordinator_<uav>.jsonl`. Logs `RecoveryRequest` after publish
  in `_on_isolation_announce`, and `RecoveryAck` after publish in
  `_on_recovery_request`. Does NOT log received-ack copies (would
  duplicate events on every peer).
- `factory.py::_build_arch_c` passes `log_path=log_dir /
  f"coordinator_{uav}.jsonl"` to each Coordinator.
- `experiment.py::_finalize` already does `log_dir.glob("*.jsonl")`,
  so the new coordinator files merge automatically.

#### Gap 2 (now closed): RestartProcessHandler did no real restart

Symptom: handler returned `success=True` but PIDs in `pgrep` were
unchanged. The recovery measurement was time-to-ack, not
time-to-actual-restart.

Root cause: `DefaultProcessRunner.kill(uav_id)` looks up Popen in
`self._handles`. Live PoC launches PX4 via `launch_px4.sh`, so
those handles were empty → kill() was a silent no-op. Subsequent
start() spawned a SECOND PX4 for the same instance, which crashed
on port 14580 collision. Handler slept `start_timeout_sec` and
returned success while the original PX4 stayed alive untouched.

Fix:
- New class `ExternalAwareProcessRunner` in
  `enforcement/handlers/restart.py`. Constructor takes
  `uav_to_initial_pid` map. First kill() per UAV signals that
  external PID (SIGTERM → optional SIGKILL on timeout). Subsequent
  kill()s use the tracked Popen as usual.
- `RestartProcessHandler` already accepted `runner=` via its
  constructor. `factory.py::_build_arch_c` now passes a shared
  `process_runner` to every per-UAV handler. With a custom runner,
  all 3 handlers share the same instance (required so the
  `ExternalAwareProcessRunner` can hold one PID map covering all
  UAVs).
- `ExperimentRunner.__init__` accepts
  `process_runner: Optional[ProcessRunner] = None`, forwards to
  `build_fleet`.
- `run_one.py` reads `/tmp/px4_pids` (line N → sysid N) and builds
  the `ExternalAwareProcessRunner`. When the file doesn't exist
  (e.g. tests, dry-runs without launch_px4), falls back to default
  — no behaviour change for existing tests.

Verified end-to-end: PID inst 0 changes (e.g. `155247 → 156528`)
across a run with comm_disruption; MTTR rises to ~8 s reflecting
real PX4 cold-start.

#### Architectural improvement: isolation-aware coordinator election

Discovered during step 10a debugging. The first live run produced
zero recovery requests despite a successful isolation. Reason:
`is_coordinator` was based on `peer_position` mesh liveness only,
and the isolated UAV's mesh process kept publishing
`peer_position` (mesh runs on ZMQ port 5550 — unaffected by the
iptables DROP on MAVLink port 14540). So the isolated UAV remained
the elected coordinator (lowest alive sysid) but was, by
definition, unable to coordinate.

Fix in `runners/coordinator.py`:
- New `_isolated_sysids: set[int]`, updated by
  `_on_isolation_announce` BEFORE the is_coordinator check, lifted
  by successful `_on_recovery_ack`.
- `is_coordinator` excludes isolated sysids from the alive set,
  with a fast-path that immediately returns False if our own sysid
  is isolated.
- 6 new unit tests in `TestIsolationAwareElection`.

This closes the trivial recursion where a UAV under attack could
attempt to coordinate its own recovery. Worth a paragraph in
Chapter 3 §3.4 (coordination_integrity property).

### Mission infrastructure (for step 10b)
- `runners/mission_mavsdk.py` exists, tested with FakeDroneController.
  Real MAVSDK integration deferred to step 10b — see §13.

### Step 12 analyzer (verified on first live data)
- `metrics/analyzer.py::analyze_run` produces the metrics shown in
  §1. Confirmed on a real run_dir from a live PX4 experiment.

---

## 5. What's not done

### Step 10b — Add MAVSDK mission to the live integration
Step 10a deliberately ran with `NullMissionRunner` (drones stay on
the ground, telemetry still streams). Step 10b adds active flight
via `MavsdkMissionRunner`. See §13 for the port 14540 conflict that
must be resolved first.

### Step 11 — 3×3 matrix smoke
For each (architecture, attack) combo: 1 trial. 9 total. With
`run_one.py` already in place this is mostly a shell loop. Sanity
that nothing crashes catastrophically across architectures.

### Step 12 (runs portion) — Full experiment + plots
- Run the experiment (100 trials per cell, ~30 wall-hours of SITL)
- Run analyzer over results (analyzer code is done)
- Generate plots for Chapter 5 (matplotlib code not yet written —
  add `metrics/plots.py`)
- Optional: add `psutil` sampling for resource overhead

### Open issues / nice-to-haves
- **MTTR breakdown**: analyzer reports total MTTR but not the
  decomposition (T_detect_to_isolate / T_isolate_to_decide /
  T_action_execute). With Gap 1 closed all timestamps are now in
  the JSONL chain — wiring this up is a 1-hour task in
  `metrics/analyzer.py`. Useful for Chapter 5.
- **`/tmp/px4_pids` becomes stale after a recovery**: after
  `ExternalAwareProcessRunner` restarts a PX4, the PID file still
  contains the OLD PID. Not a problem within one experiment run
  (the runner tracks the fresh Popen internally), but a subsequent
  `kill_px4.sh` will reference dead PIDs and the next
  `launch_px4.sh` reads stale data. Re-run `launch_px4.sh` if you
  want the PID file refreshed.
- **iptables stale rules**: if a run crashes mid-attack, the DROP
  rules stay. `comm_disruption` cleanup() is best-effort. Always
  inspect with `sudo iptables -L INPUT -n | grep DROP` before a
  fresh run; remove any leftovers (both `--dport` and `--sport`
  variants — we saw both in practice).
- **Disk fills extremely fast**: 30 GB VM, ulog per instance per
  run = 100-200 MB. Three instances × ten runs = 4.5-6 GB. The
  auto-cleanup in `launch_px4.sh` only catches ulogs from the
  PREVIOUS launches; if you run experiments without re-launching
  PX4, ulogs accumulate inside the running PX4 processes.

---

## 6. File inventory (updated)

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
│   └── base.py + heartbeat.py + command.py + gps.py + cross_check.py
│
├── decision/                    (pure deciders)
│   └── isolation.py + recovery.py
│
├── enforcement/                 (side effects)
│   ├── isolation.py
│   ├── recovery.py
│   └── handlers/
│       ├── __init__.py          ★ NEW: exports ExternalAwareProcessRunner
│       ├── restart.py           ★ NEW: ExternalAwareProcessRunner class
│       ├── loiter.py
│       └── filter.py
│
├── runners/                     (orchestrators)
│   ├── __init__.py
│   ├── monitor.py
│   ├── coordinator.py           ★ MODIFIED: log_path, isolation-aware election
│   ├── factory.py               ★ MODIFIED: process_runner DI
│   ├── missions.py
│   ├── mission_mavsdk.py
│   └── experiment.py            ★ MODIFIED: process_runner DI
│
├── attacks/                     (concrete attacks)
│   └── base.py + comm_disruption.py + command_injection.py + gps_spoofing.py
│
├── metrics/                     (analysis)
│   └── analyzer.py
│
├── scripts/                     ★ MOSTLY NEW
│   ├── smoke_telemetry.py
│   ├── run_one.py               ★ NEW: CLI for one experiment trial
│   ├── launch_px4.sh            ★ NEW: launches 3 PX4 SITL instances
│   └── kill_px4.sh              ★ NEW: clean teardown
│
└── tests/                       (438 tests across many files)
    ├── ... (existing test files)
    └── test_handler_restart_external.py  ★ NEW: 10 tests for ExternalAware
```

---

## 7. Test count timeline (updated)

```
55 → 83 → 100 → 122 → 143 → 164 → 200 → 218 → 231 → 244 → 252
→ 259 → 278 → 296 → 312 → 326 → 343 → 359 → 379 → 400 → 422
→ 428 (isolation-aware election, +6) → 438 (ExternalAwareProcessRunner, +10)
```

Quick sanity check: `python -m pytest tests/ -q | tail -3` →
should report **`438 passed`**.

---

## 8. Key design decisions with rationale

[Previous sections unchanged, plus:]

### Why isolation-aware election uses a separate `_isolated_sysids` set
Election was on `_last_seen` (peer_position liveness) only. With
mesh ZMQ on a different port from MAVLink, an isolated UAV stays
mesh-alive forever after a comm_disruption attack — and stays
elected coordinator under the old rule, blocking recovery. The
`_isolated_sysids` set is a separate dimension: a peer is eligible
for election only if it's both alive (recent peer_position) AND
non-isolated. Cleanup happens on RecoveryAck(success=True).

### Why `process_runner` is shared across handlers (not per-handler)
`ExternalAwareProcessRunner` holds a single PID map covering all
UAVs. If each handler had its own runner, only one of them would
know each PID. Sharing one runner makes the PID map accessible to
all three handlers. The cost — losing the ability to inject
different runners per UAV — is hypothetical, never used in
practice.

### Why coordinator logs RecoveryRequest/RecoveryAck only on publish
A `RecoveryAck` published by the target UAV is received via mesh by
all other coordinators too. If each receiver logged it, the merged
file would contain three copies of every ack. Logging only on
publish gives exactly one event per publish, with a
publisher-side timestamp suitable for MTTR. The handler chain in
the analyzer reconstructs full chronology via `caused_by`.

### Why MTTR is bound by PX4 cold-start (academic insight)
First real run gave MTTR = 8.07 s, almost exactly
`ProcessSpec.start_timeout_sec=8.0`. Decomposing:
- T_detect_to_isolate ≈ 0 (Monitor publishes IsolationAnnounce
  immediately after SecurityEvent)
- T_isolate_to_decide ≈ 0 (Coordinator's RecoveryDecider is
  synchronous, mesh latency is loopback)
- T_action_execute ≈ 8.0 s (PX4 binary spawn + ready timeout)

So **MTTR-restart is not architecture-dependent in this PoC** — it's
the PX4 cold-start latency, a fixed lower bound common to all three
architectures. What IS architecture-dependent is MTTD (different
detection mechanisms) and impact_scope (centralized SPOF vs
distributed). Chapter 5 should split MTTR into these components and
honestly note the cold-start floor.

---

## 9. PoC simplifications (for Chapter 4)

[Previous table unchanged]

---

## 10. Environment specs (updated)

### Host system
- **Hardware**: Apple M4 Pro Mac
- **VM**: UTM running Ubuntu 22.04 ARM64
- **VM disk**: 30 GB. **Critically constrained.** Clean PX4 logs
  before each run — `launch_px4.sh` does this automatically. If you
  see "No space left on device", run:
  ```
  rm -rf ~/PX4-Autopilot/build/px4_sitl_default/rootfs/*/log/*
  rm -rf ~/csma_poc_v2/runs/*
  sudo apt clean
  sudo journalctl --vacuum-size=100M
  ```
- **Python**: 3.10.12, venv at `~/csma_poc_v2/.venv`

### PX4 SITL
- **Path**: `~/PX4-Autopilot`
- **Build**: `make px4_sitl gz_x500`
- **Launch**: `scripts/launch_px4.sh` (three instances, Gazebo on
  first, writes PIDs to `/tmp/px4_pids`)
- **Teardown**: `scripts/kill_px4.sh`

### Process layout (3 UAVs) — verified in step 10a
| UAV | PX4 `-i` | sysid | MAVLink in (Monitor) | MAVSDK out (mission, step 10b) |
|-----|----------|-------|----------------------|--------------------------------|
| uav_0 | 0 | 1 | `udpin:127.0.0.1:14540` | `udp://127.0.0.1:14540` |
| uav_1 | 1 | 2 | `udpin:127.0.0.1:14541` | `udp://127.0.0.1:14541` |
| uav_2 | 2 | 3 | `udpin:127.0.0.1:14542` | `udp://127.0.0.1:14542` |

### Live SITL packet flow (observed in step 10a)
PX4 inst i sends MAVLink:
- Normal stream → `udp port 1857{i} → remote port 14550` (QGC channel)
- Onboard stream → `udp port 1458{i} → remote port 1454{i}` (MAVSDK/pymavlink channel)
- Other channels: `1428{i}→1403{i}` (uxrce_dds), `1303{i}→1328{i}` (gimbal)

PX4 is the **sender** on 1454{i}; whoever listens there receives
the stream. Two listeners on the same port = port conflict (see
§13).

### iptables / sudo (Step 10a verified working)
Comm_disruption requires passwordless sudo for iptables:
```bash
sudo visudo -f /etc/sudoers.d/csma-iptables
# Add: youruser ALL=(ALL) NOPASSWD: /usr/sbin/iptables
```

CAP_NET_ADMIN on Python does **not** work for this — `iptables` is
a separate binary, capabilities don't pass through `subprocess`.
Use sudo.

**Watch for stale rules from crashed runs**:
```bash
sudo iptables -L INPUT -n | grep DROP
# If anything remains, remove BOTH --dport and --sport variants:
for port in 14540 14541 14542; do
  while sudo iptables -D INPUT -p udp --dport $port -j DROP 2>/dev/null; do :; done
done
for sport in 14580 14581 14582; do
  while sudo iptables -D INPUT -p udp --sport $sport -j DROP 2>/dev/null; do :; done
done
```

---

## 11. Common mistakes to avoid (updated)

[Previous list, plus:]

### When applying multi-point patches, give a full file replace
We learned this twice: the `_isolated_sysids` initialization went
missing on the first patch, the `log_path` parameter went missing
on the second. Multi-step diffs through GitHub UI / manual edits
lose one step every time. For any change touching > 2 spots in a
single file, hand the user a full replacement file via
`present_files`. One atomic copy is reliable.

### When a new live PX4 setup looks broken, check iptables FIRST
We chased "PX4 inst 2 doesn't send heartbeat" for 30 minutes
before realising the previous comm_disruption run had left
`DROP udp dpt:14542` AND `DROP udp spt:14582` rules. Always
inspect `iptables -L INPUT -n` before debugging UDP receive issues.

### Don't trust pgrep alone to verify "restart happened"
`pgrep` shows PIDs but doesn't reveal whether the handler's
spawned process and the one you're seeing are the same. Capture
PID inst 0 before the run (`head -1 /tmp/px4_pids`) and compare
to `pgrep -f 'px4 -i 0$'` after. If they differ → real restart
happened.

### Gazebo state lingers across PX4 launches
If a previous `launch_px4.sh` was killed un-cleanly, Gazebo can
keep running with its own simulation time accumulated. New PX4
instances then see `lockstep_scheduler] setting initial absolute
time to 95168848000 us` (~26 hours), EKF fails, telemetry breaks.
`launch_px4.sh` and `kill_px4.sh` both attempt cleanup, but if
weirdness persists:
```bash
pkill -9 -f 'gz sim' ; pkill -9 -f 'gz-sim' ; pkill -9 -f 'ruby.*gz'
rm -rf /tmp/.gz* ~/.gz/log/*
```

### Don't worry about `runners/__init__.py` being empty
It is, intentionally. Python's implicit namespace packaging works
fine. Existing imports like `from runners.experiment import
ExperimentRunner` work without anything in `__init__.py`.

---

## 12. How to continue (handoff to step 10b)

Assuming a new chat starts with this repo cloned and this file read:

1. **Acknowledge the state.** "438 tests passing. Step 10a complete:
   detection → isolation → real PX4 restart → ack verified end-to-end
   with first MTTD/MTTR numbers. Step 10b adds MAVSDK mission for
   active flight."

2. **The blocker for step 10b: port 14540 conflict.** See §13 below
   for full options.

3. **Recommended starting combo for 10b**: same as 10a — Architecture
   C + comm_disruption. Once mission works, expand to other attacks.

---

## 13. Step 10b blocker: port 14540 conflict (detailed)

### The problem

PX4 SITL inst 0 sends its onboard MAVLink stream to
`127.0.0.1:14540`. Both of the following need to read from this
port simultaneously, and Linux UDP semantics make that very hard:

1. **Monitor** uses pymavlink with `udpin:127.0.0.1:14540` — binds
   the port and reads.
2. **MAVSDK mission** uses `udp://127.0.0.1:14540` — also binds the
   port (server mode in MAVSDK convention).

In step 10a we bypassed this by using `NullMissionRunner` — only
Monitor binds 14540, MAVSDK is not active. For 10b we need both.

### Options to resolve

**Option A: mavlink-router (recommended).**
Run `mavlink-router` as an intermediate process per UAV. PX4 sends
to mavlink-router; mavlink-router forwards each packet to both
Monitor's port AND MAVSDK's port. The PoC convention would become:

- PX4 inst i sends to a single endpoint (configured by env var or
  PX4 startup script tweak)
- mavlink-router listens, forwards to 14540+i (Monitor) and 14560+i
  (MAVSDK)
- Monitor reads from 14540+i as before
- MavsdkMissionRunner reads from 14560+i

Pros: clean separation; mavlink-router is a known, packaged tool;
no PX4 internals changed. Cons: extra process per UAV (3 more);
extra deployment step.

**Option B: second MAVLink stream from PX4.**
Modify PX4 startup script (`etc/init.d-posix/rcS` or equivalent) to
add a second `mavlink start` command on a different port:
```
mavlink start -x -u $((14560+px4_instance)) -r 4000000 -m onboard
```
Then MavsdkMissionRunner connects to 14560+i. Monitor stays on
14540+i.

Pros: no extra processes. Cons: requires patching the PX4 source's
startup script (or overriding it via `PX4_GZ_STANDALONE` or per-
instance custom rcS), which is fragile across PX4 upgrades.

**Option C: drop pymavlink Monitor in favour of MAVSDK telemetry.**
Rewrite Monitor's telemetry consumption to use MAVSDK's
`drone.telemetry.heartbeat()` etc. Then MAVSDK owns 14540+i alone.

Pros: single MAVLink consumer per UAV. Cons: substantial Monitor
rewrite; gives up pymavlink's wider message coverage; MAVSDK's
telemetry API is less granular for our detector needs (GPS noise,
specific COMMAND_LONG inspection).

**Option D: SO_REUSEPORT.**
Linux allows multiple UDP sockets to bind the same port with
SO_REUSEPORT — the kernel load-balances incoming packets. Neat in
theory, terrible in practice: each socket gets a random subset of
packets. Monitor would miss half the heartbeats, MAVSDK would miss
half the telemetry. Don't use.

### Recommended path: Option A

Steps for a new chat:
1. Install mavlink-router: `apt install mavlink-router` (or build
   from source — recent versions matter for PX4 compatibility).
2. Write a config per UAV that listens on a port PX4 sends to (could
   be 14540+i if we move Monitor & MAVSDK both off it) and forwards
   to two endpoints.
3. Add `scripts/launch_router.sh` analogous to `launch_px4.sh`.
4. Update `experiment.yaml`'s `telemetry.endpoints` to point Monitor
   at one set of ports; update `MavsdkMissionRunner` factory in
   `run_one.py` to use the other set.
5. Smoke test with `--mission mavsdk --attack none` first (real
   flight, no attack). When that flies, add comm_disruption back.

---

## Quick-reference

- Sandbox: `/home/claude/csma_poc_v2/`
- Output staging: `/mnt/user-data/outputs/csma_poc_v2/`
- Repo (user's): `~/csma_poc_v2/`
- Run tests: `python -m pytest tests/ -q | tail -3`
- Expected count: **438 passed**
- Live smoke (no flight): `scripts/launch_px4.sh && python scripts/run_one.py
  --arch c --attack comm_disruption --mission null --attack-at-sec 10
  --observation-after-attack-sec 30`
- Analyze last run: `python -c "from pathlib import Path;
  from metrics.analyzer import analyze_run; from pprint import pp;
  pp(analyze_run(sorted(Path('runs').iterdir())[-1]))"`

End of handoff document.

---

## Step 10b — CLOSED (live MAVSDK mission)

**Status:** §13 port-14540 blocker RESOLVED via Option A (mavlink-router fan-out per UAV). First end-to-end live trial with active 3-UAV flight: MTTD=3.28s, MTTR=8.07s, detected=True, recovery_success=True, impact_scope=1. 438 tests passing.

**See [STEP_10B_NOTES.md](STEP_10B_NOTES.md) for full closeout** — new files, MavsdkDroneController patches (grpc_port + wait_armable), environment changes (VM disk 30→100 GB), known limitations, reproduction commands.

**Pre-flight for next step:** `DefaultMavsdkRunner` (loiter recovery) and `DefaultGpsSpoofingRunner` (GPS attack) still use default gRPC port 50051; will collide with mission controllers (50051-50053). Patch needed before testing `--attack gps_spoofing` or loiter-based recovery action.
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
---

## Step 10e — IN PROGRESS (gps_spoofing, blocker A resolved)

### Blocker A — RESOLVED via GZBridge source patch (variant 3)

Decision: param-manipulation (SIM_GPS_NOISE / SIM_GPS_USED) rejected.
- No noise-amplitude param exists in gz-sim; noise is hardcoded C++ (GZBridge
  addGpsNoise, _pos_noise_amplitude=0.8). Only live param lever is SIM_GPS_USED<4,
  which produces GNSS *denial* (fix loss → pos_h goes nan), NOT falsification.
- Denial ≠ spoofing: thesis Table 3.3 separates them (T0856/T0832 integrity vs
  T0826/T0814 availability). Collapsing spoofing→denial would gut the integrity
  scenario and require rewriting 3.1.6.2 + tables 3.3/3.4 + injection case 1 +
  waypoint section + Ch.5. Rejected.

Chosen: **documented PX4 patch** — param-gated ramped GPS position offset in
GZBridge, giving true residual-divergence (pos_horiz_ratio>1.0) spoofing signature.
Preserves thesis verbatim; needs one honest line in Ch.4 ("PX4 with documented
local GPS-offset injection patch"). Also dissolves blocker B (param written
straight to PX4, no router fan-out).

**Patch location:** `~/PX4-Autopilot/src/modules/simulation/gz_bridge/`
- `parameters.c`: SIM_GPS_OFF_N (0.0), SIM_GPS_OFF_E (0.0), SIM_GPS_OFF_R (0.02 ramp)
- `GZBridge.hpp`: ramp state (_gps_off_n/_gps_off_e) + 3 params in DEFINE_PARAMETERS tuple
- `GZBridge.cpp` (~line 698, after altitude+=_gps_pos_noise_d): ramped offset applied
  to latitude/longitude. Tag `OFFSET_INJECT` on all patched lines.
- Built OK (make clean && make px4_sitl_default; incremental build hit the known
  parameters.json.xz gen glitch → clean rebuild fixed it).

**Status:** patch built, proven HARMLESS — arch-C baseline flies clean on it
(error=null, security_emitted=0 all 3, is_armable OK ×3, full arm→takeoff).
NOT YET committed (PX4 patch lives in separate repo; commit after in-flight verify).

### NOT YET DONE (next session, in order)
1. **In-flight injection unverified.** Offset effect confirmed only conceptually;
   on-ground EKF does NOT fuse horizontal GPS (pos_h=nan, expected). Must inject
   SIM_GPS_OFF_N mid-flight and confirm pos_horiz_ratio ramps >1.0.
2. **Design fork before wiring:** how injector writes SIM_GPS_OFF_N — via router
   (may resurface blocker B) vs straight param_set to PX4. Prefer direct.
3. Wire into GpsSpoofingInjector + **mandatory restore phase** (set OFF_N=0 on
   teardown — see storage lesson below).
4. Live-verify gps_spoofing on arch C.

### CRITICAL LESSON — per-instance param storage pollution
Today's multi-hour rabbit hole root cause: PX4 SITL persists params to
`build/px4_sitl_default/rootfs/{0,1,2}/parameters.bson` (PER-INSTANCE, not the
rootfs-root file we first deleted). Diagnostic param_set probes (SIM_GPS_USED=0,
SIM_GPS_OFF_N=40, SIM_GZ_EN_GPS denormalized) got saved and SURVIVED restarts,
causing is_armable timeouts on some instances → TimeoutError in _wait_armable →
whole gather() run failed. Fix: `rm rootfs/{0,1,2}/parameters*.bson` AFTER killing
all procs, then relaunch.
- Implication: injector MUST restore OFF_N=0, and runs should clean per-instance
  param storage between trials, else offset leaks into next run's baseline.
- Silver lining: per-instance storage is isolated → impact_scope=1 IS achievable
  (offset on uav_0 won't auto-leak to peers at runtime).

### Diagnostic markers added (uncommitted)
`runners/mission_mavsdk.py`: 6 `[mission]` print markers around _wait_armable /
set_takeoff_altitude / arm / takeoff. Made the timeout phase visible. Keep or
strip next session.

439 tests still passing (domain code untouched; only PX4 patch + debug prints).
Step 10e — MECHANISM VERIFIED IN FLIGHT (gps_spoofing)

Status: GZBridge SIM_GPS_OFF_N offset injection produces a real,
sustained ESTIMATOR_STATUS.pos_horiz_ratio > 1.0 on a FLYING drone.
The GpsSpoofingDetector signature is confirmed to be reproducible live.
Both open blockers for step 10e are now closed. Not yet wired into
GpsSpoofingInjector; not yet run through run_one.py.

Live result (standalone test, arch-agnostic, inst 0 only)

Baseline hover (20 m): pos_h ≈ 0.005–0.008 (clean).
After SIM_GPS_OFF_N=50:

t after injectpos_horiz_ratiobaseline~0.006+0.5 s1.169+1.0 … +7.0 s2.000 (clipped)+8.0 s onward~0.004 (back to baseline)


Detection fires at +1.5 s (3 sustained samples > 1.0 @ 2 Hz).
On PX4's default 1 Hz stream this is ~3 s — matches the documented
MTTD floor in detectors/gps.py.
Ratio plateaus at 2.000 because PX4 clips the innovation test ratio
at 2.0; the true residual is higher.
SIM_GPS_OFF_N restored to 0.0 (verified readback). Per-instance
param storage clean.


Physics (honest note for Ch. 4 / Ch. 5)

The detectable signature is the onset transient of the ramp, not a
steady-state offset. SIM_GPS_OFF_R=0.02 ramps the offset to 50 m over
~7 s; while the offset is changing, GPS diverges from the inertial
prediction and the residual spikes (>1.0). Once the offset is static,
EKF re-converges to the shifted position (it now "believes" it is 50 m
north) and the residual falls back to baseline. This is physically
faithful: real GNSS spoofing that walks a target off-course produces a
growing residual only while the position is being pulled. sustained_ samples=3 catches the transient with margin. Implication for attack
timing: the detection/observation window must overlap the ramp phase.
For a longer detectable window, slow the ramp (lower SIM_GPS_OFF_R)
or step the offset target repeatedly.

Blocker resolutions (both closed)


Blocker A (mechanism): RESOLVED earlier via GZBridge source patch
(SIM_GPS_OFF_N/E/R, tag OFFSET_INJECT). Now verified to actually
drive pos_horiz_ratio in flight, not just conceptually.
Blocker B (param routing / wiring fork): CLOSED. The injector
writes the param through the router, via the EXISTING MAVSDK
fan-out endpoint (14560+i), using MAVSDK param.set_param_float.
This is the same path proven by set_takeoff_altitude in 10b–10d.
Blocker B was specifically about adding a 4th endpoint; reusing the
existing 3-endpoint config does not reproduce it. No router config
change needed. (Direct-to-PX4 path abandoned — unnecessary.)


Test method (for reproduction)

test_gps_offset_inflight_v2.py (repo root, uncommitted helper):


Split channels through router on inst 0:
PX4 14540 → router → 14560 (MAVSDK: fly + param) + 14570 (pymavlink: read ratio).
MAVSDK does arm/takeoff/param (the proven path — passes PX4 prearm via
is_armable wait). pymavlink reads ESTIMATOR_STATUS.pos_horiz_ratio
on 14570 because mavsdk-python 3.15.3 has no mavlink_passthrough
and cannot read that message itself.
v1 (pure pymavlink) was abandoned: raw MAVLink arm hit
"Arming denied: Resolve system health failures first" — it does not
wait through prearm the way MAVSDK's is_armable does.


Caution learned this session


scripts/launch_px4.sh redirects PX4 stdout to /tmp/px4_inst_*.log.
A stuck/looping instance can balloon this to tens of GB fast
(hit 17 GB). Inspect with tail -c, never a full-file grep/tail -n
on a multi-GB log. Truncate after kills: rm -f /tmp/px4_inst_*.log.
pymavlink as a MAVLink peer must send its own GCS heartbeat or PX4
reports datalink lost and refuses to arm (TEMPORARILY_REJECTED with
no reason surfaced). Not needed in the MAVSDK path (it heartbeats).


Next (one micro-step per turn)


Wire the verified mechanism into GpsSpoofingInjector: MAVSDK
param.set_param_float("SIM_GPS_OFF_N", offset) via the 14560 fan-out

mandatory restore (OFF_N=0) in teardown. gRPC port 50057
(already allocated) to stay clear of mission (50051–53) / loiter
(50054–56).



Live-verify gps_spoofing × arch C through run_one.py end-to-end
(attack timing must land on the ramp window).
Then: arch A + arch B baseline + one attack each (never run live).
Step 11: 3×3 matrix smoke. Step 12: full experiment.

## Step 10e — gps_spoofing LIVE VERIFIED on arch C (ParamWriter path)

**Result: PASS (detection + consensus). Recovery defect noted separately.**

Run: `run_c_gps_spoofing_<ts>`, target uav_0, attack@90s, obs 60s.

- Mechanism: injector no longer opens its own MAVSDK connection. During
  flight the mission MAVSDK owns the target's UDP fan-out (14560+i);
  a 2nd client can't bind, and raw pymavlink PARAM_SET doesn't route to
  PX4 via the router. Verified exhaustively (see debugging arc below).
- Final design: `AttackContext.param_writer` (ParamWriter Protocol in
  attacks/base.py) provided by `MavsdkMissionRunner.param_writer_for()`
  → `MissionParamWriter` delegates to the live controller borrowed via
  `controller_for(uav_id)`. Wired with `MavsdkMissionRunner(uav_ids=...)`.
- Teardown reordered in ExperimentRunner: attack.cleanup() runs BEFORE
  mission.abort() so param restore uses the still-live connection.
- Capture-on-fire (arm is before mission.start, no controller yet);
  reads real baseline, falls back to restore_value/0.0 on read failure.

**Live evidence (merged.jsonl):**
- inject_start t0 → gps detector fired at +3.1s: pos_horiz_ratio=2.0
  (PX4-clipped), threshold 1.0, sustained_samples=3. Onset-transient
  signature as predicted (not steady state).
- isolation_announce (gps_anomaly) by monitor_uav_0.
- coordinator_uav_1 → recovery_request mode_loiter.
- monitor_uav_1 AND monitor_uav_2 independently raised
  cross_check_anomaly on uav_0 → full mesh consensus.
- run_summary: error=null, handler_errors=0 across all components.

**Open defect (NOT gps-related): mode_loiter recovery failed.**
- recovery_ack action=mode_loiter success=false, error="loiter failed:".
- Root: loiter handler uses `_default_mavsdk_endpoint` → `udp://127.0.0.1:14540`
  (factory.py). Deprecated udp:// scheme + tries to attach a 2nd MAVSDK
  server on the target during flight. Detection/isolation OK; recovery
  execution is the next task.

**Abandoned approaches (do NOT retry):**
- 2nd mavsdk_server on udpin://14560 → bind "Address in use" (mission holds it).
- Router TCP server endpoint (tcpout://5761) → set_param timeouts in full flight.
- Raw pymavlink PARAM_SET to 14540/14570 → does not apply (router routing).
- All three fail for the same reason: only the live mission System reaches
  PX4 params mid-flight.

**Test count: 446 passing.**
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

## Step 10e — loiter recovery LIVE VERIFIED on arch C (mission-borrowed connection)

**Result: PASS. Full arch C chain closed end-to-end.**

Run: run_c_gps_spoofing (target uav_0, attack@90s, obs 60s).

Chain (merged.jsonl):
  gps detect (pos_horiz_ratio=2.0, +~3s)
  -> isolation_announce (gps_anomaly, monitor_uav_0)
  -> cross_check_anomaly consensus (monitor_uav_1 + monitor_uav_2)
  -> recovery_request mode_loiter (coordinator_uav_1)
  -> recovery_ack mode_loiter success=true (enforcer_uav_0)   <-- NEW

Design:
- Loiter recovery no longer opens its own MAVSDK System (can't bind the
  target's port mid-flight — same constraint as gps param injection).
- DroneController.hold() + MavsdkMissionRunner.loiter_runner_for(uav, main_loop)
  -> MissionLoiterRunner borrows the live mission controller.
- ModeLoiterHandler.set_runner() swaps the default DefaultMavsdkRunner for
  the mission-backed one; wired in ExperimentRunner._setup_fleet.
- WiredFleet.loiter_handlers exposes handlers so the experiment layer can
  swap their runner.

Cross-loop bridge (the crux):
- Recovery runs from the Coordinator mesh-receiver thread via a short-lived
  asyncio.run() (coordinator.py:337) -> different loop/thread from the one
  owning the mission MAVSDK System. Direct await -> "attached to a
  different loop".
- Fix: MissionLoiterRunner.set_loiter uses run_coroutine_threadsafe to
  schedule hold() back onto the captured main loop (idle in the obs-window
  sleep during recovery) and blocks for the result with a timeout.

TECH DEBT (document in Ch.4, PoC simplification — NOT a hidden hack):
- Coordinator still executes each recovery via per-request asyncio.run()
  (coordinator.py:43-49, 337). We bridge over it rather than refactoring to
  a long-lived recovery loop in a dedicated thread. The docstring already
  flags this as the intended future refactor. Acceptable for PoC; the
  bridge is the standard run_coroutine_threadsafe pattern.
- DroneController.get_param_float/set_param_float/hold are concrete
  NotImplementedError defaults (not a separate capability interface) so
  test fakes instantiate unchanged. Minor; could be split into
  ParamCapable/LoiterCapable interfaces later.
- factory._default_mavsdk_endpoint (udp://14540) is now dead for loiter
  (mission-backed) — remove in cleanup.

**Test count: 446 passing.**

## Step 10e/11 — FULL 3x3 MATRIX LIVE VERIFIED (A, B, C)

All three architectures flown live through the MAVSDK pipeline. The
long-standing gap (A and B never flown) is now closed.

Live runs (arch × attack), gps_spoofing target uav_0, attack@90s:
- arch A none          -> flies, 3 monitors read ~15k telemetry each, 0 events (baseline OK)
- arch A gps_spoofing  -> detect +3.0s (ratio 2.0) -> LOCAL isolation, NO recovery
- arch B gps_spoofing  -> detect +3.4s (ratio 2.0) -> segmented local isolation, NO recovery
- arch C gps_spoofing  -> detect +3s -> mesh cross_check consensus (2 neighbours) -> loiter recovery success

Contrast (for Ch.5):
- MTTD ~identical across A/B/C (same detector + same param-injection signature).
- What differs: consensus + recovery. A/B detect+isolate locally only; C
  reaches neighbour consensus and self-heals (mode_loiter).
- Matches the planned thesis claim: architecture varies impact_scope and
  recovery, not detection latency.

Monitor logs contain only events (not raw telemetry); empty monitor
JSONL on baseline runs is expected. Telemetry flow verified via
listener stats (telemetry_seen ~15k-34k per monitor, 0 callback errors).

**Test count: 446 passing. arch A/B/C all live-verified.**

---

## detector_takeout — mesh-advantage scenario (LIVE VERIFIED)

Closes the Ch.3<->Ch.5 detection gap: proves cross_check adds detection
that segmentation cannot, which the 3x4 matrix could not show (detection
100% everywhere there).

Threat model: adversary silences the TARGET monitor's local detectors
(monitor stays alive, keeps publishing its position to the mesh), then
GPS-spoofs. Composed via SequentialAttackInjector [detector_takeout,
gps_spoofing]. No architecture branching: detector_takeout silences the
one monitor whose uav_id == target; the A/B-vs-C split is purely a
consequence of mesh+cross_check being wired (factory DI).

Live smoke (attack-at 90s, obs 60s, target uav_0, N=1 each):
  C: detected=True, n_sec=2 (cross_check, sources monitor_uav_1 +
     monitor_uav_2, ZERO local gps events), impact_scope=1, FP=False
  A: detected=False, n_sec=0
  B: detected=False, n_sec=0

Mechanism note (for Ch.4/5): killing the target's WHOLE monitor would
also stop its peer-position publishing and blind cross_check (C would
degrade to B). detector_takeout deliberately leaves the monitor alive so
the mesh signal survives — this is the honest, precise threat model and
must be stated as such (adversary compromises node-local IDS, not the
telemetry link).

Pending: batch N=10 per arch for Ch.5 statistics; monitor_takeout
(whole-domain kill) still available for the complementary A-SPOF /
blast-radius result but NOT yet live-verified.
---

## OPEN-1 CLOSED — mission.laps; detection verified under motion (runs_v3)

**Read this section before the older ones.** This file is an append-log:
everything above is historical and some of it is superseded here. In
particular, every "Test count: NNN passing" line above is a snapshot from
its own session, not current.

**Test count: 526 passing.** (446 → 512 → 526; the 446 in older sections
is stale and has already caused one session to start from wrong numbers.)

Committed: `a4745f9`.

### What was wrong (the campaign blocker)

The single-lap route finished at **t ≈ 57 s** while attacks fire at
**t = 90 s**. Established from Gazebo ground-truth trajectory, uav_1:

| t | state |
|---|---|
| 0 – 10.9 s | on ground (arm / pre-arm) |
| 10.9 – 21 s | climb to 20 m |
| 21 – 57 s | flying the square |
| 57 – 161 s | hovering at home, v ≈ 0.03 m/s |

Consequence: **runs_v1, runs_v2 and results R1-R4 all measured an attack
on a HOVERING UAV**, not on one executing a mission. Mission resilience
(thesis 3.4.5) was unmeasurable. Defensible only if stated in Ch.4 —
indefensible if a reviewer finds it.

### The fix — `mission.laps`

New optional key in `configs/experiment.yaml`, parsed in `core/config.py`,
default 1. The authored lap pattern is repeated `laps` times **at load
time**; `MissionConfig.waypoints` remains the fully expanded plan, so
`runners/mission_mavsdk.py` and `runners/experiment.py` are **untouched**
and know nothing about laps. Config-only change; the one rule (§3) holds.

`MissionConfig.lap_waypoints` is a property deriving the pattern from the
plan (`waypoints[:len//laps]`) rather than a second stored copy — two
copies of the same fact can disagree.

Shipped: **`laps: 5`**, 4-corner square → 20-item plan.

Sizing from measurement, not estimate:
- lap ≈ 34 s (120 m perimeter, 5 m/s cruise, ≈3.5 m/s average with corner
  deceleration)
- motion from t ≈ 21 s to t ≈ 191 s
- attack t = 90 s → lap 3, in motion — **verified on all three UAVs**
  (v = 2.7–5.1 m/s)
- observation ends t = 150 s → lap 4, in motion — **verified on all three**
  (v = 1.5–5.0 m/s)

4 laps clears the window by only ~8 s. `is_armable` (EKF/GPS convergence)
varies run to run; 8 s would not survive a 1000+ trial campaign. 5 costs
nothing — see next point.

### Route length does NOT affect trial duration (verified)

`MissionRunner.wait_until_complete()` **is never called** by
`runners/experiment.py` — grep confirms only `duration_sec` appears, no
call site. The runner sleeps `attack_at + observation_after_attack` and
exits. Trial wall time: 160.7 s before the change, 160.5 s after.

The mission deliberately does **not** complete inside a trial. That is
what "attack on a mission in progress" requires. Do not "fix" this.

Related: `mission.duration_sec: 300` appears to have **no consumer** — it
is validated in `core/config.py` and never read elsewhere. Unconfirmed,
low priority, noted so it is not mistaken for live behaviour.

### Guards added (512 → 526, +14 tests in `tests/test_config.py`)

- `laps` must be an integer ≥ 1 — rejects `2.5` (would truncate to 2 under
  `int()`) and `true` (bool is an int subclass in Python)
- **identical consecutive waypoints in the expanded plan are rejected.** A
  self-closing lap (ends where it starts) produces one at every seam and
  is a no-op for PX4. Previously catchable only by eyeballing a
  trajectory. Non-adjacent revisits stay legal (figure-8).
- `MissionConfig.__post_init__` enforces the invariants for hand-built
  configs too (tests construct it directly), incl. `len(waypoints) % laps`
- `test_experiment_mission_is_multi_lap` asserts the shipped config still
  flies ≥ 4 laps — if anyone trims it back to one, a test fails instead of
  a campaign silently collecting hover data again

### runs_v3 — detection under motion (N=20, arch C, gps_spoofing)

| Metric | value |
|---|---|
| Detection | **20/20** — Wilson 95% CI **[84%, 100%]** |
| MTTD | 3.113 ± 0.677 s |
| Impact scope | 1.00 ± 0.00 |
| False positives | 0/20 |

Always write "20/20, 95% CI [84%, 100%]", never a bare "100%".

Two questions settled at once: detection is **not** an artefact of
hovering, **and** the metrics did not break on the new route —
`cross_check` does not fire falsely on genuinely moving neighbours.

Dataset committed following the `runs_v1` convention: `run_summary.json`
per run + `report/` (`.gitignore` has `*.jsonl`, so trajectory/merged
logs stay local). `runs_v1` and `runs_v2` are validated datasets — **never
write a new batch into them**; `run_batch.py --log-root` defaults to
`runs_v1`, so always pass it explicitly.

### Detector gradient — OPEN-3 (do not investigate with current data)

| runs | detectors fired | MTTD |
|---|---|---|
| 19 of 20 | 3 | 2.58–3.28 s (mean 2.97, sd 0.22) |
| r10 | 1 | 5.84 s |
| `run_c_gps_spoofing_1784210522` (manual) | 0 | not detected |

The N=20 sd is driven **entirely** by r10. 3 → 1 → 0 is a gradient, not a
binary — so the one undetected run is the far end of a real distribution,
not a glitch. Something in the ramp-onset signature varies run to run.
**Cause unknown.**

Excluding r10 is a post-hoc exclusion: report 3.113 ± 0.677 (N=20) as the
headline, use the breakdown only to explain the sd.

**Cannot be investigated yet**: `1784210522` contains zero security
events — monitors log events, not raw telemetry, so there is nothing to
inspect. Needs PX4 true-vs-believed position and the raw
`pos_horiz_ratio` series from the instrumentation work. **Do not spend
runs guessing at it first.**

### Physical control case for R4 (extends the drift result)

`1784210522` is the natural control: same attack, no detection, so nothing
issued loiter.

| | `208189` (detected, mttd 2.6) | `210522` (not detected) |
|---|---|---|
| t = 110 s | (29.8, 28.4) z = 20.3 | (−6.6, −29.1) **z = 0.5** |
| t = 120 s | (30.0, −16.7) | (−80.9, −40.0) |
| range | x[0..30] y[−20..30] | x[−83..30] y[−50..31] |

Causality, stated correctly: the wild trajectory is a **consequence** of
non-detection, not its cause. Detected → isolation → loiter → UAV stopped
at ~20 m offset and held. Undetected → mission kept executing in a
falsified frame → UAV thrown across the field, nearly touching ground.

### RULED OUT — `SIM_GPS_OFF_N` does not leak via bson (OPEN-4)

The natural hypothesis for `1784210522`: param leaking between runs via
per-instance storage (`run_batch` clears
`rootfs/{0,1,2}/parameters*.bson`, manual `run_one.py` does not).
**Checked and false** — after a completed run only
`parameters_backup.bson` exists, and `SIM_GPS_OFF_N` is in **none** of the
three instances.

This contradicts the rule stated earlier in this file (§"CRITICAL LESSON —
per-instance param storage pollution") as established fact. Either that
rule was never verified, or the behaviour changed. **Do not remove the
cleanup on the strength of one observation** — it is harmless and
`run_batch` does it anyway. But confirm or correct it before Ch.4 cites it
as methodology. Tracked as OPEN-4 in `RESULTS_NOTES.md`.

### MTTR is misnamed (raise in Ch.5, do not paper over)

MTTR across runs_v3 = **0.015 ± 0.006 s**. 15 ms is not a recovery time —
it is latency from decision to *issuing* the loiter command. Combined with
R4 (loiter does not restore a safe state under an integrity attack), the
metric measures **dispatch**, not recovery. The number is not wrong, the
name is. Ch.5 needs the decomposition (dispatch latency vs actual
restoration vs PX4 cold-start, per §8) rather than a headline
"MTTR = 15 ms", which a reviewer will correctly attack.

### Work queue (order matters)

1. **Instrumentation — BEFORE the campaign, not after.** Omitting it means
   re-running ~1160 trials.
   - mission plan in `run_summary` — "was the UAV flying at attack time?"
     must be machine-checkable per run. OPEN-1 was found by hand-reading a
     trajectory; that must never be necessary again.
   - PX4 true vs believed position + raw `pos_horiz_ratio` series →
     unblocks OPEN-3
   - mesh cost counters
   - mesh loss/delay
2. R2 (`monitor_takeout`) batch — still N=1 smoke. R1 already has N=10.
3. OPEN-2 parametric sweeps (`RESULTS_NOTES.md`). `mission.laps` now makes
   flight duration a single-number sweep axis.
4. Full campaign, N=30/cell, with the statistics from OPEN-2.4.

### Files touched this session

- `core/config.py` — `laps`, expansion, validation, `lap_waypoints`
- `tests/test_config.py` — `TestMissionLaps` (13) +
  `test_experiment_mission_is_multi_lap`
- `configs/experiment.yaml` — `laps: 5`, 4-point lap, sizing rationale in
  comments
- `RESULTS_NOTES.md` — R7 (OPEN-1 closed), R8 (detection under motion),
  R4 extended, OPEN-3, OPEN-4, work queue
- `runs_v3/` — 20 × `run_summary.json` + `report/`

## INSTRUMENTATION 1/4 CLOSED — mission_plan + flight_at_attack

Item 1 of 4 (mission plan in run_summary). Tests 526 -> 576.

### What it answers

"Was the UAV actually flying when the attack fired?" — now a field in
every `run_summary.json`, not an investigation. OPEN-1 was found by
hand-reading a Gazebo trajectory after 120 invalid runs had already been
collected (runs_v1, runs_v2, R1-R4 all attacked a hovering UAV). The
question was answerable only once, late, and only by hand. On the
~1160-trial campaign that failure mode is silent and unrepeatable.

### Added

- `metrics/flight_check.py` — pure functions, no I/O in the computation:
  - `flight_state_at(samples, t_wall, ...)` — per-UAV speed / altitude /
    position at the injection instant, plus `in_motion` / `airborne` /
    `flying` verdicts.
  - `read_trajectory(path)` — tolerant reader (a truncated final line is
    normal: the recorder is killed at teardown).
  - `mission_plan_summary(mission_cfg, ...)` — laps, expanded waypoints,
    injection timing.
- `RunResult.mission_plan`, `RunResult.flight_at_attack`.
- `ExperimentRunner._attack_fired_wall` — captured immediately before
  `fire()`, on the same wall clock as merged.jsonl and trajectory.jsonl.
- `ExperimentRunner._resolve_target()` — one definition of the target,
  shared by the scenario and the flight check.

### Decisions

- **Gazebo ground truth only.** PX4's estimate is corrupted by GPS
  spoofing by construction, and monitors are killed by the takeout
  attacks. An answer from either would be an answer from inside the
  system under test (thesis 3.5.5, table 3.14).
- **Z axis: gz world frame is ENU, Z up -> `alt_m = z`, no sign flip.**
  Measured, not assumed: `runs_v3/run_C_gps_spoofing_r16_*`, uav_0 at a
  20 m cruise reads z = +19.81 / +20.21. The NED convention (z down) is
  equally common in this stack and would silently invert every
  `airborne` flag while still reading plausible. Pinned by a test.
- **`None` != `False`.** No recorder -> `flight_at_attack: null` ("not
  observed"). Recorder ran but captured nothing -> populated dict with
  null verdicts ("we looked and saw nothing"). Collapsing the two would
  put a confident falsehood into the dataset.
- **Thresholds (0.5 m/s, 1.0 m) and window (+/-1 s) are written into the
  JSON next to the raw numbers.** A threshold baked into code is a hidden
  assumption a reviewer cannot audit; recorded beside its result it is
  reproducible, and the booleans stay re-derivable from the raw speeds
  without re-flying anything. 0.5 m/s sits inside the 50x gap measured in
  R7 (hover 0.03 m/s, mission flight 1.5-5.1 m/s) — not tuned.
- **Speed = path length / elapsed, not endpoint displacement.** A UAV
  rounding a corner returns near its start; endpoint displacement would
  read ~0 m/s and call a flying UAV hovering — precisely the failure this
  module exists to prevent. Gazebo poses carry no sensor noise (they are
  the physics state), so path length costs nothing in robustness.
- **`mission_plan` is computed before the `_fleet is None` check** — a run
  that died during setup still has to say what it was trying to fly.
- **A flight_check defect surfaces in `error`, it does not raise** (same
  contract as `merge_jsonl`): losing a live 160 s flight over a summary
  field would be the expensive failure.
- **Why run_summary and not the analyzer:** `*.jsonl` is gitignored and
  `configs/experiment.yaml` will drift under the OPEN-2 sweeps, so a
  committed run must be self-contained or the dataset becomes numbers
  without units.
- **No architecture branching.** Both functions read poses and a
  timestamp, so the identical-measurement-procedure requirement holds by
  construction rather than by discipline.

### Deliberately not done

Waypoint index is NOT resolved from position. With `laps: 5` the square
repeats, so lap 1 and lap 3 are physically identical and a
nearest-waypoint guess is ambiguous. Real mission progress needs PX4's
believed item index alongside the true position — that is instrumentation
item 2. Recording the plan now is what keeps that option open; not
recording it would have closed it.

### Live verification

`runs/run_c_gps_spoofing_1784265288`, arch C, gps_spoofing, target uav_0.

    plan:   laps=5, n_waypoints=20, attack_at_sec=90
    flight: n_samples_total=2280, target_in_motion=True,
            target_flying=True
    uav_0 @ inject: speed_horiz=2.467 m/s, speed_3d=2.468 m/s,
                    alt=19.986 m, x=-0.044, y=26.563,
                    in_motion=True, airborne=True, flying=True
                    n_samples=9, dt_sec=1.736, t_offset_sec=0.068

`t_offset_sec = 0.068` is the point of the live run: it confirms the
runner's `time.time()` and the gz bridge's `t_wall` are the same clock.
Nothing in the test suite could establish that — the fakes derive both
timestamps from one `time.time()`, so a clock mismatch is invisible there
by design. Had the clocks diverged, a healthy flight would have returned
`n_samples_total > 0` with `uav_0.n_samples: 0`, and the anchor would
have had to move to `t_sim`.

### Observation (not a blocker)

The +/-1 s window caught 9 samples with dt=1.736 s -> actual recorder
step ~0.217 s, i.e. 4.6 Hz rather than the nominal 5 Hz. Jitter in
`gz topic --json-output`. No effect on the verdict at this window size;
worth revisiting only if the window is ever narrowed below ~0.5 s.

### Assessment

Clean solution. No workarounds.

### Remaining before the campaign

Items 2-4: raw `pos_horiz_ratio` series + PX4 true vs believed position
(unblocks OPEN-3), mesh cost counters, mesh loss/delay. Do not launch the
~1160-run campaign until these are closed.

## INSTRUMENTATION 2A CLOSED — raw estimator series in run_summary

Item 2, first half (raw `pos_horiz_ratio` series). Tests 576 -> 644.
Item 2B (true-vs-believed divergence) is NOT done — see end of block.

### What it answers

OPEN-3 was unanswerable, not merely unanswered: monitors log events, not
telemetry. `GpsSpoofingDetector` sees `pos_horiz_ratio` in every
ESTIMATOR_STATUS and emits nothing unless it fires, so the undetected run
(`run_c_gps_spoofing_1784210522`) contains zero security events. There was
literally nothing to inspect.

A non-detection has exactly two causes, and they are distinguishable:

  n_above_threshold == 0        the ratio never crossed -> the injection
                                produced no signature. Detection rate is
                                then a property of the ATTACK, not the
                                architecture: threats-to-validity.
  max_consecutive_above < 3     it crossed but never sustained -> the
                                signature existed and the sustain rule
                                rejected it: a detector-tuning finding.

`max_consecutive_above` is the discriminator. Both readings are honest
and publishable; guessing between them is not.

### Added

- `metrics/estimator_series.py` — pure functions, no I/O in the
  computation: `estimator_series()`, tolerant `read_telemetry()`.
  Reproduces the detector's sustain rule over a recorded series.
- `Monitor(telemetry_log_path=..., telemetry_log_types=...)` — replaces
  the dead `log_telemetry: bool` flag (present in the signature, never
  passed by `factory.py`, never enabled in any real run).
- `runners/factory.py`: `TELEMETRY_LOG_PREFIX`, every monitor in every
  architecture gets `telemetry_<source>.jsonl`.
- `RunResult.estimator_series`, folded from all monitors' telemetry logs.

### Decisions

- **Why not reuse `log_telemetry`.** It wrote into the monitor's
  `log_path`, which `merge_jsonl` folds into `merged.jsonl` — drowning
  the event stream the metrics layer reads. It also sat BEFORE the
  detectors, i.e. on the path to `SecurityEvent`, so its I/O would have
  been added to MTTD: instrumentation upstream of the measurement changes
  the measurement. Recording now happens AFTER the detector loop, into
  its own file, excluded from the merge by prefix.
- **No config knob; on for every run of every architecture.** ~480
  ESTIMATOR_STATUS lines per trial. A switch is a thing that can be left
  off for the one run that mattered — which is exactly how OPEN-3 became
  unanswerable.
- **Filename keyed on `source`, not `uav_id`.** In Architecture A several
  monitor entries could watch one UAV from different locations; two
  EventLoggers appending to one file would interleave. `source` already
  makes `log_path` unique, so collisions are impossible by the same
  argument.
- **Threshold duplicated, not imported** from `detectors.gps`: this
  module describes what the data did and must stay readable if the
  detector is retuned. A silent divergence would make every recorded
  breach count describe a detector that does not exist, so
  `test_default_threshold_matches_the_detector` compares them directly.
  Duplication yes; blind duplication no.
- **Strict `>`, and a gap breaks a run of breaches** — mirrors the
  detector exactly. `>=` would report breaches the detector never saw; a
  missing sample is not one it could have counted toward sustain.
- **`bool` rejected explicitly**: it is an int subclass in Python, so a
  stray `True` would become 1.0, sitting exactly at the threshold.
- **Baseline is median, not mean**, over pre-injection samples only.
- **Series in `run_summary.json`, not only in .jsonl.** `*.jsonl` is
  gitignored, which is precisely why OPEN-3 is unanswerable for runs
  already on disk. Measured cost: 17.4 kB per summary (arch C, 3 UAVs)
  -> ~20 MB for the full ~1160-run campaign. Acceptable.

### Scope — diagnostic, NOT a metric source

The series is produced by monitors, inside the system under test. An
outside tap would need a 4th mavlink-router endpoint, which breaks MAVSDK
PARAM_SET routing (step 10e, blocker 2). So under `monitor_takeout` the
series dies with the monitor: its availability is architecture-dependent
and NOTHING in table 3.13 may be computed from it (thesis 3.5.5, 3.5.4).
It is for explaining mechanisms in Ch.4/5 and for OPEN-3. Metric-grade
ground truth stays with Gazebo (`metrics/flight_check.py`).

Under `detector_takeout` the opposite holds and is useful:
`disable_local_detectors()` empties the detector list but the listener
survives, so the series shows what the silenced detector WOULD have seen
— R5's mechanism, not only its outcome.

### Live verification

`runs/run_c_gps_spoofing_1784270714`, arch C, gps_spoofing, target uav_0.

    MTTD 3.276 s, detected, impact_scope 1, flying at inject: True
    uav_0: rate_hz 0.9855, n 159, baseline_median 0.0104
           peak 2.0 @ t_rel +1.278, n_above 6, max_consecutive 6
           first_cross +1.278

MTTD unmoved against the runs_v3 baseline (3.113 +/- 0.677, range of the
19 detecting runs 2.58-3.28), so recording after the detectors did what
it was supposed to. See RESULTS_NOTES R9 for what the series revealed.

### 3-channel recording (for 2B)

Measured live on this build (`smoke_telemetry.py`, uav_0):

    ESTIMATOR_STATUS      0.9 Hz    pos_horiz_ratio (the residual)
    LOCAL_POSITION_NED   29.4 Hz    what PX4 BELIEVES  <- 2B
    GPS_RAW_INT          29.8 Hz    the GPS input, i.e. the spoof itself
    GLOBAL_POSITION_INT  49.1 Hz    not recorded
    ATTITUDE             97.6 Hz    not recorded

All three are now in `DEFAULT_TELEMETRY_LOG_TYPES`. The two 30 Hz
channels cost ~14k samples per trial per UAV (~2.8 MB of gitignored
.jsonl). Recorded now, because changing this before the campaign costs
160 s and after it costs weeks.

Together they close the triangle: truth (Gazebo) -> falsified input
(GPS_RAW_INT) -> belief (LOCAL_POSITION_NED). `pos_horiz_ratio` is
precisely the residual between input and prediction, so the triangle
should explain the one-sample collapse in R9. Note GPS_RAW_INT is
geodetic (lat/lon in 1e7 deg): comparing it to NED metres needs the EKF
origin. That it carries the SIM_GPS_OFF_N offset is a HYPOTHESIS (GZBridge
generates the simulated GPS) — unverified until a baseline and an attack
run are compared.

### AXIS CALIBRATION — measured, and it refuted the hypothesis

**Gazebo world is standard ENU: x = EAST, y = NORTH.**

    ned.x (north) = gz.y
    ned.y (east)  = gz.x
    ned.z (down)  = -gz.z        (gz.z ~ +20 -> ned.z ~ -20, confirmed)

Measured on `runs/run_c_none_1784272577` (baseline: no attack, so belief
== truth, which is the only condition where an axis mismatch is
distinguishable from a working spoof). 4383 paired samples above 5 m:

    H2  gz.y=north, gz.x=east : mean err 0.356 m   <- correct
    H1  gz.x=north, gz.y=east : mean err 27.797 m  <- refuted

H1 was the standing hypothesis, argued from a runs_v3 sample
(`x=27.56, y=0.54` against waypoint `north=30, east=0`) and from
`PX4_GZ_MODEL_POSE = instance*5,0,0` spacing the fleet "along +X". Both
were reasoning, not measurement, and both were wrong. The square route is
symmetric under an axis swap, so runs_v3 CANNOT settle this — only
LOCAL_POSITION_NED can, because its frame is fixed by the MAVLink spec
rather than by convention.

**No code changed.** Nothing maps gz x/y to compass directions:
`flight_check` uses `hypot(dx, dy)` (axis-name independent) and
`alt_m = z` was verified separately and stands. The error was in the
hypothesis, not the repository. This is the second axis assumption in
this work that turned out to contradict the "obvious" convention — do not
reason about frames, measure them.

**Consequence for 2B: the fleet is spaced along EAST, not north.**
`PX4_GZ_MODEL_POSE = instance*5,0,0` is gz X = east, so EKF origins sit at
gz (0,0), (5,0), (10,0) for uav_0/1/2. NED origin is EKF start, NOT the
Gazebo world origin — subtract that offset or a healthy uav_1 reads 5 m
of divergence.

**The 0.356 m is NOT the EKF noise floor.** Gazebo records at 4.6 Hz and
NED at 30 Hz; the pairing used a +/-0.2 s tolerance, which at ~4 m/s
allows up to 0.8 m of pure time-alignment error. Most of the 0.356 m is
that artefact. True estimation error is smaller, and proper interpolation
will do better. Either way the spoof injects 50 m, so divergence is
comfortably measurable.

Also confirmed by the same run: the fleet flies the configured square
correctly — NED track (0,0) -> (30,0) -> (30,30) -> (0,30) -> (0,0),
altitude held at 20 m +/- 0.2. Nothing flies crooked.

### Remaining

- **2B**: true-vs-believed divergence into `run_summary` at ~1 Hz (a pair
  is rate-limited by its slower side; the Gazebo recorder runs at 4.6 Hz).
  Raw channels are already being recorded, so no re-flying is needed.
- **3**: mesh cost counters.
- **4**: mesh loss/delay.

Do not launch the ~1160-run campaign until these are closed.

## INSTRUMENTATION 2B CLOSED — true vs believed divergence

Item 2, second half. Tests 644 -> 674. Item 2 (2A + 2B) is now complete.
Items 3 and 4 remain before the campaign.

### What it answers

2A recorded `pos_horiz_ratio` — the EKF's own residual, "did the filter
notice?". It cannot say how far the belief actually moved in metres. 2B
pairs Gazebo ground truth against PX4's believed position
(`LOCAL_POSITION_NED`) and reports the divergence, closing the truth ->
falsified-input -> belief triangle for the truth/belief leg. The third
leg (GPS_RAW_INT, the geodetic input itself) is deferred — see end.

### Added

- `metrics/belief_divergence.py` — pure functions, no I/O in the
  computation:
  - `resolve_ekf_origin()` — median Gazebo pose over a UAV's pre-liftoff
    ground block. The EKF origin is MEASURED, not taken from the
    `PX4_GZ_MODEL_POSE = instance*5,0,0` constant.
  - `belief_divergence()` — truth (gz ENU) -> local NED via the measured
    axis map, paired to believed NED within +/-0.2 s, downsampled to
    ~1 Hz, per UAV.
- `runners/experiment.py`: `RunResult.belief_divergence`,
  `_compute_belief_divergence()`, folded in `_finalize` beside
  `estimator_series` with the same "error into `error`, never fail the
  run" contract.

### Decisions

- **Origin measured, not configured.** Hard-coding `*5` would put a
  deployment's fleet-spacing config inside `metrics/` and break silently
  when spacing changes (5-7 drones, OPEN-2 sweeps). The project already
  got an axis assumption wrong once by reasoning instead of measuring
  (2A calibration) — same discipline here. VALIDATED on live baseline
  below: healthy uav_1/uav_2 read sub-metre, not 5 m / 10 m.
- **Origin from the FIRST ground block only**, not every low-z sample —
  a later crash/landing must not pull the reference point.
- **`None`, never (0,0,0), for an unresolved origin.** Defaulting to
  zero is exactly the fleet-spacing bug the resolver removes.
- **Runs on baseline too.** Unlike `estimator_series`, `belief_divergence`
  does not require an attack anchor: the axis calibration and the EKF
  noise floor are validated on unattacked runs, where truth == belief is
  the only condition a frame error is distinguishable in. With an attack,
  times are relative to injection and baseline is pre-injection; without,
  times are relative to the first paired sample and the whole run is
  baseline. The `anchor` field records which so zero is never ambiguous.
  (In practice a runner-driven baseline still carries the NOMINAL
  injection instant, so anchor="attack" there — identical measurement
  procedure, thesis 3.5.5. The "first_sample" path fires only when the
  instant was never captured.)
- **Airborne threshold shared with `flight_check` by a direct assert**
  (`test_airborne_threshold_matches_flight_check`), not two copies of
  1.0: the same ground/airborne boundary must define "pre-liftoff" here
  and "flying" there.
- **`bool` rejected explicitly** (int subclass -> stray True reads as
  1.0 m); NaN/inf dropped.

### Scope — diagnostic, NOT a metric source

Same rule as 2A: the believed channel comes from a monitor inside the
system under test and dies under `monitor_takeout`, so its availability
is architecture-dependent. Nothing in table 3.13 may be computed from it
(thesis 3.5.5, 3.5.4). Metric-grade ground truth stays with Gazebo.

### Live verification

Baseline `runs/run_c_none_1784288796`, arch C, no attack:

    origins:  uav_0 x=-0.0  uav_1 x=5.0  uav_2 x=10.0   (spawn offset caught)
    baseline_median_horiz_m:  0.228 / 0.179 / 0.077     (all sub-metre)
    peaks ~1-2 m, scattered in time (incl. pre-injection and +57 s on a
    run with NO attack) — single-sample stitching artefacts on corners
    (gz 4.6 Hz vs believed 30 Hz, +/-0.2 s at ~4 m/s), NOT signal. This
    is the baseline noise ceiling.

The 5 m / 10 m spawn offset is REMOVED by the measured origin. The
"origin must be subtracted from data" item is now a confirmed fact on a
real flight, not a hypothesis.

Attack `runs/run_c_gps_spoofing_1784289089`, arch C, gps_spoofing,
target uav_0, `SIM_GPS_OFF_N=50`:

    uav_0:  peak_horiz_m = 50.03 @ t_rel +55.9   (== the injected offset)
    uav_1:  peak 1.01     uav_2: 0.95            (baseline, not attacked)
    ratio uav_0: peak 2.0, n_above 6, max_consec 6, first_cross +1.374

### The triangle (explains R9)

The belief was CAPTURED: LOCAL_POSITION_NED converged to the full 50 m
spoof offset. Timeline read across both series in one summary:

- `ratio` (innovation): spikes at onset (+1.374 s), sustains 6 samples,
  then collapses (R9: 2.0 -> 0.0007).
- `belief_divergence` (consequence): grows to the full 50 m by +55.9 s.

Mechanism: the residual is the gap between prediction and input. It
flares on the spoof onset, but once the EKF accepts the spoof and its
state converges to the spoofed position the residual falls to zero (the
filter now "believes" the spoof) while the true belief-vs-truth error
grows to the full injected offset. The detector therefore fires on the
onset transient only — consistent with the documented signature. 2B
separates detection latency (MTTD, onset ~1.4 s) from corruption
magnitude (50 m, peak +56 s): different axes that were previously
conflated.

### Remaining before the campaign

- **3**: mesh cost counters.
- **4**: mesh loss/delay.
- **2B third leg (deferred, not blocking):** GPS_RAW_INT is geodetic
  (lat/lon 1e7 deg); comparing it to NED metres needs the EKF origin in
  lat/lon. The raw channel is already recorded, so this needs no
  re-flying whenever it is picked up.

Items 3 and 4 touch the mesh — the system under test — unlike 1/2 where
the risk was zero. An error there corrupts the already-validated
runs_v1/runs_v3. Do not launch the ~1160-run campaign until they close.

## INSTRUMENTATION 2B CLOSED — true vs believed divergence

Item 2, second half. Tests 644 -> 674. Item 2 (2A + 2B) is now complete.
Items 3 and 4 remain before the campaign.

### What it answers

2A recorded `pos_horiz_ratio` — the EKF's own residual, "did the filter
notice?". It cannot say how far the belief actually moved in metres. 2B
pairs Gazebo ground truth against PX4's believed position
(`LOCAL_POSITION_NED`) and reports the divergence, closing the truth ->
falsified-input -> belief triangle for the truth/belief leg. The third
leg (GPS_RAW_INT, the geodetic input itself) is deferred — see end.

### Added

- `metrics/belief_divergence.py` — pure functions, no I/O in the
  computation:
  - `resolve_ekf_origin()` — median Gazebo pose over a UAV's pre-liftoff
    ground block. The EKF origin is MEASURED, not taken from the
    `PX4_GZ_MODEL_POSE = instance*5,0,0` constant.
  - `belief_divergence()` — truth (gz ENU) -> local NED via the measured
    axis map, paired to believed NED within +/-0.2 s, downsampled to
    ~1 Hz, per UAV.
- `runners/experiment.py`: `RunResult.belief_divergence`,
  `_compute_belief_divergence()`, folded in `_finalize` beside
  `estimator_series` with the same "error into `error`, never fail the
  run" contract.

### Decisions

- **Origin measured, not configured.** Hard-coding `*5` would put a
  deployment's fleet-spacing config inside `metrics/` and break silently
  when spacing changes (5-7 drones, OPEN-2 sweeps). The project already
  got an axis assumption wrong once by reasoning instead of measuring
  (2A calibration) — same discipline here. VALIDATED on live baseline
  below: healthy uav_1/uav_2 read sub-metre, not 5 m / 10 m.
- **Origin from the FIRST ground block only**, not every low-z sample —
  a later crash/landing must not pull the reference point.
- **`None`, never (0,0,0), for an unresolved origin.** Defaulting to
  zero is exactly the fleet-spacing bug the resolver removes.
- **Runs on baseline too.** Unlike `estimator_series`, `belief_divergence`
  does not require an attack anchor: the axis calibration and the EKF
  noise floor are validated on unattacked runs, where truth == belief is
  the only condition a frame error is distinguishable in. With an attack,
  times are relative to injection and baseline is pre-injection; without,
  times are relative to the first paired sample and the whole run is
  baseline. The `anchor` field records which so zero is never ambiguous.
  (In practice a runner-driven baseline still carries the NOMINAL
  injection instant, so anchor="attack" there — identical measurement
  procedure, thesis 3.5.5. The "first_sample" path fires only when the
  instant was never captured.)
- **Airborne threshold shared with `flight_check` by a direct assert**
  (`test_airborne_threshold_matches_flight_check`), not two copies of
  1.0: the same ground/airborne boundary must define "pre-liftoff" here
  and "flying" there.
- **`bool` rejected explicitly** (int subclass -> stray True reads as
  1.0 m); NaN/inf dropped.

### Scope — diagnostic, NOT a metric source

Same rule as 2A: the believed channel comes from a monitor inside the
system under test and dies under `monitor_takeout`, so its availability
is architecture-dependent. Nothing in table 3.13 may be computed from it
(thesis 3.5.5, 3.5.4). Metric-grade ground truth stays with Gazebo.

### Live verification

Baseline `runs/run_c_none_1784288796`, arch C, no attack:

    origins:  uav_0 x=-0.0  uav_1 x=5.0  uav_2 x=10.0   (spawn offset caught)
    baseline_median_horiz_m:  0.228 / 0.179 / 0.077     (all sub-metre)
    peaks ~1-2 m, scattered in time (incl. pre-injection and +57 s on a
    run with NO attack) — single-sample stitching artefacts on corners
    (gz 4.6 Hz vs believed 30 Hz, +/-0.2 s at ~4 m/s), NOT signal. This
    is the baseline noise ceiling.

The 5 m / 10 m spawn offset is REMOVED by the measured origin. The
"origin must be subtracted from data" item is now a confirmed fact on a
real flight, not a hypothesis.

Attack `runs/run_c_gps_spoofing_1784289089`, arch C, gps_spoofing,
target uav_0, `SIM_GPS_OFF_N=50`:

    uav_0:  peak_horiz_m = 50.03 @ t_rel +55.9   (== the injected offset)
    uav_1:  peak 1.01     uav_2: 0.95            (baseline, not attacked)
    ratio uav_0: peak 2.0, n_above 6, max_consec 6, first_cross +1.374

### The triangle (explains R9)

The belief was CAPTURED: LOCAL_POSITION_NED converged to the full 50 m
spoof offset. Timeline read across both series in one summary:

- `ratio` (innovation): spikes at onset (+1.374 s), sustains 6 samples,
  then collapses (R9: 2.0 -> 0.0007).
- `belief_divergence` (consequence): grows to the full 50 m by +55.9 s.

Mechanism: the residual is the gap between prediction and input. It
flares on the spoof onset, but once the EKF accepts the spoof and its
state converges to the spoofed position the residual falls to zero (the
filter now "believes" the spoof) while the true belief-vs-truth error
grows to the full injected offset. The detector therefore fires on the
onset transient only — consistent with the documented signature. 2B
separates detection latency (MTTD, onset ~1.4 s) from corruption
magnitude (50 m, peak +56 s): different axes that were previously
conflated.

### Remaining before the campaign

- **3**: mesh cost counters.
- **4**: mesh loss/delay.
- **2B third leg (deferred, not blocking):** GPS_RAW_INT is geodetic
  (lat/lon 1e7 deg); comparing it to NED metres needs the EKF origin in
  lat/lon. The raw channel is already recorded, so this needs no
  re-flying whenever it is picked up.

Items 3 and 4 touch the mesh — the system under test — unlike 1/2 where
the risk was zero. An error there corrupts the already-validated
runs_v1/runs_v3. Do not launch the ~1160-run campaign until they close.

## INSTRUMENTATION 2B CLOSED — true vs believed divergence in run_summary

Item 2, second half. Item 2 (2A + 2B) is now complete. Tests 644 -> 674.

### Added

- `metrics/belief_divergence.py` — pure functions, no I/O in the maths:
  - `resolve_ekf_origin()` — median Gazebo pose over a UAV's
    chronologically-first pre-liftoff ground block. Measured, not the
    `instance*5` constant. None (never (0,0,0)) when no ground sample
    exists.
  - `belief_divergence()` — pairs believed LOCAL_POSITION_NED against
    Gazebo truth mapped into NED (north=gz.y-oy, east=gz.x-ox,
    down=-(gz.z-oz)), ±0.2 s tolerance, downsampled to ~1 Hz. Works with
    OR without an attack anchor; the `anchor` field records which.
- `runners/experiment.py`: `RunResult.belief_divergence`,
  `_compute_belief_divergence`, folded in `_finalize` after the detector
  loop with the same "errors go to `error`, never fail the run" contract
  as flight_check / estimator_series.

### Decisions

- **Origin measured, not configured.** This module is architecture-blind
  and has no business knowing fleet-spacing config; and the project got
  an axis assumption wrong once by reasoning instead of measuring (2A
  calibration). Validated live: baseline origins recovered 0/5/10 m
  exactly and healthy medians are sub-metre — a hardcoded `*5` would have
  been correct here but silently wrong under any future re-spacing (the
  5-7 drone step).
- **First pre-liftoff block only**, not all low-z samples: a later crash
  or landing must not pull the origin. Confirmed on real data — the
  recorder starts on the ground (z ≈ -0.013), so the block exists.
- **airborne threshold pinned to flight_check** by a direct equality
  test, not a second copy of the literal 1.0.
- **No anchor requirement** (unlike estimator_series): a working baseline
  is the ONLY condition where a frame error is distinguishable from a
  real spoof (truth == belief there). In practice the runner supplies the
  nominal instant even on baseline, so anchor is "attack"; the
  "first_sample" fallback fires only when the instant was never captured.

### Live verification

Matched pair, arch C, gps_spoofing, target uav_0, SIM_GPS_OFF_N=50:

- baseline `run_c_none_1784288796`: origins x = -0.0 / 5.0 / 10.0,
  medians 0.228 / 0.179 / 0.077 m. Spawn offset removed. Peaks 1-2 m are
  cornering/stitching artefacts (scatter across the run, incl.
  pre-injection and +57 s on a no-attack run) — baseline ceiling ~2 m.
- attack `run_c_gps_spoofing_1784289089`: uav_0 peak 50.03 m @ +55.9 s
  (== the injected offset; EKF fused the spoof), uav_1/uav_2 at baseline.
  Alongside pos_horiz_ratio (first_cross +1.374 s, collapse per R9) this
  closes the truth -> input -> belief triangle. See RESULTS_NOTES R10.

### Not done

- Third leg: GPS_RAW_INT (the falsified input, geodetic) — deferred.
- Items 3 (mesh cost counters) and 4 (mesh loss/delay). Unlike 1/2 they
  touch the system under test — a defect there corrupts the already-
  validated runs_v1/runs_v3. Design them in a fresh chat.

Do not launch the ~1160-run campaign until 3 and 4 are closed.
## INSTRUMENTATION 3 CLOSED — mesh cost counters in run_summary

Item 3. Tests 674->687. Two commits: b3a2c69 (counters in MeshBus),
9837109 (fleet aggregation wired into RunResult.mesh_cost).

MeshBus.mesh_counters(): per-topic msgs+bytes, split published (offered
at this peer) vs delivered (frames on this peer's SUB). Counted on the
frame, not per callback; incremented only after a successful send/decode;
never reset by stop(). ABC default + NoOpMesh report zeros, so A/B carry
zero mesh cost by construction (meshes=[]) — no architecture branch.
"Bytes" = application frame (len(topic)+len(payload)), NOT TCP/IP
overhead: a lower bound on wire cost, stated as such for Ch.4/5.

metrics/mesh_cost.fleet_mesh_cost(): pure fold of per-peer snapshots ->
{per_peer, fleet_total}. Empty list (A/B) -> all-zero aggregate.

Live verification: run_c_none_1784294206, arch C, baseline, error=None.
Fleet over 30 s observation: published 205 msgs / 54.5 kB, delivered
410 / 109 kB, all on topic peer_position. delivered = 2 x published
EXACTLY (full mesh of 3, each frame reaches 2 peers, zero loss on
localhost); per-peer arithmetic closes too (uav_0 delivered 136 =
69+67 from the other two). This confirms the counter is exact AND
records the 0-loss baseline that item 4 will perturb: under loss,
delivered drops below published x fanout. A/B = zero (by construction,
unit-tested) — not re-flown.

The "C detects" claim is now an engineering trade-off: detection costs
~205 msgs / 55 kB per 30 s of idle mesh, A/B pay nothing.
