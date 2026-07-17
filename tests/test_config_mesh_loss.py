"""Tests for mesh loss config knobs (instrumentation item 4a, step 2).

Covers MeshConfig.loss_prob / loss_seed: defaults, validation, parsing, and
the cross-field invariant that loss only applies to an enabled (C) mesh.
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


# ----------------------------------------------------------------------------
# MeshConfig field defaults + validation
# ----------------------------------------------------------------------------


class TestMeshConfigFields:
    def test_defaults_are_zero_loss_no_seed(self):
        m = MeshConfig(enabled=True, transport="zeromq", endpoints={})
        assert m.loss_prob == 0.0
        assert m.loss_seed is None

    def test_rejects_out_of_range_loss(self):
        for bad in (-0.1, 1.5):
            with pytest.raises(ConfigError, match="loss_prob"):
                MeshConfig(
                    enabled=True, transport="zeromq", endpoints={}, loss_prob=bad
                )

    def test_accepts_boundary_loss(self):
        for ok in (0.0, 1.0):
            MeshConfig(
                enabled=True, transport="zeromq", endpoints={}, loss_prob=ok
            )

    def test_rejects_non_int_seed(self):
        for bad in (3.5, "abc", True):
            with pytest.raises(ConfigError, match="loss_seed"):
                MeshConfig(
                    enabled=True,
                    transport="zeromq",
                    endpoints={},
                    loss_seed=bad,
                )

    def test_accepts_int_or_none_seed(self):
        MeshConfig(enabled=True, transport="zeromq", endpoints={}, loss_seed=42)
        MeshConfig(enabled=True, transport="zeromq", endpoints={}, loss_seed=None)


# ----------------------------------------------------------------------------
# _parse_mesh
# ----------------------------------------------------------------------------


class TestParseMesh:
    def test_reads_loss_fields(self):
        m = _parse_mesh(
            {
                "enabled": True,
                "transport": "zeromq",
                "endpoints": {"uav_0": "tcp://127.0.0.1:5550"},
                "loss_prob": 0.25,
                "loss_seed": 7,
            }
        )
        assert m.loss_prob == 0.25
        assert m.loss_seed == 7

    def test_defaults_when_absent(self):
        m = _parse_mesh({"enabled": False, "transport": "noop"})
        assert m.loss_prob == 0.0
        assert m.loss_seed is None

    def test_still_rejects_unknown_key(self):
        with pytest.raises(ConfigError, match="unexpected keys"):
            _parse_mesh({"enabled": False, "transport": "noop", "bogus": 1})

    def test_out_of_range_loss_raises_through_parse(self):
        with pytest.raises(ConfigError, match="loss_prob"):
            _parse_mesh(
                {"enabled": True, "transport": "zeromq", "loss_prob": 2.0}
            )


# ----------------------------------------------------------------------------
# Cross-field invariant
# ----------------------------------------------------------------------------


def _arch_a(mesh: MeshConfig) -> ArchitectureConfig:
    """Minimal valid Architecture A, parameterised on its mesh."""
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
    """Minimal valid Architecture C, parameterised on its mesh."""
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


class TestLossInvariant:
    def test_loss_on_disabled_mesh_is_rejected(self):
        cfg = _arch_a(
            MeshConfig(enabled=False, transport="noop", endpoints={}, loss_prob=0.5)
        )
        with pytest.raises(ConfigError, match="loss_prob>0 requires mesh.enabled"):
            _validate_architecture_invariants(cfg)

    def test_zero_loss_on_disabled_mesh_is_allowed(self):
        cfg = _arch_a(
            MeshConfig(enabled=False, transport="noop", endpoints={})
        )
        _validate_architecture_invariants(cfg)  # must not raise

    def test_loss_on_enabled_c_mesh_is_allowed(self):
        cfg = _arch_c(
            MeshConfig(
                enabled=True,
                transport="zeromq",
                endpoints={"uav_0": "tcp://127.0.0.1:5550"},
                loss_prob=0.3,
                loss_seed=7,
            )
        )
        _validate_architecture_invariants(cfg)  # must not raise
