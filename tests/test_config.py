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
    MissionConfig,
    VALID_ARCHITECTURES,
    Waypoint,
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

    def test_experiment_mission_is_multi_lap(self):
        """OPEN-1: the route must outlast the observation window.

        A single lap finished at t~57 s while attacks fire at t=90 s, so
        every attack hit a hovering UAV. This asserts the shipped config
        still flies multiple laps — if someone trims it back to one, the
        campaign silently reverts to measuring hover, and this fails.
        """
        cfg = load_experiment_config(CONFIGS_DIR / "experiment.yaml")
        m = cfg.mission
        assert m.laps >= 4, "route must outlast the 150 s observation window"
        assert len(m.lap_waypoints) == 4, "lap is a square: 4 corners"
        assert len(m.waypoints) == len(m.lap_waypoints) * m.laps
        # No lap seam duplicates survived expansion.
        assert all(
            m.waypoints[i] != m.waypoints[i - 1]
            for i in range(1, len(m.waypoints))
        )

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


def _experiment(tmp_path: Path, mission_body: str) -> Path:
    """Valid experiment YAML with a caller-supplied `mission:` block.

    `mission_body` is the indented content of the mission mapping.
    """
    body = textwrap.dedent("""
        mission:
        {mission}
        telemetry:
          endpoints:
            - {{uav_id: uav_0, endpoint: udpin:127.0.0.1:14540, sysid: 1}}
        attacks:
          - comm_disruption
        runs:
          baseline_per_arch: 1
          attacks_per_arch_per_attack: 1
          observation_after_attack_sec: 5
    """).format(mission=textwrap.indent(textwrap.dedent(mission_body).strip("\n"), "  "))
    p = tmp_path / "x.yaml"
    p.write_text(body)
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


# ---------------------------------------------------------------------------
# mission.laps — route length as an experiment parameter (OPEN-1 / OPEN-2)
# ---------------------------------------------------------------------------


