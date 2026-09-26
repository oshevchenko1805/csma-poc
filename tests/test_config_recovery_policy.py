"""Tests for recovery.policy in the architecture config (review stage 3)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from core.config import ConfigError, load_architecture_config

REPO = Path(__file__).resolve().parent.parent

_C = """
architecture: C
monitors:
  - location: uav_0
    watches: [uav_0]
    detectors: [heartbeat, gps, cross_check]
mesh: {{enabled: true, transport: zeromq, endpoints: {{uav_0: tcp://x:1}}}}
recovery: {{enabled: true, coordinator_election: lowest_alive_sysid{extra}}}
isolation: {{enforcement: local_with_announce}}
"""

_A = """
architecture: A
monitors:
  - location: ground_station
    watches: [uav_0]
    detectors: [heartbeat, gps]
mesh: {{enabled: false, transport: noop}}
recovery: {{enabled: false, coordinator_election: none{extra}}}
isolation: {{enforcement: ground_station_command}}
"""


def _write(tmp_path: Path, tpl: str, extra: str = "") -> Path:
    p = tmp_path / "arch.yaml"
    p.write_text(textwrap.dedent(tpl.format(extra=extra)))
    return p


def test_absent_key_defaults_to_proportionate(tmp_path):
    cfg = load_architecture_config(_write(tmp_path, _C))
    assert cfg.recovery.policy == "proportionate"


def test_shipped_arch_c_yaml_is_proportionate():
    cfg = load_architecture_config(REPO / "configs" / "architecture_c.yaml")
    assert cfg.recovery.policy == "proportionate"


@pytest.mark.parametrize("policy", ["proportionate", "trust_aware", "detect_only"])
def test_valid_policies_accepted_in_c(tmp_path, policy):
    cfg = load_architecture_config(_write(tmp_path, _C, f", policy: {policy}"))
    assert cfg.recovery.policy == policy


def test_unknown_policy_rejected(tmp_path):
    with pytest.raises(ConfigError, match="recovery.policy"):
        load_architecture_config(_write(tmp_path, _C, ", policy: aggressive"))


@pytest.mark.parametrize("policy", ["trust_aware", "detect_only"])
def test_non_default_policy_needs_recovery_enabled(tmp_path, policy):
    with pytest.raises(ConfigError, match="requires recovery.enabled=true"):
        load_architecture_config(_write(tmp_path, _A, f", policy: {policy}"))


def test_arch_a_unchanged(tmp_path):
    cfg = load_architecture_config(_write(tmp_path, _A))
    assert cfg.recovery.policy == "proportionate"
    assert not cfg.recovery.enabled
