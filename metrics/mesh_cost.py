"""
Fleet-level aggregation of mesh cost counters (instrumentation item 3).

Each MeshBus reports its own traffic via `mesh_counters()`:

    {"endpoint": <str|None>,
     "published": {"per_topic": {topic: {"msgs", "bytes"}}, "total": {...}},
     "delivered": {"per_topic": {topic: {"msgs", "bytes"}}, "total": {...}},
     "dropped":   {"per_topic": {topic: {"msgs", "bytes"}}, "total": {...}}}

`dropped` counts frames erased by the item-4 loss model (zero unless loss
is enabled). `fleet_mesh_cost` folds a list of those snapshots into one
view for run_summary.json: every peer preserved as-is under `per_peer`,
plus a `fleet_total` that sums each of the three streams per topic and
overall across peers.

Pure function, no I/O, no architecture branch. Architectures A and B hold
no mesh instances, so the caller passes an empty list and gets an all-zero
aggregate — the baseline against which C's detection cost is measured.
That the difference is "an empty list" rather than "an if" is the point:
the cost asymmetry is data, not code.

Scope note (thesis 3.5.5): these counters describe the transport, which
exists only in C. They are an engineering characterisation of the mesh
(messages/bytes per run), NOT one of the five security-property metrics in
table 3.13. Read "C detects, at a cost of X messages A and B never pay".
"""

from __future__ import annotations

import copy
from typing import Any


def _empty_bucket() -> dict[str, Any]:
    return {"per_topic": {}, "total": {"msgs": 0, "bytes": 0}}


def _accumulate(acc: dict[str, Any], bucket: dict[str, Any]) -> None:
    """Add one peer's bucket (published or delivered) into the accumulator."""
    for topic, counts in bucket.get("per_topic", {}).items():
        slot = acc["per_topic"].setdefault(topic, {"msgs": 0, "bytes": 0})
        slot["msgs"] += counts.get("msgs", 0)
        slot["bytes"] += counts.get("bytes", 0)


def _finalise_total(acc: dict[str, Any]) -> dict[str, Any]:
    """Recompute the total from the merged per-topic tallies.

    Derived from per_topic rather than summing peer totals so the two can
    never silently disagree: one source of truth.
    """
    acc["total"]["msgs"] = sum(v["msgs"] for v in acc["per_topic"].values())
    acc["total"]["bytes"] = sum(v["bytes"] for v in acc["per_topic"].values())
    return acc


def fleet_mesh_cost(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold per-peer mesh_counters() snapshots into a fleet aggregate.

    Parameters
    ----------
    snapshots
        One `mesh_counters()` result per MeshBus in the fleet. Empty for
        Architectures A and B (no mesh) — yields an all-zero aggregate.

    Returns
    -------
    {"per_peer": [<snapshot>, ...],
     "fleet_total": {"published": <bucket>, "delivered": <bucket>,
                     "dropped": <bucket>}}
    """
    published = _empty_bucket()
    delivered = _empty_bucket()
    dropped = _empty_bucket()

    for snap in snapshots:
        _accumulate(published, snap.get("published", {}))
        _accumulate(delivered, snap.get("delivered", {}))
        _accumulate(dropped, snap.get("dropped", {}))

    _finalise_total(published)
    _finalise_total(delivered)
    _finalise_total(dropped)

    return {
        "per_peer": copy.deepcopy(snapshots),
        "fleet_total": {
            "published": published,
            "delivered": delivered,
            "dropped": dropped,
        },
    }
