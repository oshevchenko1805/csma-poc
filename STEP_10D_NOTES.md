# Step 10d — closeout notes

**Status:** Architecture C produces a **clean baseline** (zero false positives) and a **clean `command_injection` trial** (only the target UAV affected, no cascade). Two root causes from step 10c — both unrelated to CSMA logic — were eliminated. **439 tests passing.**

This unblocks the path to the step 11 matrix. Two items remain before the matrix can include all attack types and architectures (see "Remaining").

---

## Root causes fixed

Both surfaced as false positives / cascades during step 10c smokes; neither was a CSMA architecture defect — they were simulation-setup bugs.

### 1. Spawn separation 2 m → 5 m

`scripts/launch_px4.sh` + `runners/factory.py::_default_px4_pose`.

At 2 m separation the three X500 models, taking off simultaneously (`asyncio.gather` in `MavsdkMissionRunner`), coupled through rotor downwash and DART contact physics. One UAV would diverge to ~54 m/s lateral velocity (unphysical for X500), Gazebo's collision detector would hit an internal assert and abort, and all three PX4 SITL instances would die with it. CSMA correctly observed the resulting heartbeat loss and issued `restart_process`, but the relaunched PX4s had no simulator to back them.

5 m (~10× model width) is stable for X500 in default SITL physics. `factory.py` is kept in lockstep because `RestartProcessHandler` relaunches a recovered UAV at the same pose it had at initial launch.

### 2. Mission relative-altitude bug

`runners/mission_mavsdk.py`.

`MissionItem` stored absolute MSL altitude (`home_alt + alt_m`), but `upload_mission` hard-coded `relative_altitude_m=0.0` for every waypoint. MAVSDK's `MissionItem.relative_altitude_m` is height *above home*, so every waypoint commanded "descend to home altitude". After takeoff to 15 m the drone immediately tried to descend to 0 m AGL, tripped `mc_pos_control` "invalid setpoints", and entered a Failsafe blind-land loop. While oscillating between mission-climb attempts and Failsafe descents, the EKF horizontal residual stayed pinned at the 2.0 reporting clamp → chronic `gps` detector false positives → downstream `cross_check` cascade (peers saw the UAV's jumping position).

Evidence in PX4 log (uav_0):

```
INFO  [navigator] Climb to 0.0 meters above home
WARN  [mc_pos_control] invalid setpoints
WARN  [mc_pos_control] Failsafe: blind land
WARN  [failsafe] Failsafe activated
[loop]
```

Fix:
- `MissionItem.alt` (absolute MSL) → `MissionItem.relative_alt_m` (home-relative, matches MAVSDK API)
- `ned_to_gps` drops the now-unused `home_alt` parameter
- `upload_mission` feeds `relative_altitude_m=it.relative_alt_m`

After the fix the navigator logs `Climb to 20.0 meters above home`, the Failsafe loop is gone, and the EKF residual stays nominal.

---

## Measurements

All Architecture C, MAVSDK mission, target uav_0, attack at T+90 s, 60 s observation.

| Run                    | n_security | n_isolations | impact_scope | affected      | false_pos | Gazebo  |
|------------------------|-----------:|-------------:|-------------:|---------------|-----------|---------|
| 10c run 1 (pre-fix)    | 138        | 14           | 2            | uav_0, uav_2  | True      | survived|
| 10c run 2 (pre-fix)    | 129        | 5            | 3            | all three     | True      | crashed |
| 10d baseline (none)    | 0          | 0            | 0            | —             | **False** | stable  |
| **10d command_injection** | **120** | **1**        | **1**        | **uav_0**     | **False** | stable  |

Clean `command_injection` trial:

| Metric            | Value     | Note                                          |
|-------------------|-----------|-----------------------------------------------|
| `detected`        | True      | first spoofed COMMAND_LONG → detector         |
| `mttd_sec`        | 0.011     | listener → detector → SecurityEvent           |
| `mttr_sec`        | 0.00066   | `filter_commands` is a state-flag flip        |
| `n_security_events` | 120     | sustained injection, ~2/s for 60 s            |
| `n_isolations`    | 1         | dedup by (uav_id, reason) correct             |
| `impact_scope`    | 1         | only the target — no cascade to peers         |
| `recovery_success`| True      | filter handler succeeded                      |
| `has_false_positive` | False  | clean                                         |

