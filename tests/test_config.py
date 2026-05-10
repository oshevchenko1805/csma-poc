"""
Tests for core.config.

Two categories:
  * Real config files in configs/ load and validate cleanly.
  * Synthetic broken configs raise ConfigError with clear messages.

If a real-config test fails after a YAML edit, the YAML is wrong, not
the test. That's the whole point of a strict loader.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from core.config import (
    ArchitectureConfig,
    ConfigError,
    ExperimentConfig,
    VALID_ARCHITECTURES,
    load_architecture_config,
    load_experiment_config,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = REPO_ROOT / "configs"


# ---------------------------------------------------------------------------
# Real config files
# ---------------------------------------------------------------------------


class TestRealConfigs:
    @pytest.mark.parametrize("name", ["architecture_a", "architecture_b", "architecture_c"])
    def test_architecture_loads(self, name: str):
        cfg = load_architecture_config(CONFIGS_DIR / f"{name}.yaml")
        assert isinstance(cfg, ArchitectureConfig)
        assert cfg.architecture in VALID_ARCHITECTURES

    def test_experiment_loads(self):
        cfg = load_experiment_config(CONFIGS_DIR / "experiment.yaml")
        assert isinstance(cfg, ExperimentConfig)
        assert len(cfg.telemetry.endpoints) == 3
        assert {e.uav_id for e in cfg.telemetry.endpoints} == {"uav_0", "uav_1", "uav_2"}
        assert {e.sysid for e in cfg.telemetry.endpoints} == {1, 2, 3}
        assert "comm_disruption" in cfg.attacks
        assert "command_injection" in cfg.attacks
        assert "gps_spoofing" in cfg.attacks

    def test_arch_a_has_centralized_monitor(self):
        cfg = load_architecture_config(CONFIGS_DIR / "architecture_a.yaml")
        assert cfg.architecture == "A"
        assert len(cfg.monitors) == 1
        assert cfg.monitors[0].location == "ground_station"
        assert set(cfg.monitors[0].watches) == {"uav_0", "uav_1", "uav_2"}
        assert not cfg.mesh.enabled
        assert not cfg.recovery.enabled

    def test_arch_b_has_per_uav_monitors_no_mesh_no_recovery(self):
        cfg = load_architecture_config(CONFIGS_DIR / "architecture_b.yaml")
        assert cfg.architecture == "B"
        assert len(cfg.monitors) == 3
        assert all(m.location.startswith("uav_") for m in cfg.monitors)
        assert all(m.watches == (m.location,) for m in cfg.monitors)
        assert all("cross_check" not in m.detectors for m in cfg.monitors)
        assert not cfg.mesh.enabled
        assert not cfg.recovery.enabled

    def test_arch_c_has_mesh_recovery_and_cross_check(self):
        cfg = load_architecture_config(CONFIGS_DIR / "architecture_c.yaml")
        assert cfg.architecture == "C"
        assert len(cfg.monitors) == 3
        assert all("cross_check" in m.detectors for m in cfg.monitors)
        assert cfg.mesh.enabled
        assert cfg.mesh.transport == "zeromq"
        assert set(cfg.mesh.endpoints.keys()) == {"uav_0", "uav_1", "uav_2"}
        assert cfg.recovery.enabled
        assert cfg.recovery.coordinator_election == "lowest_alive_sysid"


# ---------------------------------------------------------------------------
# Helpers for synthetic broken configs
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "x.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def _arch_a(tmp_path: Path, **overrides) -> Path:
    """Generate a valid arch-A YAML, then apply overrides as raw YAML."""
    base = textwrap.dedent("""
    architecture: A
    monitors:
      - location: ground_station
        watches: [uav_0, uav_1, uav_2]
        detectors: [heartbeat, command, gps]
    mesh:
      enabled: false
      transport: noop
    recovery:
      enabled: false
      coordinator_election: none
    isolation:
      enforcement: ground_station_command
    """)
    for k, v in overrides.items():
        base = base + f"\n{k}: {v}\n"
    p = tmp_path / "x.yaml"
    p.write_text(base)
    return p


# ---------------------------------------------------------------------------
# Architecture: schema errors
# ---------------------------------------------------------------------------


class TestArchitectureSchema:
    def test_missing_top_key(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: A
            monitors: []
        """)
        with pytest.raises(ConfigError, match="missing keys"):
            load_architecture_config(p)

    def test_unknown_top_key(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: A
            monitors:
              - location: ground_station
                watches: [uav_0]
                detectors: [heartbeat]
            mesh: {enabled: false, transport: noop}
            recovery: {enabled: false, coordinator_election: none}
            isolation: {enforcement: ground_station_command}
            extra_field: 42
        """)
        with pytest.raises(ConfigError, match="unexpected keys"):
            load_architecture_config(p)

    def test_unknown_architecture_value(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: X
            monitors:
              - location: ground_station
                watches: [uav_0]
                detectors: [heartbeat]
            mesh: {enabled: false, transport: noop}
            recovery: {enabled: false, coordinator_election: none}
            isolation: {enforcement: ground_station_command}
        """)
        with pytest.raises(ConfigError, match="not in"):
            load_architecture_config(p)

    def test_unknown_detector(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: A
            monitors:
              - location: ground_station
                watches: [uav_0]
                detectors: [made_up_detector]
            mesh: {enabled: false, transport: noop}
            recovery: {enabled: false, coordinator_election: none}
            isolation: {enforcement: ground_station_command}
        """)
        with pytest.raises(ConfigError, match="not in"):
            load_architecture_config(p)

    def test_empty_monitors(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: A
            monitors: []
            mesh: {enabled: false, transport: noop}
            recovery: {enabled: false, coordinator_election: none}
            isolation: {enforcement: ground_station_command}
        """)
        with pytest.raises(ConfigError, match="non-empty"):
            load_architecture_config(p)

    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(ConfigError, match="not found"):
            load_architecture_config(tmp_path / "nonexistent.yaml")


