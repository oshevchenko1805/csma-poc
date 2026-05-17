# Step 10c — closeout notes

**Status:** live `command_injection` smoke against Architecture C works end-to-end. Detection layer wired with router-aware attack injection; loiter recovery now actually executes (previously failed silently). **439 tests passing.**

Surfaced one new open issue (Gazebo physics divergence) that is **independent of CSMA** and tracked separately for step 10d.

---

## What was done

Three orthogonal fixes were needed to get `command_injection` from "injector fires but detector never sees it" to "detector fires, decider announces, recovery executes".

### 1. Sysid filter passthrough for command messages — `core/telemetry.py`

`TelemetryListener` previously dropped any packet whose `src_sysid` didn't match `expected_sysid`. The signature of a `command_injection` attack is precisely a `COMMAND_LONG`/`COMMAND_INT` from a non-whitelist source — those packets were being filtered out *before* reaching `CommandInjectionDetector`.

Added module-level constant:

```python
SYSID_FILTER_PASSTHROUGH: frozenset[str] = frozenset(
    {"COMMAND_LONG", "COMMAND_INT"}
)
```

`_receive_loop` filter relaxed:

```python
if src_sys != self.expected_sysid and msg_type not in SYSID_FILTER_PASSTHROUGH:
    self._n_filtered_sysid += 1
    continue
```

Rationale documented in module docstring: the listener is no longer the gatekeeper for command sysid; `CommandInjectionDetector.DEFAULT_WHITELIST = {1, 2, 3, 255}` is. Other telemetry types still require matching `expected_sysid` — they carry no adversarial-source signal and rogue-sourced copies would only confuse detectors.

**Test changes:**
- `tests/test_telemetry.py` — added `test_command_messages_pass_sysid_filter` (positive coverage)
- `tests/test_monitor.py` — rewrote `test_command_injection_from_rogue_sysid_fires`; was asserting `listener_filtered_sysid==1 && security_emitted==0`, now asserts `security_emitted==1` with correct SecurityEvent evidence

### 2. Attack injector targets Monitor listener — `scripts/run_one.py`

`CommandInjectionInjector` default `port_base=14540` aimed at PX4's port. Post-step-10b that port is bound by `mavlink-routerd` as a UDP Server. The router drops attacker packets because `target_system=1` lives on the same Server endpoint they entered from (loop prevention) — empirically `"N messages to unknown endpoints in the last 5 seconds"` in router log, `monitor_uav_*.jsonl` empty.

Fix in `ATTACK_FACTORIES`:

```python
"command_injection": lambda: CommandInjectionInjector(port_base=14570),
```

The injector now writes spoofed `COMMAND_LONG` directly to each Monitor's MAVLink listener (`udpout:127.0.0.1:14570+i`). This **restores the step-10a attack model**: in 10a the Monitor was on 14540 and the attacker hit it directly; PX4 didn't bind 14540 in 10a either (it only sends there), so the attack's reach is no narrower than the documented 10a baseline.

Class default (`14540`) untouched — unit tests and any non-router-fronted scenario unchanged.

### 3. Per-consumer gRPC ports — `enforcement/handlers/loiter.py`, `attacks/gps_spoofing.py`, `runners/factory.py`, `scripts/run_one.py`

`DefaultMavsdkRunner` (loiter recovery) and `DefaultGpsSpoofingRunner` (GPS attack) both called `mavsdk.System()` with no port argument. Three `MavsdkDroneController` instances already hold gRPC ports 50051–50053 from step 10b; any subsequent `System()` collides with `AioRpcError: Socket closed`. Empirically this caused loiter recovery to silently report success ~30 ms after request without engaging hold mode (run 1 of the 10c smoke: 12 cross_check-anomaly announces on uav_2 looped because hold never took effect).

Both `Default*Runner.__init__` now accept `grpc_port: Optional[int] = None`. When set, `System(port=self._grpc_port)` is used; default `None` preserves legacy behaviour for unit tests injecting fakes.

