"""
TrajectoryRecorder — independent ground-truth trajectory logging.

Why this exists
---------------
Every other observation channel in this PoC is *inside* the system under
test, and the experiments deliberately attack that system:

  * Monitors are stopped or blinded by monitor_takeout / detector_takeout,
    so anything they log disappears exactly when the incident happens.
  * PX4's own estimate is corrupted by construction under GPS spoofing:
    the injected offset moves the estimated position, so the UAV believes
    it is on course while it physically drifts. MAVSDK telemetry reports
    that belief, not reality.

Measuring physical consequence therefore requires an observer *outside*
the system: Gazebo's model poses. Gazebo is the simulator's own physics
ground truth — it cannot be spoofed by a PX4 param, and it does not care
whether monitors are alive. This is the simulation analogue of an
external motion-capture rig in a real flight test, and it is what makes
mission-level metrics (residual functionality, degradation) and
coordination metrics (true inter-UAV geometry) measurable at all — none
of which can be reconstructed after the fact from event logs.

What it records
---------------
One JSONL line per (sample, UAV):

    {"t_wall": 1784195298.42,   # wall clock at receipt — aligns with
                                # merged.jsonl event timestamps
     "t_sim": 576.148,          # Gazebo sim clock from the message header
     "uav_id": "uav_0",
     "x": 0.0866, "y": -0.0075, "z": -0.0130,     # world frame, metres
     "qx": .., "qy": .., "qz": .., "qw": ..}      # orientation

Both clocks are stored on purpose. Gazebo stamps messages with *sim*
time, while every event in merged.jsonl (attacks, detections, recovery)
carries wall-clock time. Correlating "how far had it drifted when the
attack fired" needs a common axis, so the recorder timestamps each
sample with the wall clock at receipt and keeps the sim stamp for
precise in-simulation timing.

Design
------
- The line source is injected (DI): production spawns
  `gz topic -e -t <topic> --json-output` as a subprocess and reads its
  stdout; tests pass a plain iterable of strings. No gz needed in tests.
- Reading happens on a daemon thread (the gz process emits ~50 Hz and a
  blocking readline is the simplest reliable reader), mirroring how
  Monitor runs its listener.
- Samples are throttled by wall-clock interval (default 5 Hz) rather
  than "every Nth message", so the output rate is stable even if Gazebo's
  publish rate changes.
- Never raises into the experiment: malformed lines, unknown models and
  a missing gz binary are counted and skipped. A failed recorder must not
  fail a flight — it degrades to an empty trajectory file, which the
  analysis layer reports honestly as missing data.
- Writes to its own file (`trajectory.jsonl`). It does NOT touch
  core.events, core.logger or merged.jsonl, so the event schema and the
  existing analyzer are untouched.

Source exhaustion vs stop()
---------------------------
In production the source never ends: gz streams until the recorder is
stopped, so stop() interrupting the reader is exactly right. A *finite*
source (a test list, or a gz process that died) ends on its own, and
callers may want to know. `wait_done(timeout)` blocks until the reader
thread has exhausted the source or errored out; `done` reports it without
blocking. Without this, stop() right after start() would race the reader
and silently truncate a finite source.

Model naming
------------
PX4 SITL multi-instance spawns models named `x500_<i>` where <i> is the
instance index, the same index behind endpoints 14540+i / 14560+i and
uav ids `uav_<i>`. The default mapper follows that convention; pass
`model_to_uav` to override.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

DEFAULT_TOPIC = "/world/default/pose/info"
DEFAULT_SAMPLE_HZ = 5.0

_MODEL_RE = re.compile(r"^x500_(\d+)$")


def default_model_to_uav(model_name: str) -> Optional[str]:
    """`x500_2` -> `uav_2`. Returns None for anything else (ground_plane,
    sun, sub-links), which the recorder then skips."""
    m = _MODEL_RE.match(model_name)
    if not m:
        return None
    return f"uav_{int(m.group(1))}"


def gz_line_source(topic: str = DEFAULT_TOPIC) -> Iterator[str]:
    """Production line source: stream JSON lines from `gz topic -e`.

    Yields one raw line per Gazebo message. Closing the generator (or
    garbage-collecting it) terminates the subprocess.
    """
    proc = subprocess.Popen(
        ["gz", "topic", "-e", "-t", topic, "--json-output"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            yield line
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


LineSourceFactory = Callable[[], Iterable[str]]


class TrajectoryRecorder:
    """Record Gazebo ground-truth poses to JSONL on a background thread."""

    def __init__(
        self,
        *,
        out_path: Path,
        line_source_factory: Optional[LineSourceFactory] = None,
        topic: str = DEFAULT_TOPIC,
        sample_hz: float = DEFAULT_SAMPLE_HZ,
        model_to_uav: Callable[[str], Optional[str]] = default_model_to_uav,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if sample_hz <= 0:
            raise ValueError("sample_hz must be positive")

        self._out_path = Path(out_path)
        self._factory: LineSourceFactory = (
            line_source_factory
            if line_source_factory is not None
            else (lambda: gz_line_source(topic))
        )
        self._period = 1.0 / sample_hz
        self._model_to_uav = model_to_uav
        self._clock = clock

        self._stop_event = threading.Event()
        self._done_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fh = None
        self._source: Optional[Iterable[str]] = None
        self._last_sample_t: float = 0.0
        self._write_lock = threading.Lock()

        self.stats: dict[str, int] = {
            "lines_read": 0,
            "samples_written": 0,
            "parse_errors": 0,
            "source_errors": 0,
        }

    # ----- lifecycle -----

    def start(self) -> None:
        if self._thread is not None:
            return
        self._out_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._out_path.open("a")
        self._thread = threading.Thread(
            target=self._run, name="trajectory-recorder", daemon=True
        )
        self._thread.start()

    @property
    def done(self) -> bool:
        """True once the reader thread has exhausted the source or errored.
        Always False for a live gz stream until stop() is called."""
        return self._done_event.is_set()

    def wait_done(self, timeout: Optional[float] = None) -> bool:
        """Block until the source is exhausted (or the reader errors).

        Returns True if it finished within the timeout. Meaningful for
        finite sources (tests) or to notice a gz process that died; a live
        gz stream never finishes on its own, so callers of a real recording
        use stop() instead.
        """
        return self._done_event.wait(timeout)

    def stop(self) -> None:
        """Idempotent. Stops the reader and closes the file."""
        self._stop_event.set()
        # Closing the generator terminates the gz subprocess, which makes
        # the blocking readline in _run return.
        src = self._source
        if src is not None and hasattr(src, "close"):
            try:
                src.close()  # type: ignore[attr-defined]
            except Exception:
                pass
        t = self._thread
        if t is not None:
            t.join(timeout=5.0)
            self._thread = None
        with self._write_lock:
            if self._fh is not None:
                try:
                    self._fh.flush()
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None

    def __enter__(self) -> "TrajectoryRecorder":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # ----- internals -----

    def _run(self) -> None:
        try:
            self._source = self._factory()
            for line in self._source:
                if self._stop_event.is_set():
                    break
                self.stats["lines_read"] += 1
                self._handle_line(line)
        except Exception:
            # A dead gz / broken pipe must never kill the flight.
            self.stats["source_errors"] += 1
        finally:
            self._done_event.set()

    def _handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return

        now = self._clock()
        # Throttle on wall time: stable output rate regardless of the
        # publisher's rate.
        if now - self._last_sample_t < self._period:
            return

        try:
            msg = json.loads(line)
            poses = msg.get("pose") or []
            stamp = (msg.get("header") or {}).get("stamp") or {}
            t_sim = float(stamp.get("sec", 0)) + float(
                stamp.get("nsec", 0)
            ) / 1e9
        except Exception:
            self.stats["parse_errors"] += 1
            return

        wrote = False
        for p in poses:
            uav_id = self._model_to_uav(str(p.get("name", "")))
            if uav_id is None:
                continue
            pos = p.get("position") or {}
            ori = p.get("orientation") or {}
            rec = {
                "t_wall": now,
                "t_sim": t_sim,
                "uav_id": uav_id,
                # Gazebo omits zero-valued fields in JSON, hence the
                # explicit 0.0 defaults.
                "x": float(pos.get("x", 0.0)),
                "y": float(pos.get("y", 0.0)),
                "z": float(pos.get("z", 0.0)),
                "qx": float(ori.get("x", 0.0)),
                "qy": float(ori.get("y", 0.0)),
                "qz": float(ori.get("z", 0.0)),
                "qw": float(ori.get("w", 0.0)),
            }
            with self._write_lock:
                if self._fh is None:
                    return
                self._fh.write(json.dumps(rec) + "\n")
            self.stats["samples_written"] += 1
            wrote = True

        if wrote:
            self._last_sample_t = now
            with self._write_lock:
                if self._fh is not None:
                    self._fh.flush()
