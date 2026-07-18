"""Tests for the mesh delay config knob (instrumentation item 4b, step 2).

MeshConfig.delay_sec: default, validation, parsing, and the cross-field
invariant that delay only applies to an enabled (C) mesh.
"""

from __future__ import annotations

import pytest

from core.config import (
    ArchitectureConfig,
    ConfigError,
    IsolationConfig,
    MeshConfig,
    MonitorSpec,
    RecoveryConfig,
    _parse_mesh,
    _validate_architecture_invariants,
)


class TestMeshConfigDelayField:
    def test_default_is_zero(self):
        m = MeshConfig(enabled=True, transport="zeromq", endpoints={})
        assert m.delay_sec == 0.0

    def test_rejects_negative_delay(self):
        with pytest.raises(ConfigError, match="delay_sec"):
            MeshConfig(
                enabled=True, transport="zeromq", endpoints={}, delay_sec=-0.1
            )

    def test_accepts_positive_delay(self):
        m = MeshConfig(
            enabled=True, transport="zeromq", endpoints={}, delay_sec=0.25
        )
        assert m.delay_sec == 0.25


class TestParseMeshDelay:
    def test_reads_delay(self):
        m = _parse_mesh(
            {
                "enabled": True,
                "transport": "zeromq",
                "endpoints": {"uav_0": "tcp://127.0.0.1:5550"},
                "delay_sec": 0.15,
            }
        )
        assert m.delay_sec == 0.15

    def test_defaults_when_absent(self):
        m = _parse_mesh({"enabled": False, "transport": "noop"})
        assert m.delay_sec == 0.0


def _arch_a(mesh: MeshConfig) -> ArchitectureConfig:
    return ArchitectureConfig(
        architecture="A",
        monitors=(
            MonitorSpec(
                location="ground_station",
                watches=("uav_0",),
                detectors=("heartbeat",),
            ),
        ),
        mesh=mesh,
        recovery=RecoveryConfig(enabled=False, coordinator_election="none"),
        isolation=IsolationConfig(enforcement="ground_station_command"),
    )


def _arch_c(mesh: MeshConfig) -> ArchitectureConfig:
    return ArchitectureConfig(
        architecture="C",
        monitors=(
            MonitorSpec(
                location="uav_0", watches=("uav_0",), detectors=("gps",)
            ),
        ),
        mesh=mesh,
        recovery=RecoveryConfig(
            enabled=True, coordinator_election="lowest_alive_sysid"
        ),
        isolation=IsolationConfig(enforcement="local_with_announce"),
    )


class TestDelayInvariant:
    def test_delay_on_disabled_mesh_is_rejected(self):
        cfg = _arch_a(
            MeshConfig(
                enabled=False, transport="noop", endpoints={}, delay_sec=0.2
            )
        )
        with pytest.raises(ConfigError, match="delay_sec>0 requires mesh.enabled"):
            _validate_architecture_invariants(cfg)

    def test_delay_on_enabled_c_mesh_is_allowed(self):
        cfg = _arch_c(
            MeshConfig(
                enabled=True,
                transport="zeromq",
                endpoints={"uav_0": "tcp://127.0.0.1:5550"},
                delay_sec=0.2,
            )
        )
        _validate_architecture_invariants(cfg)  # must not raise
