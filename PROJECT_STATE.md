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
