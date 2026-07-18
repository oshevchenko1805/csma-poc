"""Tests for wiring mesh delay config into ZmqMesh via the factory
(instrumentation item 4b, step 3).

Constructing a ZmqMesh here does not bind sockets (that happens in
start()), so this is fast and needs no live peers — pyzmq must be
importable (it is in the C runtime env).
"""

from __future__ import annotations

from core.config import MeshConfig
from core.mesh import ZmqMesh
from runners.factory import _make_default_mesh_factory


class TestFactoryDelayWiring:
    def test_passes_delay_from_config(self):
        cfg = MeshConfig(
            enabled=True,
            transport="zeromq",
            endpoints={"uav_0": "tcp://127.0.0.1:5550"},
            delay_sec=0.2,
        )
        mesh = _make_default_mesh_factory(cfg)("tcp://127.0.0.1:5550", [])
        assert isinstance(mesh, ZmqMesh)
        assert mesh._delay_sec == 0.2

    def test_default_config_has_zero_delay(self):
        cfg = MeshConfig(
            enabled=True,
            transport="zeromq",
            endpoints={"uav_0": "tcp://127.0.0.1:5550"},
        )
        mesh = _make_default_mesh_factory(cfg)("tcp://127.0.0.1:5550", [])
        assert mesh._delay_sec == 0.0
