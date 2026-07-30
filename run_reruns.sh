#!/usr/bin/env bash
# Re-run ONLY the campaign cells that failed (command_injection + both
# takeout scenarios). The standard none/gps/comm cells survived in
# std_pass1 (N=5) and are kept.
#
# Why this differs from the failed run:
#   * short chunks (<=15 runs) — well under the ~45-run tipping point at
#     which the sim wedged;
#   * a cooldown between chunks so the M4 sheds heat (thermal throttling
#     is the leading suspect for the slow-Gazebo-boot wedge);
#   * requires the run_batch circuit breaker (patch_run_batch_robust.py) —
#     if a chunk wedges anyway it aborts in minutes, not hours.
#
# Each chunk is its own log-root so a wedge never contaminates a clean
# chunk, and analysis points only at the roots that finished clean.
#
# Run in tmux with `caffeinate -dims` on the Mac. Resumable: re-running
# skips chunks whose runs already passed (run_batch manifest).

set -u
cd ~/csma_poc_v2 || exit 1
source .venv/bin/activate

COOLDOWN=300   # seconds between chunks — let the sim/host settle & cool

if ! grep -q MAX_CONSEC_FAIL scripts/run_batch.py; then
  echo "!! run_batch is not hardened. Apply patch_run_batch_robust.py first."
  exit 1
fi
if systemctl is-active --quiet falco-modern-bpf; then
  echo "!! falco active — mask it first"; exit 1
fi

CI_CELLS="A/command_injection,B/command_injection,C/command_injection"
DT_CELLS="A/detector_takeout+gps_spoofing,B/detector_takeout+gps_spoofing,C/detector_takeout+gps_spoofing"
MT_CELLS="A/monitor_takeout+gps_spoofing,B/monitor_takeout+gps_spoofing,C/monitor_takeout+gps_spoofing"

chunk () {
  local root="$1" cells="$2"
  echo "== $(date '+%m-%d %H:%M:%S')  chunk -> $root =="
  python scripts/run_batch.py -n 5 --post-launch-settle 20 \
    --target-uav uav_0 --log-root "$root" --cells "$cells" 2>&1 | tail -6
  local rc=${PIPESTATUS[0]}
  if [ "$rc" = "3" ]; then
    echo "!! circuit breaker tripped in $root (rc=3). Sim wedged."
    echo "!! Stopping. Reboot/cool the VM, then re-run this script (resumes)."
    exit 3
  fi
  echo "-- cooldown ${COOLDOWN}s --"; sleep "$COOLDOWN"
}

# command_injection: N=15  (3 chunks of 3 cells x n=5 = 9 runs each)
for p in 1 2 3; do chunk "./runs_campaign/ci_pass${p}" "$CI_CELLS"; done

# detector_takeout: N=30  (6 chunks of 9 runs)
for p in 1 2 3 4 5 6; do chunk "./runs_campaign/dt_pass${p}" "$DT_CELLS"; done

# monitor_takeout: N=30   (6 chunks of 9 runs)
for p in 1 2 3 4 5 6; do chunk "./runs_campaign/mt_pass${p}" "$MT_CELLS"; done

echo "== reruns done $(date '+%m-%d %H:%M:%S') =="
echo "analyze with:"
echo "  python campaign_report.py runs_campaign/std_pass1 \\"
echo "    runs_campaign/ci_pass{1,2,3} \\"
echo "    runs_campaign/dt_pass{1,2,3,4,5,6} \\"
echo "    runs_campaign/mt_pass{1,2,3,4,5,6}"
