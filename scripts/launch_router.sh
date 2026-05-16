#!/usr/bin/env bash
# Launch 3 mavlink-routerd instances, one per PX4 SITL UAV.
#
# Each router instance binds PX4's destination port (14540+i), receives
# the onboard MAVLink stream from that PX4 inst, and fans it out to two
# consumers:
#   - Monitor side (pymavlink udpin)   on 14570+i
#   - MAVSDK side  (mavsdk_server)     on 14560+i
#
# This resolves the port-14540 conflict that blocked step 10b
# (PROJECT_STATE.md §13, Option A).
#
# Layout (per UAV i):
#   PX4 inst i  --UDP-->  router_inst${i}  --+-->  Monitor   :1457${i}
#                                            +-->  MAVSDK    :1456${i}
#
# Per-instance logs: /tmp/router_inst_{0,1,2}.log
# PID file:          /tmp/router_pids   (one PID per line, sysid order)
#
# Usage:
#   scripts/launch_router.sh
#
# Stop:
#   scripts/kill_router.sh
#
# IMPORTANT — order of operations:
#   1. scripts/launch_px4.sh    (PX4 starts; does NOT bind 14540-14542)
#   2. scripts/launch_router.sh (router binds 14540-14542 and fans out)
# Reverse order works for the router but launch_px4.sh refuses to start
# when 14540+ are bound.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF_DIR="${ROUTER_CONF_DIR:-$REPO_ROOT/configs/router}"
LOG_DIR="${LOG_DIR:-/tmp}"
PID_FILE="$LOG_DIR/router_pids"

# Sanity: binary present
if ! command -v mavlink-routerd >/dev/null 2>&1; then
    echo "ERROR: mavlink-routerd not in PATH." >&2
    echo "Install: build from source at https://github.com/mavlink-router/mavlink-router" >&2
    exit 1
fi

# Sanity: all three config files present
for i in 0 1 2; do
    if [[ ! -f "$CONF_DIR/router_inst${i}.conf" ]]; then
        echo "ERROR: missing config: $CONF_DIR/router_inst${i}.conf" >&2
        exit 1
    fi
done

# Refuse if input ports already bound (stale router, or unexpected listener).
# 14570+/14560+ are bind-by-consumer ports, so we don't check those here —
# they're allowed to be in use (e.g. Monitor is already listening before
# the router catches up).
for port in 14540 14541 14542; do
    if ss -uln 2>/dev/null | awk '{print $5}' | grep -qE ":${port}\$"; then
        echo "ERROR: UDP port $port already bound. Run scripts/kill_router.sh first." >&2
        echo "       (or kill whatever else holds it)" >&2
        exit 1
    fi
done

mkdir -p "$LOG_DIR"
rm -f "$PID_FILE"

launch_router() {
    local inst=$1
    local conf="$CONF_DIR/router_inst${inst}.conf"
    local logfile="$LOG_DIR/router_inst_${inst}.log"
    echo "  launching router inst $inst -> log: $logfile"
    mavlink-routerd -c "$conf" > "$logfile" 2>&1 &
    echo $! >> "$PID_FILE"
}

echo "Launching 3 mavlink-routerd instances. Configs: $CONF_DIR"
echo

launch_router 0
launch_router 1
launch_router 2

# Give the routers a moment to bind their UDP server sockets so the verify
# command below shows the right thing.
sleep 1

echo
echo "PIDs: $(cat "$PID_FILE" | tr '\n' ' ')"
echo "Verify with:"
echo "  ss -ulnp 2>/dev/null | grep -E '1454[012]'   # routers bound on PX4 side"
echo "  tail -n 5 /tmp/router_inst_0.log /tmp/router_inst_1.log /tmp/router_inst_2.log"
