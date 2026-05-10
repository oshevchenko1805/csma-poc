"""
Structured JSONL event logger.

Each process (monitor, attacker, orchestrator) owns one EventLogger writing
to its own file. After the experiment run, files are merged by timestamp
for analysis. This avoids cross-process file locking complexity at the
cost of a trivial post-hoc merge step.

Design choices:
  - One JSON object per line (JSONL). Survives partial writes; trivial
    to stream-parse with `for line in f: json.loads(line)`.
  - Line-buffered I/O + thread lock so a kill -9 loses at most the line
    in flight, never garbles earlier entries.
  - No external logging frameworks (logging, loguru, structlog). Single
    well-defined responsibility, no surprises.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import IO, Optional

from core.events import BaseEvent, event_from_json


class EventLogger:
    """
    Append-only JSONL writer for typed events.

    Usage:
        logger = EventLogger(Path("results/runs/run_042_monitor_uav_0.jsonl"))
        logger.log(SecurityEvent(source="monitor_uav_0", ...))
        logger.close()

    Or as a context manager:
        with EventLogger(path) as logger:
            logger.log(event)
    """

    def __init__(self, path: Path):
        self.path: Path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f: IO[str] = open(self.path, "a", buffering=1, encoding="utf-8")
        self._lock = threading.Lock()
        self._closed: bool = False
        self._count: int = 0

    def log(self, event: BaseEvent) -> None:
        if self._closed:
            raise RuntimeError(f"EventLogger({self.path}) is closed")
        line = event.to_json()
        with self._lock:
            self._f.write(line + "\n")
            self._count += 1

    def flush(self) -> None:
        with self._lock:
            self._f.flush()

    def close(self) -> None:
        if self._closed:
            return
        with self._lock:
            self._f.flush()
            self._f.close()
            self._closed = True

    @property
    def count(self) -> int:
        """How many events have been written so far."""
        return self._count

    def __enter__(self) -> "EventLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def read_jsonl(path: Path) -> list[BaseEvent]:
    """
    Stream-read a JSONL file back into typed events.

    Skips blank lines but raises on malformed JSON or unknown event_type
    so corrupt logs surface immediately rather than silently producing
    bogus metrics.
    """
    events: list[BaseEvent] = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                events.append(event_from_json(line))
            except (ValueError, json.JSONDecodeError) as e:
                raise ValueError(f"{path}:{lineno}: {e}") from e
    return events


def merge_jsonl(paths: list[Path], output: Path) -> int:
    """
    Merge several per-process JSONL logs into one timestamp-sorted file.

    Returns the total number of events written.
    """
    all_events: list[BaseEvent] = []
    for p in paths:
        all_events.extend(read_jsonl(p))
    all_events.sort(key=lambda e: e.timestamp)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        for ev in all_events:
            f.write(ev.to_json() + "\n")
    return len(all_events)