`runners/factory.py`:
- Imports `DefaultMavsdkRunner`
- Introduces `LOITER_GRPC_PORT_BASE = 50054`
- `_build_arch_c` builds each per-UAV loiter handler with `runner=DefaultMavsdkRunner(grpc_port=LOITER_GRPC_PORT_BASE + (ep.sysid - 1))`

`scripts/run_one.py`:
- Imports `DefaultGpsSpoofingRunner`
- `ATTACK_FACTORIES["gps_spoofing"] = lambda: GpsSpoofingInjector(runner=DefaultGpsSpoofingRunner(grpc_port=50057))`

### gRPC port map (Architecture C, live PoC)

```
50051-50053  MavsdkDroneController     (mission controllers, one per UAV)
50054-50056  DefaultMavsdkRunner       (loiter recovery, one per UAV)
50057        DefaultGpsSpoofingRunner  (GPS attack injector, one-shot)
```

---

## Test status

`python -m pytest tests/ -q` → **439 passed**

Changes vs. step 10b:
- `tests/test_telemetry.py`: +1 test (`test_command_messages_pass_sysid_filter`)
- `tests/test_monitor.py`: rewrote one test (`test_command_injection_from_rogue_sysid_fires`)
- No new tests for `Default*Runner` `grpc_port` kwarg — that path imports `mavsdk` and is exercised by integration smokes, not unit tests

`FakeMavsdkRunner` and `FakeGpsSpoofingRunner` paths untouched.

---

## Measurements

### Smoke 1 — Gazebo-stable, `command_injection` + arch C

| Metric                | Value         | Comment                                              |
|-----------------------|---------------|------------------------------------------------------|
| `detected`            | True          | First spoofed COMMAND_LONG reaches detector          |
| `mttd_sec`            | 0.009         | listener → detector → SecurityEvent on next tick     |
| `mttr_sec`            | 0.00037       | `filter_commands` action is a state-flag flip        |
| `n_security_events`   | 138           | injector fires ~2.3 packets/s for 60s — by design    |
| `n_isolations` (command_injection) | 1 | dedup by `(uav_id, reason)` working                 |
| `recovery_success`    | True          | filter handler succeeded                             |

Numerical correctness for the attack itself is established. The 138-event volume reflects sustained-attack design (every spoofed packet is independent evidence); MTTD is fast because the injector now bypasses the router and writes to the listener directly.

### Smoke 2 — Gazebo crashed during run

In a second smoke, Gazebo's DART physics aborted ~12 s into the mission (before the attack at T+90 s). uav_2 had reached ~54 m/s — Gazebo's collision detector hit an internal assert and the Gazebo process exited, taking all three PX4 SITL instances with it. CSMA correctly observed heartbeat loss on all three UAVs and issued `restart_process` recovery; the new PX4 instances came up but failed pre-flight with `Attitude failure (roll)` because Gazebo wasn't restarted.

This run's numbers are not representative of `command_injection` behaviour — they reflect a separate Gazebo-physics failure mode. Recorded for context, not for evaluation:

| Metric                | Value         | Note                                                  |
|-----------------------|---------------|-------------------------------------------------------|
| `n_security_events`   | 129           | 124 command (post-attack) + 2 cross_check + 3 heartbeat |
| `n_isolations`        | 5             | 2 cross_check + 3 heartbeat; **0 command_injection**  |
| `recovery_request`    | 4             | 1 loiter (failed) + 3 restart_process (all "success") |
| `mttr_sec`            | 8.064         | real MAVSDK connect + hold + ack time                 |
| `impact_scope`        | 3             | all three UAVs flagged from heartbeat loss cascade    |

Two observations worth carrying forward:

1. **Loiter recovery now reports honestly.** `mode_loiter` ack arrived with `success=False` (5 s after request) — MAVSDK correctly reported PX4 unreachable. Pre-patch this returned `success=True` ~30 ms after request without engaging hold.

2. **Detection layer is robust to PX4 failure.** The attacker writes UDP directly to the Monitor listener (bypassing the router). When all PX4s died, the listener still received all 124 spoofed packets and the detector fired every time. Useful property for the dissertation: detection survives flight-layer failures.