class TestMissionLaps:
    """`laps` repeats the authored lap pattern into the uploaded plan.

    The lap count controls how long the UAV stays in motion, which is
    what makes an attack land on a flying vehicle rather than a hovering
    one. Getting it wrong silently invalidates a whole campaign, so it
    is a validated parameter rather than a hand-copied waypoint list.
    """

    @staticmethod
    def _mission(laps: str | None = None) -> str:
        """A valid square lap, optionally with a raw `laps:` value."""
        body = """
        type: coordinated_waypoint
        duration_sec: 300
        waypoints:
          - {north_m: 10, east_m: 0, alt_m: 20}
          - {north_m: 10, east_m: 10, alt_m: 20}
          - {north_m: 0, east_m: 10, alt_m: 20}
          - {north_m: 0, east_m: 0, alt_m: 20}
        """
        if laps is not None:
            body += f"laps: {laps}\n        "
        return body

    def test_laps_defaults_to_one(self, tmp_path: Path):
        """Configs written before `laps` existed keep their exact plan."""
        p = _experiment(tmp_path, self._mission())
        cfg = load_experiment_config(p)
        assert cfg.mission.laps == 1
        assert len(cfg.mission.waypoints) == 4

    def test_laps_expands_plan(self, tmp_path: Path):
        p = _experiment(tmp_path, self._mission("3"))
        cfg = load_experiment_config(p)
        assert cfg.mission.laps == 3
        assert len(cfg.mission.waypoints) == 12
        # The plan is the pattern, three times over.
        assert cfg.mission.waypoints[0:4] == cfg.mission.waypoints[4:8]
        assert cfg.mission.waypoints[4:8] == cfg.mission.waypoints[8:12]

    def test_lap_waypoints_recovers_pattern(self, tmp_path: Path):
        p = _experiment(tmp_path, self._mission("5"))
        cfg = load_experiment_config(p)
        assert cfg.mission.lap_waypoints == (
            Waypoint(10.0, 0.0, 20.0),
            Waypoint(10.0, 10.0, 20.0),
            Waypoint(0.0, 10.0, 20.0),
            Waypoint(0.0, 0.0, 20.0),
        )

    def test_laps_zero_rejected(self, tmp_path: Path):
        p = _experiment(tmp_path, self._mission("0"))
        with pytest.raises(ConfigError, match=r"laps: must be >= 1"):
            load_experiment_config(p)

    def test_laps_negative_rejected(self, tmp_path: Path):
        p = _experiment(tmp_path, self._mission("-2"))
        with pytest.raises(ConfigError, match=r"laps: must be >= 1"):
            load_experiment_config(p)

    def test_laps_float_rejected(self, tmp_path: Path):
        """2.5 laps would silently truncate to 2 under int()."""
        p = _experiment(tmp_path, self._mission("2.5"))
        with pytest.raises(ConfigError, match="must be an integer"):
            load_experiment_config(p)

    def test_laps_bool_rejected(self, tmp_path: Path):
        """`laps: true` is a typo; bool is an int subclass in Python."""
        p = _experiment(tmp_path, self._mission("true"))
        with pytest.raises(ConfigError, match="must be an integer"):
            load_experiment_config(p)

    def test_lap_seam_duplicate_rejected(self, tmp_path: Path):
        """A self-closing lap makes every seam a duplicate waypoint."""
        closing_lap = """
            type: coordinated_waypoint
            duration_sec: 300
            waypoints:
              - {north_m: 0, east_m: 0, alt_m: 20}
              - {north_m: 10, east_m: 0, alt_m: 20}
              - {north_m: 0, east_m: 0, alt_m: 20}
            laps: 2
        """
        p = _experiment(tmp_path, closing_lap)
        with pytest.raises(ConfigError, match="are identical"):
            load_experiment_config(p)

    def test_adjacent_duplicate_within_lap_rejected(self, tmp_path: Path):
        """Caught even at laps=1 — a repeated point is always a no-op."""
        dup_lap = """
            type: coordinated_waypoint
            duration_sec: 300
            waypoints:
              - {north_m: 0, east_m: 0, alt_m: 20}
              - {north_m: 10, east_m: 0, alt_m: 20}
              - {north_m: 10, east_m: 0, alt_m: 20}
        """
        p = _experiment(tmp_path, dup_lap)
        with pytest.raises(ConfigError, match="are identical"):
            load_experiment_config(p)

    def test_repeated_point_within_lap_is_allowed_when_not_adjacent(
        self, tmp_path: Path
    ):
        """Revisiting a point later in the lap is legitimate (a figure-8)."""
        figure_eight = """
            type: coordinated_waypoint
            duration_sec: 300
            waypoints:
              - {north_m: 0, east_m: 0, alt_m: 20}
              - {north_m: 10, east_m: 0, alt_m: 20}
              - {north_m: 0, east_m: 0, alt_m: 20}
              - {north_m: 0, east_m: 10, alt_m: 20}
        """
        p = _experiment(tmp_path, figure_eight)
        cfg = load_experiment_config(p)
        assert len(cfg.mission.waypoints) == 4

    def test_direct_construction_defaults_to_one_lap(self):
        """Hand-built MissionConfig (as in other tests) still works."""
        m = MissionConfig(
            type="coordinated_waypoint",
            duration_sec=300.0,
            waypoints=(Waypoint(0, 0, 20), Waypoint(1, 0, 20)),
        )
        assert m.laps == 1
        assert m.lap_waypoints == m.waypoints

    def test_direct_construction_indivisible_plan_rejected(self):
        """laps must divide the plan, or lap_waypoints would be garbage."""
        with pytest.raises(ConfigError, match="not divisible by laps"):
            MissionConfig(
                type="coordinated_waypoint",
                duration_sec=300.0,
                waypoints=(
                    Waypoint(0, 0, 20),
                    Waypoint(1, 0, 20),
                    Waypoint(2, 0, 20),
                ),
                laps=2,
            )

    def test_direct_construction_zero_laps_rejected(self):
        with pytest.raises(ConfigError, match=r"laps: must be >= 1"):
            MissionConfig(
                type="coordinated_waypoint",
                duration_sec=300.0,
                waypoints=(Waypoint(0, 0, 20), Waypoint(1, 0, 20)),
                laps=0,
            )