---

## Resolved / no-longer-open

- **Gazebo physics divergence** (STEP_10C_NOTES "Known limitations") — resolved by the 5 m spacing fix. No crash across the 10d baseline and command_injection runs.
- **Missing `command_injection` IsolationAnnounce** observed in the 10c run-2 timeline (STEP_10C_NOTES suggested-next-step #2) — that run had a Gazebo-crash-induced `heartbeat_loss → restart_process → un_isolate` cycle on uav_0 *before* the attack. With the crash eliminated, the clean 10d run shows exactly 1 isolation for `(uav_0, command_injection)`, so the decider behaves correctly. The earlier anomaly was a downstream artefact of the cascade, not a decider defect. Considered moot; will revisit only if it recurs in a stable run.

---

## Remaining before step 11 (3×3 matrix)

1. **`gps_spoofing` live (UDP endpoint).** `GpsSpoofingInjector.DEFAULT_PORT_BASE = 14540` makes MAVSDK attempt `udpin://127.0.0.1:14540+i` — bound by `mavlink-routerd` as a Server endpoint. They cannot coexist. The step-10c gRPC-port fix is necessary but not sufficient; the UDP layer still needs resolving (likely a dedicated router fan-out endpoint, e.g. 14550+i, with the injector's port_base moved to match). This is the last attack type not yet validated end-to-end and the next blocker.

2. **Architecture A and B never run live.** They are simpler (no mesh, no recovery — A is centralized, B is segmented-without-self-healing) but have not been exercised against the current MAVSDK-mission pipeline. At least one baseline + one attack each before trusting them in the matrix.

---

## Reproducing the clean trials

```bash
./scripts/kill_router.sh 2>/dev/null; ./scripts/kill_px4.sh 2>/dev/null
./scripts/launch_px4.sh
./scripts/launch_router.sh
source .venv/bin/activate

# Baseline (expect 0 security events)
python scripts/run_one.py --arch c --attack none --mission mavsdk \
    --target-uav uav_0 --attack-at-sec 90 --observation-after-attack-sec 60 \
    --px4-pid-file /tmp/px4_pids

# command_injection (expect impact_scope=1, no cascade)
python scripts/run_one.py --arch c --attack command_injection --mission mavsdk \
    --target-uav uav_0 --attack-at-sec 90 --observation-after-attack-sec 60 \
    --px4-pid-file /tmp/px4_pids

# Analyse — sort by mtime, NOT name (lexically 'none' > 'command_injection')
python -c "
from pathlib import Path
from metrics.analyzer import analyze_run
from pprint import pp
latest = max(Path('runs').iterdir(), key=lambda p: p.stat().st_mtime)
print('Analyzing:', latest.name)
pp(analyze_run(latest))
"

./scripts/kill_router.sh; ./scripts/kill_px4.sh
```

Note the analyser one-liner now sorts by modification time. The previous `sorted(...)[-1]` sorted lexically, which silently returned the wrong run when a `none` directory existed alongside a `command_injection` one.

---

## Suggested next steps (priority order)

1. **gps_spoofing UDP endpoint** — add a router fan-out endpoint dedicated to the injector and move `GpsSpoofingInjector.port_base` to match; validate `--attack gps_spoofing` against arch C. This is where Architecture C's `cross_check` value-add is meant to show (catching slow GPS drift a local EKF detector might miss).

2. **Architecture A and B smoke** — one baseline + one attack each through the current pipeline, to confirm the non-mesh architectures fly and detect before the matrix.

3. **Step 11 — 3×3 matrix smoke** — 3 architectures × 3 attacks, once (1) and (2) are green.

4. **Step 12 — full experiment** — 100 runs per cell. Beforehand: silence the `mavsdk-python` "Event loop is closed" teardown noise (STEP_10C_NOTES) so runs don't clutter stderr.