# ---------------------------------------------------------------------------
# Architecture: cross-field invariants (this is where mistakes hide)
# ---------------------------------------------------------------------------


class TestArchitectureInvariants:
    def test_recovery_in_arch_a_rejected(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: A
            monitors:
              - location: ground_station
                watches: [uav_0]
                detectors: [heartbeat]
            mesh: {enabled: false, transport: noop}
            recovery: {enabled: true, coordinator_election: lowest_alive_sysid}
            isolation: {enforcement: ground_station_command}
        """)
        with pytest.raises(ConfigError, match="recovery.enabled=true is only valid"):
            load_architecture_config(p)

    def test_mesh_in_arch_b_rejected(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: B
            monitors:
              - location: uav_0
                watches: [uav_0]
                detectors: [heartbeat]
            mesh: {enabled: true, transport: zeromq, endpoints: {uav_0: tcp://x:1}}
            recovery: {enabled: false, coordinator_election: none}
            isolation: {enforcement: local_self}
        """)
        with pytest.raises(ConfigError, match="mesh.enabled=true is only valid"):
            load_architecture_config(p)

    def test_arch_c_without_mesh_rejected(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: C
            monitors:
              - location: uav_0
                watches: [uav_0]
                detectors: [heartbeat]
            mesh: {enabled: false, transport: noop}
            recovery: {enabled: true, coordinator_election: lowest_alive_sysid}
            isolation: {enforcement: local_with_announce}
        """)
        with pytest.raises(ConfigError, match="architecture C requires mesh.enabled=true"):
            load_architecture_config(p)

    def test_arch_c_without_recovery_rejected(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: C
            monitors:
              - location: uav_0
                watches: [uav_0]
                detectors: [heartbeat]
            mesh: {enabled: true, transport: zeromq, endpoints: {uav_0: tcp://x:1}}
            recovery: {enabled: false, coordinator_election: none}
            isolation: {enforcement: local_with_announce}
        """)
        with pytest.raises(ConfigError, match="architecture C requires recovery.enabled=true"):
            load_architecture_config(p)

    def test_arch_b_with_cross_check_rejected(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: B
            monitors:
              - location: uav_0
                watches: [uav_0]
                detectors: [heartbeat, cross_check]
            mesh: {enabled: false, transport: noop}
            recovery: {enabled: false, coordinator_election: none}
            isolation: {enforcement: local_self}
        """)
        with pytest.raises(ConfigError, match="cross_check detector is C-only"):
            load_architecture_config(p)

    def test_arch_b_monitor_watching_other_uav_rejected(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: B
            monitors:
              - location: uav_0
                watches: [uav_1]
                detectors: [heartbeat]
            mesh: {enabled: false, transport: noop}
            recovery: {enabled: false, coordinator_election: none}
            isolation: {enforcement: local_self}
        """)
        with pytest.raises(ConfigError, match="must watch only itself"):
            load_architecture_config(p)

    def test_arch_a_with_local_isolation_rejected(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: A
            monitors:
              - location: ground_station
                watches: [uav_0]
                detectors: [heartbeat]
            mesh: {enabled: false, transport: noop}
            recovery: {enabled: false, coordinator_election: none}
            isolation: {enforcement: local_self}
        """)
        with pytest.raises(ConfigError, match="isolation.enforcement must be ground_station_command"):
            load_architecture_config(p)

    def test_arch_c_missing_mesh_endpoint_rejected(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: C
            monitors:
              - location: uav_0
                watches: [uav_0]
                detectors: [heartbeat, cross_check]
              - location: uav_1
                watches: [uav_1]
                detectors: [heartbeat, cross_check]
            mesh:
              enabled: true
              transport: zeromq
              endpoints:
                uav_0: tcp://127.0.0.1:5550
                # uav_1 missing!
            recovery: {enabled: true, coordinator_election: lowest_alive_sysid}
            isolation: {enforcement: local_with_announce}
        """)
        with pytest.raises(ConfigError, match="missing mesh endpoints"):
            load_architecture_config(p)

    def test_mesh_disabled_with_zeromq_transport_rejected(self, tmp_path: Path):
        p = _write(tmp_path, """
            architecture: A
            monitors:
              - location: ground_station
                watches: [uav_0]
                detectors: [heartbeat]
            mesh: {enabled: false, transport: zeromq}
            recovery: {enabled: false, coordinator_election: none}
            isolation: {enforcement: ground_station_command}
        """)
        with pytest.raises(ConfigError, match="requires transport=noop"):
            load_architecture_config(p)


