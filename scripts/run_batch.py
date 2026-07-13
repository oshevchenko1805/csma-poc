#!/usr/bin/env python3
"""
scripts/run_batch.py — batch experiment driver (step 11/12).

Runs a set of (architecture, attack) cells N times each, one trial per
fresh subprocess, with full PX4/Gazebo/router teardown + relaunch around
every single trial. Writes each trial's logs under a dedicated batch root
(default: ./runs_v1) so validated data never mixes with the ad-hoc
debugging runs in ./runs.

Why one subprocess + full relaunch per trial
--------------------------------------------
PX4 SITL, MAVSDK, asyncio event loops, gRPC ports and per-instance PX4
param files (parameters*.bson) all accumulate state. Reusing them across
trials is exactly how earlier sessions leaked SIM_GPS_OFF_N into baseline
runs and hit "address in use". A clean process + a clean simulator per
trial trades ~30s of launch time for isolation we can trust in the
dissertation data.

Safety rails (each earned from a real failure)
----------------------------------------------
  * disk-guard: refuses to start a trial when free space on $HOME drops
    below --disk-floor-gb, and stops the batch cleanly. A full disk
    truncates files mid-write (we lost a source file this way once).
  * per-trial timeout: a hung PX4/MAVSDK can stall forever; on timeout the
    trial is killed, marked, and the batch moves on.
  * fixed attack timing (--attack-at-sec / --observation-after-attack-sec)
    defaults to the known-good 90/60 recipe, NOT run_one's 30s default —
    30s fires before EKF/GPS convergence and would make a cell look broken
    for timing reasons, not architectural ones.

Resumability
------------
Every trial appends one line to <root>/batch_manifest.jsonl. On restart,
cells whose (cell_key, replicate) already completed with exit code 0 are
skipped, so a crashed batch resumes where it stopped.

Usage
-----
    # dry run — print the plan and exact commands, execute nothing
    python scripts/run_batch.py --dry-run

    # default smoke: the 4 never-flown A/B x {comm,cmd} cells, N=1
    python scripts/run_batch.py

    # full matrix later, e.g. N=10 over explicit cells
    python scripts/run_batch.py -n 10 \\
        --cells A/none,B/none,C/none,\\
A/gps_spoofing,B/gps_spoofing,C/gps_spoofing,\\
A/comm_disruption,B/comm_disruption,C/comm_disruption,\\
A/command_injection,B/command_injection,C/command_injection

Exit code
---------
    0  — batch finished (individual trial failures are recorded, not fatal)
    2  — batch stopped early by disk-guard
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
PX4_ROOT = Path.home() / "PX4-Autopilot"

VALID_ARCHS = {"A", "B", "C"}
VALID_ATTACKS = {
    "none",
    "gps_spoofing",
    "comm_disruption",
    "command_injection",
}

# The 4 cells that have never been flown live (the smoke default).
DEFAULT_CELLS = [
    "A/comm_disruption",
    "A/command_injection",
    "B/comm_disruption",
    "B/command_injection",
]


# ---------------------------------------------------------------------------
# Cell parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    arch: str  # "A" / "B" / "C"
    attack: str

    @property
    def key(self) -> str:
        return f"{self.arch}/{self.attack}"


def parse_cells(spec: str) -> list[Cell]:
    cells: list[Cell] = []
    for raw in spec.replace("\n", "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        if "/" not in raw:
            raise ValueError(f"bad cell {raw!r}, expected ARCH/ATTACK")
        arch, attack = raw.split("/", 1)
        arch = arch.strip().upper()
        attack = attack.strip()
        if arch not in VALID_ARCHS:
            raise ValueError(f"bad arch {arch!r} in {raw!r}")
        if attack not in VALID_ATTACKS:
            raise ValueError(f"bad attack {attack!r} in {raw!r}")
        cells.append(Cell(arch, attack))
    if not cells:
        raise ValueError("no cells parsed")
    return cells


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


@dataclass
class TrialRecord:
    cell_key: str
    replicate: int
    run_id: str
    arch: str
    attack: str
    status: str  # ok | error | timeout | launch_failed
    exit_code: Optional[int]
    duration_sec: float
    log_dir: str
    started_at: float


def load_completed(manifest_path: Path) -> set[tuple[str, int]]:
    """Return {(cell_key, replicate)} that already finished with status ok."""
    done: set[tuple[str, int]] = set()
    if not manifest_path.exists():
        return done
    for line in manifest_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("status") == "ok":
            done.add((rec.get("cell_key"), rec.get("replicate")))
    return done


def append_manifest(manifest_path: Path, rec: TrialRecord) -> None:
    with manifest_path.open("a") as f:
        f.write(json.dumps(asdict(rec)) + "\n")


# ---------------------------------------------------------------------------
# Disk guard
# ---------------------------------------------------------------------------


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / (1024**3)


# ---------------------------------------------------------------------------
# Shell helpers (PX4 lifecycle)
# ---------------------------------------------------------------------------


def _bash(cmd: str, *, timeout: Optional[float] = None) -> int:
    """Run a bash snippet from the repo root. Returns exit code."""
    proc = subprocess.run(
        ["bash", "-c", cmd],
        cwd=str(REPO_ROOT),
        timeout=timeout,
    )
    return proc.returncode


CLEANUP_CMD = (
    "./scripts/kill_router.sh 2>/dev/null; "
    "./scripts/kill_px4.sh 2>/dev/null; "
    "pkill -9 -f gz 2>/dev/null; "
    "pkill -9 -f px4 2>/dev/null; "
    "rm -f /tmp/px4_inst_*.log; "
    f"rm -f {PX4_ROOT}/build/px4_sitl_default/rootfs/"
    "{0,1,2}/parameters*.bson; "
    "true"
)

LAUNCH_CMD = "./scripts/launch_px4.sh && ./scripts/launch_router.sh"


def cleanup(verbose: bool = True) -> None:
    if verbose:
        _log("cleanup: kill router/px4/gz, rm params + stale logs")
    try:
        _bash(CLEANUP_CMD, timeout=60)
    except subprocess.TimeoutExpired:
        _log("warn: cleanup timed out")


def launch() -> bool:
    _log("launch: PX4 x3 + mavlink-router x3")
    try:
        rc = _bash(LAUNCH_CMD, timeout=120)
    except subprocess.TimeoutExpired:
        _log("error: launch timed out")
        return False
    if rc != 0:
        _log(f"error: launch exited {rc}")
        return False
    return True


# ---------------------------------------------------------------------------
# One trial
# ---------------------------------------------------------------------------


def run_trial(
    cell: Cell,
    replicate: int,
    args: argparse.Namespace,
    log_root: Path,
) -> TrialRecord:
    run_id = f"{cell.arch}_{cell.attack}_r{replicate}_{int(time.time())}"
    log_dir = log_root / f"run_{run_id}"
    started = time.time()

    cmd = [
        sys.executable,
        "scripts/run_one.py",
        "--arch", cell.arch.lower(),
        "--attack", cell.attack,
        "--mission", "mavsdk",
        "--target-uav", args.target_uav,
        "--attack-at-sec", str(args.attack_at_sec),
        "--observation-after-attack-sec", str(args.obs_sec),
        "--log-root", str(log_root),
        "--run-id", run_id,
        "--px4-pid-file", args.px4_pid_file,
    ]

    # Full simulator relaunch around every trial.
    cleanup()
    time.sleep(args.settle)
    if not launch():
        cleanup()
        return TrialRecord(
            cell_key=cell.key, replicate=replicate, run_id=run_id,
            arch=cell.arch, attack=cell.attack, status="launch_failed",
            exit_code=None, duration_sec=time.time() - started,
            log_dir=str(log_dir), started_at=started,
        )

    _log(f"RUN {cell.key} replicate {replicate} -> {run_id}")
    status = "ok"
    exit_code: Optional[int] = None
    try:
        # Inherit stdout/stderr so run_one's live [run_one] logs are visible.
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), timeout=args.timeout)
        exit_code = proc.returncode
        status = "ok" if exit_code == 0 else "error"
    except subprocess.TimeoutExpired:
        status = "timeout"
        _log(f"TIMEOUT after {args.timeout}s — killing {cell.key} r{replicate}")

    cleanup()
    return TrialRecord(
        cell_key=cell.key, replicate=replicate, run_id=run_id,
        arch=cell.arch, attack=cell.attack, status=status,
        exit_code=exit_code, duration_sec=time.time() - started,
        log_dir=str(log_dir), started_at=started,
    )


# ---------------------------------------------------------------------------
# CLI + main
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    print(f"[run_batch] {msg}", file=sys.stderr, flush=True)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Batch experiment driver with per-trial simulator relaunch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--cells",
        default=",".join(DEFAULT_CELLS),
        help="comma list of ARCH/ATTACK (default: 4 never-flown A/B cells)",
    )
    p.add_argument(
        "-n", "--runs-per-cell", type=int, default=1,
        help="replicates per cell (default: 1 = smoke)",
    )
    p.add_argument(
        "--log-root", type=Path, default=Path("./runs_v1"),
        help="batch output root (default: ./runs_v1)",
    )
    p.add_argument(
        "--attack-at-sec", type=float, default=90.0,
        help="seconds into mission to fire attack (default: 90, known-good)",
    )
    p.add_argument(
        "--observation-after-attack-sec", dest="obs_sec",
        type=float, default=60.0,
        help="seconds to observe after attack (default: 60, known-good)",
    )
    p.add_argument(
        "--timeout", type=float, default=360.0,
        help="per-trial timeout in seconds (default: 360)",
    )
    p.add_argument(
        "--disk-floor-gb", type=float, default=5.0,
        help="stop batch if free space on $HOME drops below this (default: 5)",
    )
    p.add_argument(
        "--settle", type=float, default=2.0,
        help="seconds to wait after cleanup before launch (default: 2)",
    )
    p.add_argument(
        "--target-uav", default="uav_0",
        help="UAV under attack (default: uav_0)",
    )
    p.add_argument(
        "--px4-pid-file", default="/tmp/px4_pids",
        help="PID file written by launch_px4.sh (default: /tmp/px4_pids)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="print the plan + exact commands, execute nothing",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    cells = parse_cells(args.cells)
    log_root = args.log_root.resolve()
    manifest_path = log_root / "batch_manifest.jsonl"

    # Build the full trial list (cell x replicate).
    trials: list[tuple[Cell, int]] = [
        (c, r) for c in cells for r in range(1, args.runs_per_cell + 1)
    ]
    total = len(trials)
    est_min = total * (args.attack_at_sec + args.obs_sec + 45) / 60.0

    _log(f"batch root: {log_root}")
    _log(f"cells: {[c.key for c in cells]}")
    _log(
        f"replicates/cell: {args.runs_per_cell}  total trials: {total}  "
        f"est wall time: ~{est_min:.0f} min"
    )
    _log(
        f"timing: attack@{args.attack_at_sec}s obs+{args.obs_sec}s  "
        f"timeout {args.timeout}s  disk-floor {args.disk_floor_gb}GB"
    )

    if args.dry_run:
        _log("--dry-run: cleanup command per trial:")
        print(f"  {CLEANUP_CMD}")
        _log("--dry-run: launch command per trial:")
        print(f"  {LAUNCH_CMD}")
        _log("--dry-run: run_one invocation per trial (example, cell 1):")
        c0 = cells[0]
        example = [
            sys.executable, "scripts/run_one.py",
            "--arch", c0.arch.lower(), "--attack", c0.attack,
            "--mission", "mavsdk", "--target-uav", args.target_uav,
            "--attack-at-sec", str(args.attack_at_sec),
            "--observation-after-attack-sec", str(args.obs_sec),
            "--log-root", str(log_root),
            "--run-id", f"{c0.arch}_{c0.attack}_r1_<ts>",
            "--px4-pid-file", args.px4_pid_file,
        ]
        print("  " + " ".join(example))
        _log("--dry-run: no processes started, no files written.")
        return 0

    log_root.mkdir(parents=True, exist_ok=True)
    completed = load_completed(manifest_path)
    if completed:
        _log(f"resume: {len(completed)} trials already ok, will skip them")

    results: list[TrialRecord] = []
    for idx, (cell, rep) in enumerate(trials, 1):
        if (cell.key, rep) in completed:
            _log(f"[{idx}/{total}] skip {cell.key} r{rep} (already ok)")
            continue

        avail = free_gb(Path.home())
        if avail < args.disk_floor_gb:
            _log(
                f"DISK GUARD: {avail:.1f}GB free < floor "
                f"{args.disk_floor_gb}GB — stopping batch before "
                f"{cell.key} r{rep}"
            )
            cleanup()
            _summarize(results)
            return 2

        _log(f"[{idx}/{total}] {cell.key} r{rep}  (free {avail:.1f}GB)")
        rec = run_trial(cell, rep, args, log_root)
        append_manifest(manifest_path, rec)
        results.append(rec)
        _log(
            f"[{idx}/{total}] {cell.key} r{rep} -> {rec.status} "
            f"(exit {rec.exit_code}) in {rec.duration_sec:.0f}s"
        )

    cleanup()
    _summarize(results)
    _log(f"manifest: {manifest_path}")
    _log(f"next: python -m metrics.report {log_root}")
    return 0


def _summarize(results: list[TrialRecord]) -> None:
    if not results:
        _log("no trials executed this session")
        return
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    _log("session summary: " + ", ".join(
        f"{k}={v}" for k, v in sorted(by_status.items())
    ))
    for r in results:
        if r.status != "ok":
            _log(f"  {r.status}: {r.cell_key} r{r.replicate} ({r.run_id})")


if __name__ == "__main__":
    sys.exit(main())
