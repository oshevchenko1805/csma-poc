"""
patch_fp_baseline.py — fix false-positive accounting for baseline runs.

Defect
------
`campaign_extras.fp_background` treated the run's `attack` event as the
boundary of the clean window. On a BASELINE run (`attack_name == "none"`)
the runner still emits an `attack` marker at the nominal instant even
though nothing is injected, so every security event after that marker
was excluded from the false-positive count.

That is exactly backwards: on a baseline run the WHOLE flight is clean
operation, and a security event anywhere in it is a false positive by
definition. The defect hid at least one measured case —
`B_none_r4_1785487217`, where a false gps detection triggered an
isolation and cost 190 m of phase divergence on a healthy fleet.

Idempotent: re-running is a no-op.

    python patch_fp_baseline.py
"""

import io
import os
import sys

TARGET = "campaign_extras.py"

ANCHOR = """        arch = str(summary.get("architecture") or "?")
        rec = per[arch]
        rec["runs"] += 1

        events = D.load_events(run_dir)
        t0 = _attack_ts(events)
        t_start = _telemetry_start(run_dir)

        if t0 is not None and t_start is not None and t0 > t_start:
            rec["exposure_s"] += t0 - t_start
        elif t0 is None:
            rec["exposure_s"] += float(summary.get("duration_sec") or 0.0)

        pre = [e for e in events
               if e.get("event_type") == "security"
               and (t0 is None or float(e["timestamp"]) < t0)]
"""

REPLACEMENT = """        arch = str(summary.get("architecture") or "?")
        rec = per[arch]
        rec["runs"] += 1

        events = D.load_events(run_dir)
        t0 = _attack_ts(events)
        t_start = _telemetry_start(run_dir)

        # A baseline run carries an `attack` marker at the nominal instant
        # even though nothing is injected. Treating that marker as the end
        # of the clean window discards most of the run — and with it any
        # false positive that fired in the second half. On a baseline run
        # the whole flight is clean operation.
        is_baseline = str(summary.get("attack_name") or "none").lower() in ("", "none")
        boundary = None if is_baseline else t0

        if boundary is not None and t_start is not None and boundary > t_start:
            rec["exposure_s"] += boundary - t_start
        elif boundary is None:
            rec["exposure_s"] += float(summary.get("duration_sec") or 0.0)

        pre = [e for e in events
               if e.get("event_type") == "security"
               and (boundary is None or float(e["timestamp"]) < boundary)]
"""

GUARD = "is_baseline = str(summary.get"


def main() -> None:
    if not os.path.exists(TARGET):
        sys.exit("!! %s not found — run from the repo root" % TARGET)

    with io.open(TARGET, encoding="utf-8") as fh:
        text = fh.read()

    if GUARD in text:
        print("already patched — nothing to do")
        return

    count = text.count(ANCHOR)
    assert count == 1, "anchor matched %d times, expected exactly 1" % count

    with io.open(TARGET + ".bak", "w", encoding="utf-8") as fh:
        fh.write(text)

    with io.open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(text.replace(ANCHOR, REPLACEMENT))

    print("patched %s (backup at %s.bak)" % (TARGET, TARGET))
    print("baseline runs now count the whole flight as clean-mode exposure")


if __name__ == "__main__":
    main()
