#!/usr/bin/env bash
# Full CSMA campaign driver.
#
# Design: randomized-block by pass. Each pass is one run_batch call over
# ALL cells in its group with n=5, written to its own log-root. Running
# several passes instead of one big -n spreads any VM drift (thermal
# throttling, degradation after hundreds of PX4 starts, disk fill)
# evenly across A/B/C, so the architecture difference stays
# architectural rather than confounded with time-of-run.
#
#   Standard + baseline  : 12 cells x 3 passes = N=15 per cell (180 runs)
#   Takeout (core)       :  6 cells x 6 passes = N=30 per cell (180 runs)
#   Total ~360 runs, ~24 h.
#
# Run inside tmux, with `caffeinate -dims` on the Mac so it doesn't sleep.
# Resumable: run_batch skips trials with a prior exit-0 run dir, so if a
# pass dies you can re-run this script and it continues.

set -u
cd ~/csma_poc_v2 || exit 1
source .venv/bin/activate

# ---- preflight --------------------------------------------------------
echo "== preflight =="
git log --oneline -1
if systemctl is-active --quiet falco-modern-bpf; then
  echo "!! falco is ACTIVE — mask it before running (it floods syslog + skews timing):"
  echo "   sudo systemctl mask 'falco*' 'falcoctl*'"
  exit 1
fi
echo "falco: inactive (good)"
df -h / | tail -1

STD_CELLS="A/none,B/none,C/none,\
A/gps_spoofing,B/gps_spoofing,C/gps_spoofing,\
A/comm_disruption,B/comm_disruption,C/comm_disruption,\
A/command_injection,B/command_injection,C/command_injection"

TAKEOUT_CELLS="A/detector_takeout+gps_spoofing,B/detector_takeout+gps_spoofing,C/detector_takeout+gps_spoofing,\
A/monitor_takeout+gps_spoofing,B/monitor_takeout+gps_spoofing,C/monitor_takeout+gps_spoofing"

run_pass () {
  local root="$1" cells="$2"
  echo "== $(date '+%H:%M:%S')  pass -> $root =="
  python scripts/run_batch.py -n 5 --post-launch-settle 20 \
    --target-uav uav_0 \
    --log-root "$root" --cells "$cells" 2>&1 | tail -4
}

# ---- standard + baseline, 3 passes (N=15) -----------------------------
for p in 1 2 3; do
  run_pass "./runs_campaign/std_pass${p}" "$STD_CELLS"
done

# ---- takeout core, 6 passes (N=30) ------------------------------------
for p in 1 2 3 4 5 6; do
  run_pass "./runs_campaign/takeout_pass${p}" "$TAKEOUT_CELLS"
done

echo "== campaign done $(date '+%H:%M:%S') =="
echo "std passes:     runs_campaign/std_pass{1,2,3}"
echo "takeout passes: runs_campaign/takeout_pass{1..6}"
