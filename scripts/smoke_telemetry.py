"""
Live smoke-test for core.telemetry against a running PX4 SITL.

This is NOT a pytest. Run it manually:

    cd ~/csma_poc_v2
    source .venv/bin/activate

    # In another terminal, start PX4 SITL instance 0:
    #   cd ~/PX4-Autopilot
    #   PX4_SYS_AUTOSTART=4001 PX4_GZ_MODEL=x500 \
    #     ./build/px4_sitl_default/bin/px4 -i 0

    python scripts/smoke_telemetry.py

Expected output: counts > 0 for HEARTBEAT, GLOBAL_POSITION_INT, ATTITUDE,
ESTIMATOR_STATUS, and SYS_STATUS over ~10 seconds. STATUSTEXT may be 0
during steady-state idle. COMMAND_* will be 0 unless GCS is sending.

Defaults assume PX4 instance 0:
  endpoint     udpin:127.0.0.1:14540
  sysid        1            (PX4 instance i -> sysid i+1)

Override via CLI args:
  python scripts/smoke_telemetry.py --endpoint udpin:127.0.0.1:14541 --sysid 2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

# Allow running this file directly: add project root to sys.path so the
# 'core' package is importable.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.events import TelemetryEvent  # noqa: E402
from core.telemetry import DEFAULT_MSG_WHITELIST, TelemetryListener  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="udpin:127.0.0.1:14540")
    parser.add_argument("--sysid", type=int, default=1)
    parser.add_argument("--uav-id", default="uav_0")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument(
        "--show-samples",
        action="store_true",
        help="Print one sample TelemetryEvent per message type",
    )
    args = parser.parse_args()

    counts: Counter[str] = Counter()
    samples: dict[str, TelemetryEvent] = {}

    def on_event(ev: TelemetryEvent) -> None:
        counts[ev.msg_type] += 1
        if ev.msg_type not in samples:
            samples[ev.msg_type] = ev

    print(f"Listening on {args.endpoint} (sysid={args.sysid}) for {args.duration:.0f}s...")
    print(f"Whitelist: {sorted(DEFAULT_MSG_WHITELIST)}")
    print()

    listener = TelemetryListener(
        endpoint=args.endpoint,
        expected_sysid=args.sysid,
        uav_id=args.uav_id,
        source=f"smoke_{args.uav_id}",
        callback=on_event,
    )

    listener.start()
    try:
        time.sleep(args.duration)
    finally:
        listener.stop()

    print()
    print("=== Receive stats ===")
    for k, v in listener.stats.items():
        print(f"  {k:20s} {v}")

    print()
    print("=== Per-message-type counts ===")
    if not counts:
        print("  (none) — check PX4 is running and endpoint/sysid are correct")
    else:
        for msg_type in sorted(counts.keys()):
            rate = counts[msg_type] / args.duration
            print(f"  {msg_type:25s} {counts[msg_type]:5d}  ({rate:5.1f} Hz)")

    if args.show_samples and samples:
        print()
        print("=== Sample event per type ===")
        for msg_type in sorted(samples.keys()):
            ev = samples[msg_type]
            preview = json.dumps(ev.data, indent=2, default=str)
            if len(preview) > 400:
                preview = preview[:400] + "..."
            print(f"\n[{msg_type}]")
            print(preview)

    # PASS criterion: at least HEARTBEAT and GLOBAL_POSITION_INT received.
    required = {"HEARTBEAT", "GLOBAL_POSITION_INT"}
    missing = required - set(counts.keys())
    if missing:
        print()
        print(f"FAIL: required message types not received: {sorted(missing)}")
        return 1
    print()
    print("OK: required message types received.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

