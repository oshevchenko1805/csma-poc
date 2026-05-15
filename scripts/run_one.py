#!/usr/bin/env python3
"""
scripts/run_one.py — single experiment trial driver (step 10).

Wires together architecture config + experiment config + (optional)
attack injector + MavsdkMissionRunner (real PX4 SITL) into one
ExperimentRunner and runs it. Reports the run directory on exit.

This is the CLI we use for:
  - step 10: first end-to-end live integration test (one combo)
  - step 11: 3x3 matrix smoke runs (driven from a shell loop)
  - step 12: full experiment (driven from a higher-level driver
             script that calls this in a loop)

Prerequisite
------------
For `--attack comm_disruption` you need passwordless sudo for
iptables. See PROJECT_STATE.md §10 for setup.

Examples
--------
    # Baseline run, Architecture C, no attack
    python scripts/run_one.py --arch c --attack none

    # First live integration target: Architecture C + comm_disruption
    python scripts/run_one.py --arch c --attack comm_disruption

    # With explicit target UAV and timing overrides
    python scripts/run_one.py --arch c --attack gps_spoofing \\
        --target-uav uav_1 --attack-at-sec 20 \\
        --observation-after-attack-sec 30

Exit code
---------
    0  — run completed cleanly (result.error is None)
    1  — run raised an error (still cleaned up; details in
         <log_dir>/run_summary.json and stderr)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

# Make repo root importable regardless of where the script is invoked from.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from attacks.base import AttackInjector, NullAttackInjector  # noqa: E402
from attacks.command_injection import CommandInjectionInjector  # noqa: E402
from attacks.comm_disruption import CommDisruptionInjector  # noqa: E402
from attacks.gps_spoofing import GpsSpoofingInjector  # noqa: E402
from core.config import (  # noqa: E402
    ExperimentConfig,
    load_architecture_config,
    load_experiment_config,
)
from enforcement.handlers import ExternalAwareProcessRunner  # noqa: E402
from runners.experiment import ExperimentRunner  # noqa: E402
from runners.mission_mavsdk import MavsdkMissionRunner  # noqa: E402
from runners.missions import MissionRunner, NullMissionRunner  # noqa: E402


CONFIGS_DIR = REPO_ROOT / "configs"


# ---------------------------------------------------------------------------
# Attack registry
# ---------------------------------------------------------------------------


ATTACK_FACTORIES: dict[str, Callable[[], AttackInjector]] = {
    "none": NullAttackInjector,
    "comm_disruption": CommDisruptionInjector,
    "command_injection": CommandInjectionInjector,
    "gps_spoofing": GpsSpoofingInjector,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run one CSMA experiment trial against live PX4 SITL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--arch",
        required=True,
        choices=["a", "b", "c"],
        help="architecture code (a / b / c)",
    )
    p.add_argument(
        "--attack",
        required=True,
        choices=list(ATTACK_FACTORIES.keys()),
        help="attack name (or 'none' for baseline)",
    )
    p.add_argument(
        "--run-id",
        default=None,
        help="run identifier (default: <arch>_<attack>_<unix_ts>)",
    )
    p.add_argument(
        "--target-uav",
        default="uav_0",
        help="UAV under attack (default: uav_0)",
    )
    p.add_argument(
        "--log-root",
        default="./runs",
        help="root directory for run logs (default: ./runs)",
    )
    p.add_argument(
        "--attack-at-sec",
        type=float,
        default=None,
        help="seconds into mission to fire attack (default: ExperimentRunner default)",
    )
    p.add_argument(
        "--observation-after-attack-sec",
        type=float,
        default=None,
        help="seconds to observe after attack fires (default: from experiment.yaml)",
    )
    p.add_argument(
        "--takeoff-alt-m",
        type=float,
        default=15.0,
        help="takeoff altitude for MAVSDK mission (m, default: 15.0)",
    )
    p.add_argument(
        "--mission",
        choices=["mavsdk", "null"],
        default="mavsdk",
        help=(
            "mission runner: 'mavsdk' = real PX4 flight (default); "
            "'null' = no flight, telemetry-only smoke test "
            "(use this for step 10a — bypasses MAVSDK/pymavlink port conflict)"
        ),
    )
    p.add_argument(
        "--px4-pid-file",
        default="/tmp/px4_pids",
        help=(
            "path to file containing externally-launched PX4 PIDs "
            "(one per line, in sysid order: inst 0, inst 1, inst 2). "
            "Default: /tmp/px4_pids (written by scripts/launch_px4.sh). "
            "When this file exists, an ExternalAwareProcessRunner is "
            "built so RestartProcessHandler can actually kill the right "
            "PX4 on recovery. Pass '' to disable."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="build everything but don't actually run() — useful for smoke-testing wiring",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Component builders
# ---------------------------------------------------------------------------


def build_attack(name: str) -> AttackInjector:
    factory = ATTACK_FACTORIES[name]
    return factory()


def build_mission(
    kind: str,
    exp_cfg: ExperimentConfig,
    *,
    takeoff_altitude_m: float,
    attack_at_sec: float,
    observation_after_attack_sec: float,
) -> MissionRunner:
    """Dispatch mission runner by kind.

    'mavsdk' — real MAVSDK-driven PX4 flight (3 UAVs through waypoints).
    'null'   — no flight at all; just sleeps. Useful when:
               - PX4 is already running, we only want to test detection
                 + recovery against live telemetry (step 10a smoke);
               - port 14540 is occupied by pymavlink listener and MAVSDK
                 can't coexist on it (PROJECT_STATE.md step-10 blocker).
    """
    if kind == "mavsdk":
        return build_mavsdk_mission(
            exp_cfg, takeoff_altitude_m=takeoff_altitude_m
        )
    if kind == "null":
        # Mission must outlast the attack + observation window with margin.
        duration = max(60.0, attack_at_sec + observation_after_attack_sec + 30.0)
        return NullMissionRunner(duration_sec=duration)
    raise ValueError(f"unknown mission kind: {kind!r}")


def build_mavsdk_mission(
    exp_cfg: ExperimentConfig,
    *,
    takeoff_altitude_m: float,
) -> MavsdkMissionRunner:
    """Build MavsdkMissionRunner from experiment config.

    MAVSDK endpoint per UAV follows the PX4 SITL convention:
      port = 14540 + (sysid - 1)
      url  = "udp://127.0.0.1:<port>"

    Ordered by sysid so endpoint[i] corresponds to UAV with sysid=i+1.
    """
    endpoints: list[str] = []
    for ep in sorted(exp_cfg.telemetry.endpoints, key=lambda e: e.sysid):
        port = 14540 + (ep.sysid - 1)
        endpoints.append(f"udp://127.0.0.1:{port}")

    return MavsdkMissionRunner(
        endpoints=endpoints,
        waypoints=list(exp_cfg.mission.waypoints),
        takeoff_altitude_m=takeoff_altitude_m,
    )


def build_process_runner(
    pid_file: str,
    exp_cfg: ExperimentConfig,
) -> ExternalAwareProcessRunner | None:
    """Build an ExternalAwareProcessRunner from a PID file if present.

    PID file format: one PID per line, in sysid order (line 1 = sysid 1,
    line 2 = sysid 2, ...). Matches what scripts/launch_px4.sh writes.

    Returns None when:
      - pid_file is empty string (explicitly disabled)
      - file does not exist
      - file is empty
      - line count doesn't match number of telemetry endpoints
      - any line is not a valid integer

    A None return means RestartProcessHandler will fall back to its
    DefaultProcessRunner — fine for tests, useless for live PoC (it
    won't be able to kill externally-launched PX4 processes).
    """
    if not pid_file:
        return None
    path = Path(pid_file)
    if not path.exists():
        return None

    try:
        lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    except OSError:
        return None
    if not lines:
        return None

    # Order endpoints by sysid; line i maps to that sysid's uav_id.
    ordered = sorted(exp_cfg.telemetry.endpoints, key=lambda e: e.sysid)
    if len(lines) != len(ordered):
        _log(
            f"warn: {pid_file} has {len(lines)} PIDs but "
            f"{len(ordered)} telemetry endpoints — ignoring PID file"
        )
        return None

    mapping: dict[str, int] = {}
    try:
        for ep, raw in zip(ordered, lines):
            mapping[ep.uav_id] = int(raw)
    except ValueError:
        _log(f"warn: {pid_file} contains non-integer PID — ignoring PID file")
        return None

    return ExternalAwareProcessRunner(uav_to_initial_pid=mapping)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    print(f"[run_one] {msg}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    arch_path = CONFIGS_DIR / f"architecture_{args.arch}.yaml"
    exp_path = CONFIGS_DIR / "experiment.yaml"
    arch_cfg = load_architecture_config(arch_path)
    exp_cfg = load_experiment_config(exp_path)

    run_id = args.run_id or f"{args.arch}_{args.attack}_{int(time.time())}"
    log_root = Path(args.log_root).resolve()
    log_root.mkdir(parents=True, exist_ok=True)

    attack = build_attack(args.attack)

    # ExperimentRunner timing defaults — needed for null-mission duration calc.
    effective_attack_at = (
        args.attack_at_sec
        if args.attack_at_sec is not None
        else ExperimentRunner.DEFAULT_ATTACK_AT_SEC
    )
    effective_obs_after = (
        args.observation_after_attack_sec
        if args.observation_after_attack_sec is not None
        else exp_cfg.runs.observation_after_attack_sec
    )

    mission = build_mission(
        args.mission,
        exp_cfg,
        takeoff_altitude_m=args.takeoff_alt_m,
        attack_at_sec=effective_attack_at,
        observation_after_attack_sec=effective_obs_after,
    )

    extra: dict = {}
    if args.attack_at_sec is not None:
        extra["attack_at_sec"] = args.attack_at_sec
    if args.observation_after_attack_sec is not None:
        extra["observation_after_attack_sec"] = args.observation_after_attack_sec

    process_runner = build_process_runner(args.px4_pid_file, exp_cfg)

    runner = ExperimentRunner(
        arch_cfg=arch_cfg,
        exp_cfg=exp_cfg,
        run_id=run_id,
        log_root=log_root,
        attack_injector=attack,
        mission_runner=mission,
        target_uav=args.target_uav,
        process_runner=process_runner,
        **extra,
    )

    expected_log_dir = log_root / f"run_{run_id}"
    _log(
        f"arch={args.arch.upper()} attack={args.attack} "
        f"target={args.target_uav} run_id={run_id} mission={args.mission}"
    )
    _log(f"log_dir will be: {expected_log_dir}")
    if isinstance(mission, MavsdkMissionRunner):
        _log(f"mavsdk endpoints: {mission._endpoints}")
    else:
        _log("mission runner: NullMissionRunner (no flight)")
    if process_runner is not None:
        _log(
            f"process runner: ExternalAwareProcessRunner with PIDs "
            f"{process_runner.pending_initial_pids}"
        )
    else:
        _log("process runner: default (no external PID tracking)")

    if args.dry_run:
        _log("--dry-run: skipping ExperimentRunner.run()")
        return 0

    result = runner.run()

    _log(
        f"DONE in {result.duration_sec:.1f}s "
        f"error={result.error or 'none'}"
    )
    _log(f"log_dir:    {result.log_dir}")
    _log(f"merged_log: {result.merged_log}")

    return 1 if result.error else 0


if __name__ == "__main__":
    sys.exit(main())
