#!/usr/bin/env bash
# Launch 3 PX4 SITL instances with Gazebo (gz_x500) in background.
#
# Layout:
#   inst 0  -> sysid 1, MAVLink port 14540, pose offset  (0,0,0)
#   inst 1  -> sysid 2, MAVLink port 14541, pose offset  (2,0,0)
#   inst 2  -> sysid 3, MAVLink port 14542, pose offset  (4,0,0)
#
# Per-instance logs:    /tmp/px4_inst_{0,1,2}.log
# PID file (for kill):  /tmp/px4_pids
#
# Usage:
#   scripts/launch_px4.sh                    # uses ~/PX4-Autopilot
#   PX4_DIR=/path/to/px4 scripts/launch_px4.sh
#
# Stop:
#   scripts/kill_px4.sh   # or: pkill -f 'px4_sitl_default/bin/px4'
 
set -u
 
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
PX4_BIN="$PX4_DIR/build/px4_sitl_default/bin/px4"
LOG_DIR="${LOG_DIR:-/tmp}"
PID_FILE="$LOG_DIR/px4_pids"
 
if [[ ! -x "$PX4_BIN" ]]; then
    echo "ERROR: PX4 binary not found at $PX4_BIN" >&2
    echo "Build first: cd $PX4_DIR && make px4_sitl gz_x500" >&2
    exit 1
fi
 
# Refuse to launch if something is already running on the target ports —
# stale PX4 processes are the #1 cause of confusing startup behaviour.
for port in 14540 14541 14542; do
    if ss -uln 2>/dev/null | awk '{print $5}' | grep -qE ":${port}\$"; then
        echo "ERROR: UDP port $port already bound. Run scripts/kill_px4.sh first." >&2
        exit 1
    fi
done
 
mkdir -p "$LOG_DIR"
rm -f "$PID_FILE"
 
cd "$PX4_DIR"
 
# Auto-clean PX4 ulog files from previous runs (~100-200 MB per instance per
# run). Without this, a 30 GB VM fills up within ~10-15 runs.
ULOG_BYTES=$(du -sb build/px4_sitl_default/rootfs/*/log/ 2>/dev/null \
             | awk '{s+=$1} END {print s+0}')
if [[ "$ULOG_BYTES" -gt 0 ]]; then
    ULOG_HUMAN=$(numfmt --to=iec --suffix=B "$ULOG_BYTES" 2>/dev/null || echo "${ULOG_BYTES}B")
    echo "Cleaning $ULOG_HUMAN of stale PX4 ulog files from previous runs..."
    rm -rf build/px4_sitl_default/rootfs/*/log/* 2>/dev/null || true
fi
# Also clean stale Gazebo logs (less critical, ~tens of MB).
rm -rf "$HOME/.gz/log/"* 2>/dev/null || true
 
launch_inst() {
    local inst=$1
    local pose=$2
    local logfile="$LOG_DIR/px4_inst_${inst}.log"
    echo "  launching instance $inst (pose=$pose) -> log: $logfile"
    env \
        PX4_SYS_AUTOSTART=4001 \
        PX4_GZ_MODEL=x500 \
        PX4_GZ_MODEL_POSE="$pose" \
        "$PX4_BIN" -i "$inst" \
        > "$logfile" 2>&1 &
    echo $! >> "$PID_FILE"
}
 
echo "Launching 3 PX4 SITL instances. Build: $PX4_DIR"
echo
 
# Instance 0: also launches Gazebo. Wait longer before next.
launch_inst 0 "0,0,0,0,0,0"
echo "  waiting 20s for Gazebo to come up..."
sleep 20
 
launch_inst 1 "2,0,0,0,0,0"
sleep 4
 
launch_inst 2 "4,0,0,0,0,0"
sleep 4
 
echo
echo "PIDs: $(cat "$PID_FILE" | tr '\n' ' ')"
echo "Wait another ~10s for full boot, then verify with:"
echo "  ss -ulnp 2>/dev/null | grep -E '1454[012]'"
echo "  tail -2 /tmp/px4_inst_*.log"
