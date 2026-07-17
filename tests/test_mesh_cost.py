"""Tests for metrics.mesh_cost.fleet_mesh_cost (instrumentation item 3).

Pure aggregation — no zmq, no live bus. Snapshots are hand-built or taken
from NoOpMesh, so these run fast and deterministically.
"""

from __future__ import annotations

from core.mesh import NoOpMesh, zero_mesh_counters
from metrics.mesh_cost import fleet_mesh_cost


def _snap(endpoint, published=None, delivered=None, dropped=None):
    """Build a mesh_counters()-shaped snapshot from per-topic dicts."""
    def bucket(per_topic):
        per_topic = per_topic or {}
        return {
            "per_topic": {t: dict(v) for t, v in per_topic.items()},
            "total": {
                "msgs": sum(v["msgs"] for v in per_topic.values()),
                "bytes": sum(v["bytes"] for v in per_topic.values()),
            },
        }

    return {
        "endpoint": endpoint,
        "published": bucket(published),
        "delivered": bucket(delivered),
        "dropped": bucket(dropped),
    }


class TestEmptyFleet:
    def test_no_meshes_gives_all_zero_aggregate(self):
        """Architectures A and B: no mesh instances -> zeros, no branch."""
        agg = fleet_mesh_cost([])
        assert agg["per_peer"] == []
        zero_bucket = {"per_topic": {}, "total": {"msgs": 0, "bytes": 0}}
        assert agg["fleet_total"]["published"] == zero_bucket
        assert agg["fleet_total"]["delivered"] == zero_bucket
        assert agg["fleet_total"]["dropped"] == zero_bucket

    def test_noop_mesh_snapshot_folds_to_zero(self):
        """A NoOpMesh in the list (via DI) still aggregates to zero."""
        agg = fleet_mesh_cost([NoOpMesh().mesh_counters()])
        assert agg["fleet_total"]["published"]["total"] == {"msgs": 0, "bytes": 0}
        assert agg["fleet_total"]["delivered"]["total"] == {"msgs": 0, "bytes": 0}
        # zero_mesh_counters is the same shape the ABC default emits.
        assert agg["per_peer"][0] == zero_mesh_counters(endpoint=None)


class TestSinglePeer:
    def test_single_peer_total_mirrors_its_buckets(self):
        snap = _snap(
            "tcp://127.0.0.1:5550",
            published={"security": {"msgs": 3, "bytes": 300},
                       "isolation": {"msgs": 1, "bytes": 90}},
            delivered={"security": {"msgs": 2, "bytes": 200}},
        )
        agg = fleet_mesh_cost([snap])

        pub = agg["fleet_total"]["published"]
        assert pub["per_topic"]["security"] == {"msgs": 3, "bytes": 300}
        assert pub["per_topic"]["isolation"] == {"msgs": 1, "bytes": 90}
        assert pub["total"] == {"msgs": 4, "bytes": 390}

        deliv = agg["fleet_total"]["delivered"]
        assert deliv["total"] == {"msgs": 2, "bytes": 200}


class TestMultiPeer:
    def test_sums_per_topic_across_peers(self):
        a = _snap("ep_a", published={"security": {"msgs": 2, "bytes": 200}})
        b = _snap(
            "ep_b",
            published={"security": {"msgs": 1, "bytes": 100},
                       "recovery_req": {"msgs": 4, "bytes": 480}},
        )
        c = _snap("ep_c", delivered={"security": {"msgs": 5, "bytes": 500}})

        agg = fleet_mesh_cost([a, b, c])
        pub = agg["fleet_total"]["published"]
        assert pub["per_topic"]["security"] == {"msgs": 3, "bytes": 300}
        assert pub["per_topic"]["recovery_req"] == {"msgs": 4, "bytes": 480}
        assert pub["total"] == {"msgs": 7, "bytes": 780}
        assert agg["fleet_total"]["delivered"]["total"] == {"msgs": 5, "bytes": 500}

    def test_dropped_sums_across_peers(self):
        """Item-4 loss: dropped frames aggregate into fleet_total.dropped."""
        a = _snap("ep_a", dropped={"security": {"msgs": 3, "bytes": 300}})
        b = _snap(
            "ep_b",
            delivered={"security": {"msgs": 7, "bytes": 700}},
            dropped={"security": {"msgs": 1, "bytes": 100}},
        )
        agg = fleet_mesh_cost([a, b])
        assert agg["fleet_total"]["dropped"]["total"] == {"msgs": 4, "bytes": 400}
        assert agg["fleet_total"]["delivered"]["total"] == {"msgs": 7, "bytes": 700}

    def test_per_peer_is_preserved_and_independent(self):
        a = _snap("ep_a", published={"security": {"msgs": 2, "bytes": 200}})
        b = _snap("ep_b", published={"security": {"msgs": 1, "bytes": 100}})
        agg = fleet_mesh_cost([a, b])

        assert [p["endpoint"] for p in agg["per_peer"]] == ["ep_a", "ep_b"]
        assert agg["per_peer"][0] == a
        # Deep copy: mutating the aggregate must not touch the input.
        agg["per_peer"][0]["published"]["total"]["msgs"] = 999
        assert a["published"]["total"]["msgs"] == 2
