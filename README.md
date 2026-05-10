# CSMA PoC — Multi-UAV Self-Healing Cybersecurity Mesh Architecture

Practical part of a PhD dissertation evaluating a Cybersecurity Mesh
Architecture (CSMA) with self-healing for multi-UAV swarms against two
baselines.

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

- **`comm_disruption`** — heartbeat loss via iptables rules (PoC
  proxy for jamming / link failure)
- **`command_injection`** — MAVLink command with spoofed sysid
- **`gps_spoofing`** — EKF position-horizontal residual divergence
  via SITL parameter manipulation

## Project structure

```
core/                    Event types, logger, mesh transport, telemetry, config
detectors/               heartbeat, command, gps, cross_check
decision/                Pure-strategy deciders (isolation, recovery)
enforcement/             Side-effectful enforcers + handlers
  handlers/              restart_process, mode_loiter, filter_commands
runners/                 monitor, coordinator, factory
configs/                 architecture_{a,b,c}.yaml + experiment.yaml
scripts/                 smoke_telemetry.py (live PX4 verification)
tests/                   Unit + integration tests (~312 currently)
PROJECT_STATE.md         Where we are in the 12-step build plan
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
   `MavsdkRunner`, `connection_factory`, `mesh_factory` — so the same
   classes run unit tests without subprocess / MAVSDK / sockets and
   integration tests against real PX4.

## Status

**Structural code complete through step 8.6a** (factory). See
`PROJECT_STATE.md` for the 12-step plan and the next steps (8.6b
experiment runner, then attacks + integration + full experiment run).

## License

TBD.