# ---------------------------------------------------------------------------
# Experiment config errors
# ---------------------------------------------------------------------------


class TestExperimentSchema:
    def test_unknown_attack(self, tmp_path: Path):
        p = _write(tmp_path, """
            mission:
              type: coordinated_waypoint
              duration_sec: 300
              waypoints:
                - {north_m: 0, east_m: 0, alt_m: 20}
                - {north_m: 1, east_m: 0, alt_m: 20}
            telemetry:
              endpoints:
                - {uav_id: uav_0, endpoint: udpin:127.0.0.1:14540, sysid: 1}
            attacks:
              - made_up_attack
            runs:
              baseline_per_arch: 1
              attacks_per_arch_per_attack: 1
              observation_after_attack_sec: 5
        """)
        with pytest.raises(ConfigError, match="not in"):
            load_experiment_config(p)

    def test_duplicate_uav_id_in_telemetry(self, tmp_path: Path):
        p = _write(tmp_path, """
            mission:
              type: coordinated_waypoint
              duration_sec: 300
              waypoints:
                - {north_m: 0, east_m: 0, alt_m: 20}
                - {north_m: 1, east_m: 0, alt_m: 20}
            telemetry:
              endpoints:
                - {uav_id: uav_0, endpoint: udpin:127.0.0.1:14540, sysid: 1}
                - {uav_id: uav_0, endpoint: udpin:127.0.0.1:14541, sysid: 2}
            attacks:
              - comm_disruption
            runs:
              baseline_per_arch: 1
              attacks_per_arch_per_attack: 1
              observation_after_attack_sec: 5
        """)
        with pytest.raises(ConfigError, match="duplicate uav_id"):
            load_experiment_config(p)

    def test_duplicate_attacks(self, tmp_path: Path):
        p = _write(tmp_path, """
            mission:
              type: coordinated_waypoint
              duration_sec: 300
              waypoints:
                - {north_m: 0, east_m: 0, alt_m: 20}
                - {north_m: 1, east_m: 0, alt_m: 20}
            telemetry:
              endpoints:
                - {uav_id: uav_0, endpoint: udpin:127.0.0.1:14540, sysid: 1}
            attacks:
              - comm_disruption
              - comm_disruption
            runs:
              baseline_per_arch: 1
              attacks_per_arch_per_attack: 1
              observation_after_attack_sec: 5
        """)
        with pytest.raises(ConfigError, match="duplicates not allowed"):
            load_experiment_config(p)

    def test_negative_run_count(self, tmp_path: Path):
        p = _write(tmp_path, """
            mission:
              type: coordinated_waypoint
              duration_sec: 300
              waypoints:
                - {north_m: 0, east_m: 0, alt_m: 20}
                - {north_m: 1, east_m: 0, alt_m: 20}
            telemetry:
              endpoints:
                - {uav_id: uav_0, endpoint: udpin:127.0.0.1:14540, sysid: 1}
            attacks:
              - comm_disruption
            runs:
              baseline_per_arch: -1
              attacks_per_arch_per_attack: 1
              observation_after_attack_sec: 5
        """)
        with pytest.raises(ConfigError, match="non-negative"):
            load_experiment_config(p)

    def test_zero_observation_window(self, tmp_path: Path):
        p = _write(tmp_path, """
            mission:
              type: coordinated_waypoint
              duration_sec: 300
              waypoints:
                - {north_m: 0, east_m: 0, alt_m: 20}
                - {north_m: 1, east_m: 0, alt_m: 20}
            telemetry:
              endpoints:
                - {uav_id: uav_0, endpoint: udpin:127.0.0.1:14540, sysid: 1}
            attacks:
              - comm_disruption
            runs:
              baseline_per_arch: 1
              attacks_per_arch_per_attack: 1
              observation_after_attack_sec: 0
        """)
        with pytest.raises(ConfigError, match="observation_after_attack_sec"):
            load_experiment_config(p)

    def test_single_waypoint_rejected(self, tmp_path: Path):
        p = _write(tmp_path, """
            mission:
              type: coordinated_waypoint
              duration_sec: 300
              waypoints:
                - {north_m: 0, east_m: 0, alt_m: 20}
            telemetry:
              endpoints:
                - {uav_id: uav_0, endpoint: udpin:127.0.0.1:14540, sysid: 1}
            attacks:
              - comm_disruption
            runs:
              baseline_per_arch: 1
              attacks_per_arch_per_attack: 1
              observation_after_attack_sec: 5
        """)
        with pytest.raises(ConfigError, match="at least two"):
            load_experiment_config(p)

