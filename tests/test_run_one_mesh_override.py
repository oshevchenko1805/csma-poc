"""Unit tests for scripts/run_one.py::apply_mesh_override (loss sweep)."""
import pathlib
import sys

import pytest

# Import run_one.py as a top-level module, the same way the script runs,
# without requiring scripts/ to be a package.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import run_one  # noqa: E402

from core.config import (  # noqa: E402
    ArchitectureConfig,
    ConfigError,
    IsolationConfig,
    MeshConfig,
    MonitorSpec,
    RecoveryConfig,
)


def _arch_c(loss_prob=0.0, loss_seed=None):
    return ArchitectureConfig(
        architecture="C",
        monitors=(MonitorSpec("uav_0", ("uav_0",), ("gps", "cross_check")),),
        mesh=MeshConfig(
            enabled=True,
            transport="zeromq",
            endpoints={"uav_0": "tcp://127.0.0.1:5550"},
            loss_prob=loss_prob,
            loss_seed=loss_seed,
        ),
        recovery=RecoveryConfig(enabled=True, coordinator_election="lowest_alive_sysid"),
        isolation=IsolationConfig(enforcement="local_with_announce"),
    )


def _arch_a():
    return ArchitectureConfig(
        architecture="A",
        monitors=(MonitorSpec("ground_station", ("uav_0",), ("gps",)),),
        mesh=MeshConfig(enabled=False, transport="noop", endpoints={}),
        recovery=RecoveryConfig(enabled=False, coordinator_election="none"),
        isolation=IsolationConfig(enforcement="ground_station_command"),
    )


def test_no_override_returns_same_object():
    c = _arch_c()
    assert run_one.apply_mesh_override(c, loss_prob=None, loss_seed=None) is c


def test_override_sets_loss_on_c():
    out = run_one.apply_mesh_override(_arch_c(), loss_prob=0.3, loss_seed=7)
    assert out.mesh.loss_prob == 0.3
    assert out.mesh.loss_seed == 7
    assert out.mesh.enabled is True
    assert out.architecture == "C"


def test_loss_on_disabled_mesh_raises():
    with pytest.raises(ConfigError):
        run_one.apply_mesh_override(_arch_a(), loss_prob=0.3, loss_seed=None)


def test_zero_loss_on_disabled_mesh_is_allowed():
    a = _arch_a()
    out = run_one.apply_mesh_override(a, loss_prob=0.0, loss_seed=None)
    assert out.mesh.loss_prob == 0.0


def test_out_of_range_loss_raises():
    with pytest.raises(ConfigError):
        run_one.apply_mesh_override(_arch_c(), loss_prob=1.5, loss_seed=None)


def test_seed_only_override_keeps_configured_loss():
    c = _arch_c(loss_prob=0.2)
    out = run_one.apply_mesh_override(c, loss_prob=None, loss_seed=99)
    assert out.mesh.loss_seed == 99
    assert out.mesh.loss_prob == 0.2
