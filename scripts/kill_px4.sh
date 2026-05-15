#!/usr/bin/env bash
# Kill all PX4 SITL instances and Gazebo.
#
# Tries PID file first (clean), falls back to pkill by name (sledgehammer).

set -u

LOG_DIR="${LOG_DIR:-/tmp}"
PID_FILE="$LOG_DIR/px4_pids"

if [[ -f "$PID_FILE" ]]; then
    echo "Killing PIDs from $PID_FILE:"
    while read -r pid; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "  TERM $pid"
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done < "$PID_FILE"
    sleep 2
    # Force any survivors
    while read -r pid; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "  KILL $pid"
            kill -KILL "$pid" 2>/dev/null || true
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
fi

# Belt-and-braces: anything matching the PX4 binary, plus Gazebo.
pkill -f 'px4_sitl_default/bin/px4' 2>/dev/null || true
pkill -f 'gz sim' 2>/dev/null || true
pkill -f 'gz-sim' 2>/dev/null || true

sleep 1
echo "done."
