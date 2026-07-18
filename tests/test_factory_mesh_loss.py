"""Tests for wiring mesh loss config into ZmqMesh via the factory
(instrumentation item 4a, step 3).

Two concerns:
  - _derive_peer_seed: distinct per endpoint, reproducible across processes,
    None-safe.
  - _make_default_mesh_factory: loss_prob/loss_seed from config actually
    reach the constructed ZmqMesh; default 0.0 leaves it lossless.

Constructing a ZmqMesh here does NOT bind sockets (that happens in start()),
so these are fast and need no live peers — but pyzmq must be importable
(it is in the C runtime env).
"""

from __future__ import annotations

from core.config import MeshConfig
from core.mesh import ZmqMesh
from runners.factory import _derive_peer_seed, _make_default_mesh_factory


class TestDerivePeerSeed:
    def test_none_base_stays_none(self):
        assert _derive_peer_seed(None, "tcp://127.0.0.1:5550") is None

    def test_distinct_per_endpoint(self):
        s0 = _derive_peer_seed(7, "tcp://127.0.0.1:5550")
        s1 = _derive_peer_seed(7, "tcp://127.0.0.1:5551")
        assert s0 != s1

    def test_reproducible_across_processes(self):
        # Hard-coded value locks reproducibility: crc32 is not salted, so
        # this must hold in any process (unlike hash()).
        assert _derive_peer_seed(7, "tcp://127.0.0.1:5550") == 1496109880

    def test_stable_on_repeat(self):
        ep = "tcp://127.0.0.1:5552"
        assert _derive_peer_seed(42, ep) == _derive_peer_seed(42, ep)


class TestMakeDefaultMeshFactory:
    def test_passes_loss_prob_from_config(self):
        cfg = MeshConfig(
            enabled=True,
            transport="zeromq",
            endpoints={"uav_0": "tcp://127.0.0.1:5550"},
            loss_prob=0.3,
            loss_seed=7,
        )
        factory = _make_default_mesh_factory(cfg)
        mesh = factory("tcp://127.0.0.1:5550", [])
        assert isinstance(mesh, ZmqMesh)
        assert mesh._loss_prob == 0.3

    def test_default_config_is_lossless(self):
        cfg = MeshConfig(
            enabled=True,
            transport="zeromq",
            endpoints={"uav_0": "tcp://127.0.0.1:5550"},
        )
        factory = _make_default_mesh_factory(cfg)
        mesh = factory("tcp://127.0.0.1:5550", [])
        assert mesh._loss_prob == 0.0