A subtlety to investigate (step 10d): in this run no `IsolationAnnounce` was emitted for the `command_injection` SecurityEvents, even though `(uav_0, command_injection)` was never previously announced and `un_isolate(uav_0)` had been called after the earlier `heartbeat_loss → restart_process` cycle succeeded. The decider state interaction between cascaded-reason recoveries and subsequent attack-specific events needs analysis.

---

## Known limitations for next steps

### Gazebo / DART physics divergence on aggressive flight

`uav_2` reaches ~54 m/s in the configured mission (cross_check evidence: `distance_m=53.5m / dt=0.985s` between consecutive position publishes). At those velocities DART's collision detector occasionally hits an unrecoverable assert and aborts Gazebo. When Gazebo dies it takes all three PX4 SITL instances with it, after which `restart_process` recovery cannot succeed (the relaunched PX4s have no simulator to back them).

Root cause is **not in CSMA**. Candidates:
- `configs/experiment.yaml` waypoints too far apart for the configured takeoff altitude — PX4 saturates velocity setpoint
- PX4 default velocity limits too permissive for the model
- Gazebo physics step / DART tuning intolerant of this corner

This is the blocker for step 11 (3×3 matrix smoke). Step 10d's first task: instrument what uav_2 is doing between consecutive position publishes, then tune mission/params until cross_check stays silent on baseline (no-attack) runs.

### GpsSpoofingInjector UDP endpoint vs. router

`GpsSpoofingInjector.DEFAULT_PORT_BASE = 14540` causes MAVSDK to attempt `udpin://127.0.0.1:14540+i` — a port now bound by `mavlink-routerd` as a Server endpoint. They cannot coexist. The grpc_port fix from this step plumbs `DefaultGpsSpoofingRunner` correctly, but the UDP-layer collision remains. Will need either a new router fan-out endpoint dedicated to the injector or a direct connection path. Address when `--attack gps_spoofing` is run end-to-end.

### `mavsdk-python` teardown noise

Every `DefaultMavsdkRunner.set_loiter` invocation produces a stderr trace at System teardown:

```
Exception in callback PollerCompletionQueue._handle_events ...
RuntimeError: Event loop is closed
```

This is a known `mavsdk-python` quirk: gRPC's poller tries to schedule cleanup on an asyncio loop that has already closed. The `hold()` command was already sent before teardown, so this is cosmetic. The run completes cleanly (`error=none`). Not a blocker but should be silenced or filtered before any user-facing reporting in step 12.

---

## Reproducing the closing trial

```bash
# 1. PX4 ×3
./scripts/launch_px4.sh

# 2. mavlink-routerd ×3 (fan-out)
./scripts/launch_router.sh

# 3. Smoke
source .venv/bin/activate
python scripts/run_one.py \
    --arch c \
    --attack command_injection \
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

# 5. Cleanup
./scripts/kill_router.sh
./scripts/kill_px4.sh
```

Expected wall time: ~3 minutes. Expected outcome on a Gazebo-stable run: `detected=True`, `mttd_sec` ≈ 0.01 s, `mttr_sec` < 0.01 s (filter_commands is a state-flag flip), 1 isolation announce for `(uav_0, command_injection)`, `recovery_success=True`. uav_2 cross_check noise depends on whether Gazebo physics holds for this particular run — see "Known limitations".

---

## Suggested next steps (priority order)

1. **Step 10d — Gazebo / mission stability.** Find why uav_2 reaches ~54 m/s, tune mission/params until baseline (no-attack) runs produce zero cross_check or gps anomalies. This is the prerequisite for any clean matrix measurements.

2. **Step 10d — IsolationDecider state-interaction audit.** Reproduce the run-2 case (cascaded heartbeat_loss followed by attack-specific event on same UAV) and verify whether the missing `command_injection` announce is a real bug or a logging artefact.

3. **Step 11 — 3×3 matrix smoke.** Once 10d is clean: 3 architectures × 3 attacks. Need to also resolve `GpsSpoofingInjector` UDP endpoint before this can include `--attack gps_spoofing`.

4. **Step 12 — full experiment.** 100 runs per cell. Beforehand: silence `mavsdk-python` teardown noise so the runs don't clutter stderr.

