# CSMA PoC — Multi-UAV Self-Healing Cybersecurity Mesh Architecture

Practical part of a PhD dissertation evaluating a Cybersecurity Mesh
Architecture (CSMA) with self-healing for multi-UAV swarms against
two baselines.

## Three architectures

| Code | Name | Detection | Isolation | Recovery |
|------|------|-----------|-----------|----------|
| **A** | Centralized | Single ground-station monitor | Ground-station-issued | None |
| **B** | Segmented / distributed | Per-UAV monitors | Local, no announcement | None |
| **C** | **CSMA + self-healing** | Per-UAV monitors | Local + mesh-announced | Coordinator-driven, automated |

All three are built from the **same component library** — the
architecture difference is **configuration**, not code branches. Each
yaml in `configs/architecture_*.yaml` selects detectors, mesh
transport, recovery on/off, and enforcer type. The factory
(`runners/factory.py`) wires the right components together.

## Three attack cases

- **`comm_disruption`** — heartbeat loss via iptables DROP rule (PoC
  proxy for jamming / link failure)
- **`command_injection`** — periodic MAVLink commands with spoofed
  sysid via background asyncio task
- **`gps_spoofing`** — PX4 SITL `SIM_GPS_NOISE` parameter manipulation
  via MAVSDK Param API

## Project structure

```
core/                    Event types, logger, mesh transport, telemetry, config
detectors/               heartbeat, command, gps, cross_check
decision/                Pure-strategy deciders (isolation, recovery)
enforcement/             Side-effectful enforcers + handlers
  handlers/              restart_process, mode_loiter, filter_commands
runners/                 monitor, coordinator, factory, missions,
                         mission_mavsdk, experiment
attacks/                 base, comm_disruption, command_injection, gps_spoofing
metrics/                 analyzer (MTTD/MTTR/FP/FN/impact)
configs/                 architecture_{a,b,c}.yaml + experiment.yaml
scripts/                 smoke_telemetry.py (live PX4 verification)
tests/                   24 test files, 422 passing
PROJECT_STATE.md         Full handoff document for new chat sessions
```

## Quick start

Tested on **Ubuntu 22.04 ARM64** (Apple M4 Pro / UTM VM), Python 3.10.12.

```bash
# 1. Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Run unit tests (no PX4 needed for these)
python -m pytest tests/ -q
# Expected: 422 passed

# 3. Live smoke test against PX4 SITL
#    Requires PX4-Autopilot + Gazebo running:
#      cd ~/PX4-Autopilot
#      make px4_sitl gz_x500
python scripts/smoke_telemetry.py
```

## Key design principles

1. **Architecture = deployment, not code branches.** No
   `if architecture == 'C'` in domain code. The factory picks
   `NoOpMesh` vs `ZmqMesh`, `LocalIsolationEnforcer` vs
   `MeshAnnouncingIsolationEnforcer`, etc. — and the same Monitor /
   Detector / Decider runs in all three.
2. **Detectors are pure.** No I/O. They take in TelemetryEvents and
   return SecurityEvents (or None). All thread-safety, all logging
   lives in Monitor.
3. **Deciders are state machines.** No I/O. They take Events and
   return Events (or None). Side effects live in Enforcers and
   Handlers.
4. **DI seams at every side-effect boundary.** `ProcessRunner`,
   `MavsdkRunner`, `IptablesRunner`, `MavlinkSender`,
   `GpsSpoofingRunner`, `DroneController`, `connection_factory`,
   `mesh_factory` — so unit tests run without subprocess / MAVSDK /
   sockets / iptables / network, and integration tests use real PX4.

## Status

**All non-PX4 code complete.** 422 tests passing. Remaining work is
**live PX4 integration** only:

- Step 10: first end-to-end run (Architecture C + comm_disruption +
  real PX4 SITL)
- Step 11: 3×3 architecture × attack matrix smoke
- Step 12: full 100-runs-per-architecture experiment + plots

See `PROJECT_STATE.md` for the full handoff document, including the
expected blockers at step 10 (sudo / port conflicts / home-position
GPS lock timing).

## License

TBD.
