"""
Typed configuration loader for the CSMA PoC.

Two YAML files drive every run:
  * configs/architecture_*.yaml — describes one of the three architectures
    (A: centralized, B: segmented without self-healing, C: CSMA with
    self-healing). The architecture difference lives in this file, not
    in domain code.
  * configs/experiment.yaml — describes the mission, telemetry endpoints,
    attack matrix, and run counts. Shared across architectures.

Loaders are strict:
  * Unknown keys raise (catches typos in YAML before they silently
    change behaviour).
  * Enumerated string fields are validated against whitelists exposed as
    module-level constants so domain code can reuse them.
  * Cross-field invariants are checked (e.g. recovery.enabled implies
    architecture C, mesh.enabled implies a peer endpoint per UAV in C).

Failing fast on malformed config is mandatory — silently misconfigured
runs produce data that cannot be defended in a dissertation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


# ---------------------------------------------------------------------------
# Whitelists (also imported by domain code)
# ---------------------------------------------------------------------------

VALID_ARCHITECTURES: frozenset[str] = frozenset({"A", "B", "C"})
VALID_DETECTORS: frozenset[str] = frozenset(
    {"heartbeat", "command", "gps", "cross_check"}
)
VALID_ATTACKS: frozenset[str] = frozenset(
    {"comm_disruption", "command_injection", "gps_spoofing"}
)
VALID_ISOLATION_ENFORCEMENTS: frozenset[str] = frozenset(
    {"ground_station_command", "local_self", "local_with_announce"}
)
VALID_MESH_TRANSPORTS: frozenset[str] = frozenset({"zeromq", "noop"})
VALID_COORDINATOR_ELECTIONS: frozenset[str] = frozenset(
    {"lowest_alive_sysid", "none"}
)
VALID_MISSION_TYPES: frozenset[str] = frozenset({"coordinated_waypoint"})


class ConfigError(ValueError):
    """Raised for any malformed or invariant-violating configuration."""


# ---------------------------------------------------------------------------
# Architecture config dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MonitorSpec:
    location: str           # 'ground_station' | 'uav_0' | 'uav_1' | 'uav_2'
    watches: tuple[str, ...]   # which uav_ids this monitor observes
    detectors: tuple[str, ...]


@dataclass(frozen=True)
class MeshConfig:
    enabled: bool
    transport: str
    endpoints: dict[str, str]   # uav_id -> 'tcp://...'
    # Channel degradation (instrumentation item 4). Defaults keep every
    # existing config byte-identical: 0.0 loss, no seed. Only meaningful
    # when the mesh is enabled (architecture C); the invariant check
    # rejects loss_prob>0 on a disabled (noop) mesh.
    loss_prob: float = 0.0
    loss_seed: Optional[int] = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.loss_prob <= 1.0:
            raise ConfigError(
                f"mesh.loss_prob: must be in [0.0, 1.0], got {self.loss_prob}"
            )
        # bool is an int subclass; `loss_seed: true` is a typo, not a seed.
        if self.loss_seed is not None and (
            isinstance(self.loss_seed, bool)
            or not isinstance(self.loss_seed, int)
        ):
            raise ConfigError(
                f"mesh.loss_seed: must be an integer or null, got "
                f"{self.loss_seed!r}"
            )


@dataclass(frozen=True)
class RecoveryConfig:
    enabled: bool
    coordinator_election: str


@dataclass(frozen=True)
class IsolationConfig:
    enforcement: str


@dataclass(frozen=True)
class ArchitectureConfig:
    architecture: str
    monitors: tuple[MonitorSpec, ...]
    mesh: MeshConfig
    recovery: RecoveryConfig
    isolation: IsolationConfig


# ---------------------------------------------------------------------------
# Experiment config dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Waypoint:
    north_m: float
    east_m: float
    alt_m: float


@dataclass(frozen=True)
class MissionConfig:
    """A mission plan.

    `waypoints` is the FULLY EXPANDED plan — the exact sequence uploaded
    to the vehicle. `laps` is how many times the authored lap pattern was
    repeated to produce it (1 = the pattern is the plan). The loader does
    the expansion; every consumer downstream (runners.mission_mavsdk,
    runners.experiment) sees only `waypoints` and needs no knowledge of
    laps.

    Why laps exists at all
    ----------------------
    Flight duration is an experiment parameter, not decoration. A live
    trajectory showed the single-lap route finishing at t~57 s while
    attacks fire at t=90 s — every attack hit a HOVERING UAV and mission
    resilience (thesis §3.4.5) was unmeasurable (RESULTS_NOTES OPEN-1).
    The fix is more laps. Expressing that as `laps: N` rather than a
    hand-copied waypoint list keeps it (a) a single number to change for
    the OPEN-2 parametric sweeps, and (b) impossible to mis-transcribe.

    `lap_waypoints` recovers the authored pattern by slicing rather than
    storing it twice — two copies of the same fact can disagree; a
    derived one cannot.
    """

    type: str
    duration_sec: float
    waypoints: tuple[Waypoint, ...]   # expanded plan (lap pattern x laps)
    laps: int = 1

    def __post_init__(self) -> None:
        # Total invariants: hold for loader-built AND hand-built configs
        # (tests construct MissionConfig directly).
        if self.laps < 1:
            raise ConfigError(f"mission.laps: must be >= 1, got {self.laps}")
        if self.waypoints and len(self.waypoints) % self.laps != 0:
            raise ConfigError(
                f"mission: expanded waypoints ({len(self.waypoints)}) is not "
                f"divisible by laps ({self.laps}) — the plan is not a whole "
                f"number of laps"
            )

    @property
    def lap_waypoints(self) -> tuple[Waypoint, ...]:
        """The authored lap pattern (one lap), derived from the plan."""
        if not self.waypoints:
            return ()
        return self.waypoints[: len(self.waypoints) // self.laps]


@dataclass(frozen=True)
class TelemetryEndpointSpec:
    uav_id: str
    endpoint: str   # 'udpin:127.0.0.1:14540'
    sysid: int


@dataclass(frozen=True)
class TelemetryConfig:
    endpoints: tuple[TelemetryEndpointSpec, ...]


@dataclass(frozen=True)
class RunsConfig:
    baseline_per_arch: int
    attacks_per_arch_per_attack: int
    observation_after_attack_sec: float


@dataclass(frozen=True)
class ExperimentConfig:
    mission: MissionConfig
    telemetry: TelemetryConfig
    attacks: tuple[str, ...]
    runs: RunsConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_keys(d: dict[str, Any], required: set[str], context: str) -> None:
    missing = required - set(d.keys())
    if missing:
        raise ConfigError(f"{context}: missing keys {sorted(missing)}")


def _no_extra_keys(d: dict[str, Any], allowed: set[str], context: str) -> None:
    extra = set(d.keys()) - allowed
    if extra:
        raise ConfigError(f"{context}: unexpected keys {sorted(extra)}")


def _enum(value: str, allowed: frozenset[str], context: str) -> str:
    if value not in allowed:
        raise ConfigError(
            f"{context}: {value!r} not in {sorted(allowed)}"
        )
    return value


# ---------------------------------------------------------------------------
# Architecture loader
# ---------------------------------------------------------------------------


def _parse_monitor(raw: dict[str, Any], idx: int) -> MonitorSpec:
    ctx = f"monitors[{idx}]"
    _require_keys(raw, {"location", "watches", "detectors"}, ctx)
    _no_extra_keys(raw, {"location", "watches", "detectors"}, ctx)

    location = str(raw["location"])
    watches = tuple(str(x) for x in raw["watches"])
    if not watches:
        raise ConfigError(f"{ctx}.watches: must not be empty")

    detectors = tuple(str(x) for x in raw["detectors"])
    for d in detectors:
        _enum(d, VALID_DETECTORS, f"{ctx}.detectors")

    return MonitorSpec(location=location, watches=watches, detectors=detectors)


def _parse_mesh(raw: dict[str, Any]) -> MeshConfig:
    ctx = "mesh"
    _require_keys(raw, {"enabled", "transport"}, ctx)
    _no_extra_keys(
        raw,
        {"enabled", "transport", "endpoints", "loss_prob", "loss_seed"},
        ctx,
    )

    enabled = bool(raw["enabled"])
    transport = _enum(str(raw["transport"]), VALID_MESH_TRANSPORTS, f"{ctx}.transport")

    endpoints_raw = raw.get("endpoints") or {}
    if not isinstance(endpoints_raw, dict):
        raise ConfigError(f"{ctx}.endpoints: must be a mapping uav_id -> tcp url")
    endpoints = {str(k): str(v) for k, v in endpoints_raw.items()}

    loss_prob = float(raw.get("loss_prob", 0.0))
    # Pass loss_seed through untouched; MeshConfig.__post_init__ type-
    # checks it (an int, or null). Coercing here would turn a float or
    # bool into a silent seed.
    loss_seed = raw.get("loss_seed", None)

    return MeshConfig(
        enabled=enabled,
        transport=transport,
        endpoints=endpoints,
        loss_prob=loss_prob,
        loss_seed=loss_seed,
    )


def _parse_recovery(raw: dict[str, Any]) -> RecoveryConfig:
    ctx = "recovery"
    _require_keys(raw, {"enabled", "coordinator_election"}, ctx)
    _no_extra_keys(raw, {"enabled", "coordinator_election"}, ctx)
    return RecoveryConfig(
        enabled=bool(raw["enabled"]),
        coordinator_election=_enum(
            str(raw["coordinator_election"]),
            VALID_COORDINATOR_ELECTIONS,
            f"{ctx}.coordinator_election",
        ),
    )


def _parse_isolation(raw: dict[str, Any]) -> IsolationConfig:
    ctx = "isolation"
    _require_keys(raw, {"enforcement"}, ctx)
    _no_extra_keys(raw, {"enforcement"}, ctx)
    return IsolationConfig(
        enforcement=_enum(
            str(raw["enforcement"]),
            VALID_ISOLATION_ENFORCEMENTS,
            f"{ctx}.enforcement",
        )
    )


def _validate_architecture_invariants(cfg: ArchitectureConfig) -> None:
    """Cross-field rules. Any violation is a ConfigError, not a warning."""

    if cfg.recovery.enabled and cfg.architecture != "C":
        raise ConfigError(
            f"recovery.enabled=true is only valid for architecture C, got {cfg.architecture!r}"
        )

    if cfg.mesh.enabled and cfg.architecture != "C":
        raise ConfigError(
            f"mesh.enabled=true is only valid for architecture C, got {cfg.architecture!r}"
        )

    if cfg.architecture == "C" and not cfg.mesh.enabled:
        raise ConfigError("architecture C requires mesh.enabled=true")
    if cfg.architecture == "C" and not cfg.recovery.enabled:
        raise ConfigError("architecture C requires recovery.enabled=true")

    if cfg.mesh.enabled and cfg.mesh.transport != "zeromq":
        raise ConfigError(
            f"mesh.enabled=true requires transport=zeromq, got {cfg.mesh.transport!r}"
        )
    if not cfg.mesh.enabled and cfg.mesh.transport != "noop":
        raise ConfigError(
            f"mesh.enabled=false requires transport=noop, got {cfg.mesh.transport!r}"
        )

    if cfg.mesh.loss_prob > 0.0 and not cfg.mesh.enabled:
        raise ConfigError(
            "mesh.loss_prob>0 requires mesh.enabled=true — channel loss "
            "only applies to the C mesh (A/B carry no mesh)"
        )

    if cfg.architecture == "A":
        # exactly one monitor, on the GS, watching every UAV present
        if len(cfg.monitors) != 1:
            raise ConfigError("architecture A: expected exactly one monitor")
        if cfg.monitors[0].location != "ground_station":
            raise ConfigError("architecture A: monitor must be at ground_station")
        if cfg.isolation.enforcement != "ground_station_command":
            raise ConfigError(
                "architecture A: isolation.enforcement must be ground_station_command"
            )

    if cfg.architecture == "B":
        for m in cfg.monitors:
            if not m.location.startswith("uav_"):
                raise ConfigError(
                    f"architecture B: monitor.location must be a uav_*, got {m.location!r}"
                )
            if m.watches != (m.location,):
                raise ConfigError(
                    f"architecture B: monitor at {m.location} must watch only itself"
                )
            if "cross_check" in m.detectors:
                raise ConfigError(
                    "architecture B: cross_check detector is C-only "
                    "(requires mesh-shared peer telemetry)"
                )
        if cfg.isolation.enforcement != "local_self":
            raise ConfigError(
                "architecture B: isolation.enforcement must be local_self"
            )

    if cfg.architecture == "C":
        for m in cfg.monitors:
            if not m.location.startswith("uav_"):
                raise ConfigError(
                    f"architecture C: monitor.location must be a uav_*, got {m.location!r}"
                )
        if cfg.isolation.enforcement != "local_with_announce":
            raise ConfigError(
                "architecture C: isolation.enforcement must be local_with_announce"
            )
        # every UAV that has a monitor must also have a mesh endpoint
        uav_ids = {m.location for m in cfg.monitors}
        missing = uav_ids - set(cfg.mesh.endpoints.keys())
        if missing:
            raise ConfigError(
                f"architecture C: missing mesh endpoints for {sorted(missing)}"
            )


def load_architecture_config(path: Path | str) -> ArchitectureConfig:
    raw = _load_yaml(Path(path))
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top-level must be a mapping")

    _require_keys(
        raw,
        {"architecture", "monitors", "mesh", "recovery", "isolation"},
        "architecture config",
    )
    _no_extra_keys(
        raw,
        {"architecture", "monitors", "mesh", "recovery", "isolation"},
        "architecture config",
    )

    architecture = _enum(
        str(raw["architecture"]), VALID_ARCHITECTURES, "architecture"
    )

    monitors_raw = raw["monitors"]
    if not isinstance(monitors_raw, list) or not monitors_raw:
        raise ConfigError("monitors: must be a non-empty list")
    monitors = tuple(_parse_monitor(m, i) for i, m in enumerate(monitors_raw))

    cfg = ArchitectureConfig(
        architecture=architecture,
        monitors=monitors,
        mesh=_parse_mesh(raw["mesh"]),
        recovery=_parse_recovery(raw["recovery"]),
        isolation=_parse_isolation(raw["isolation"]),
    )
    _validate_architecture_invariants(cfg)
    return cfg


# ---------------------------------------------------------------------------
# Experiment loader
# ---------------------------------------------------------------------------


def _parse_waypoint(raw: dict[str, Any], idx: int) -> Waypoint:
    ctx = f"mission.waypoints[{idx}]"
    _require_keys(raw, {"north_m", "east_m", "alt_m"}, ctx)
    _no_extra_keys(raw, {"north_m", "east_m", "alt_m"}, ctx)
    return Waypoint(
        north_m=float(raw["north_m"]),
        east_m=float(raw["east_m"]),
        alt_m=float(raw["alt_m"]),
    )


def _parse_laps(raw: dict[str, Any], ctx: str) -> int:
    """Optional `laps`, defaulting to 1 (the pattern is the whole plan)."""
    if "laps" not in raw:
        return 1
    value = raw["laps"]
    # bool is an int subclass in Python; `laps: true` is a typo, not 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            f"{ctx}.laps: must be an integer, got {value!r}"
        )
    if value < 1:
        raise ConfigError(f"{ctx}.laps: must be >= 1, got {value}")
    return value


def _reject_consecutive_duplicates(
    plan: tuple[Waypoint, ...], ctx: str
) -> None:
    """Two identical adjacent items are a no-op for PX4 and always a bug.

    The usual cause: a lap pattern that closes itself (ends where it
    starts), so repeating it puts the same point twice at every seam.
    Caught here rather than by eyeballing a trajectory afterwards.
    """
    for i in range(1, len(plan)):
        if plan[i] == plan[i - 1]:
            raise ConfigError(
                f"{ctx}.waypoints: expanded plan items {i - 1} and {i} are "
                f"identical ({plan[i]}). Consecutive duplicate waypoints do "
                f"nothing; if this is a lap seam, drop the closing point "
                f"from the lap pattern."
            )


def _parse_mission(raw: dict[str, Any]) -> MissionConfig:
    ctx = "mission"
    _require_keys(raw, {"type", "duration_sec", "waypoints"}, ctx)
    _no_extra_keys(raw, {"type", "duration_sec", "waypoints", "laps"}, ctx)

    mission_type = _enum(str(raw["type"]), VALID_MISSION_TYPES, f"{ctx}.type")
    duration = float(raw["duration_sec"])
    if duration <= 0:
        raise ConfigError(f"{ctx}.duration_sec: must be positive, got {duration}")

    wps_raw = raw["waypoints"]
    if not isinstance(wps_raw, list) or len(wps_raw) < 2:
        raise ConfigError(f"{ctx}.waypoints: need at least two")
    lap = tuple(_parse_waypoint(w, i) for i, w in enumerate(wps_raw))

    laps = _parse_laps(raw, ctx)
    expanded = lap * laps
    _reject_consecutive_duplicates(expanded, ctx)

    return MissionConfig(
        type=mission_type,
        duration_sec=duration,
        waypoints=expanded,
        laps=laps,
    )


def _parse_telemetry_endpoint(raw: dict[str, Any], idx: int) -> TelemetryEndpointSpec:
    ctx = f"telemetry.endpoints[{idx}]"
    _require_keys(raw, {"uav_id", "endpoint", "sysid"}, ctx)
    _no_extra_keys(raw, {"uav_id", "endpoint", "sysid"}, ctx)
    return TelemetryEndpointSpec(
        uav_id=str(raw["uav_id"]),
        endpoint=str(raw["endpoint"]),
        sysid=int(raw["sysid"]),
    )


def _parse_telemetry(raw: dict[str, Any]) -> TelemetryConfig:
    ctx = "telemetry"
    _require_keys(raw, {"endpoints"}, ctx)
    _no_extra_keys(raw, {"endpoints"}, ctx)
    eps_raw = raw["endpoints"]
    if not isinstance(eps_raw, list) or not eps_raw:
        raise ConfigError(f"{ctx}.endpoints: must be a non-empty list")
    endpoints = tuple(_parse_telemetry_endpoint(e, i) for i, e in enumerate(eps_raw))
    seen: set[str] = set()
    for e in endpoints:
        if e.uav_id in seen:
            raise ConfigError(f"{ctx}.endpoints: duplicate uav_id {e.uav_id!r}")
        seen.add(e.uav_id)
    return TelemetryConfig(endpoints=endpoints)


def _parse_runs(raw: dict[str, Any]) -> RunsConfig:
    ctx = "runs"
    _require_keys(
        raw,
        {"baseline_per_arch", "attacks_per_arch_per_attack", "observation_after_attack_sec"},
        ctx,
    )
    _no_extra_keys(
        raw,
        {"baseline_per_arch", "attacks_per_arch_per_attack", "observation_after_attack_sec"},
        ctx,
    )
    baseline = int(raw["baseline_per_arch"])
    per_attack = int(raw["attacks_per_arch_per_attack"])
    obs = float(raw["observation_after_attack_sec"])
    if baseline < 0 or per_attack < 0:
        raise ConfigError(f"{ctx}: counts must be non-negative")
    if obs <= 0:
        raise ConfigError(f"{ctx}.observation_after_attack_sec: must be positive")
    return RunsConfig(
        baseline_per_arch=baseline,
        attacks_per_arch_per_attack=per_attack,
        observation_after_attack_sec=obs,
    )


def load_experiment_config(path: Path | str) -> ExperimentConfig:
    raw = _load_yaml(Path(path))
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top-level must be a mapping")

    _require_keys(
        raw, {"mission", "telemetry", "attacks", "runs"}, "experiment config"
    )
    _no_extra_keys(
        raw, {"mission", "telemetry", "attacks", "runs"}, "experiment config"
    )

    attacks_raw = raw["attacks"]
    if not isinstance(attacks_raw, list) or not attacks_raw:
        raise ConfigError("attacks: must be a non-empty list")
    attacks = tuple(str(a) for a in attacks_raw)
    for a in attacks:
        _enum(a, VALID_ATTACKS, "attacks")
    if len(set(attacks)) != len(attacks):
        raise ConfigError(f"attacks: duplicates not allowed, got {list(attacks)}")

    return ExperimentConfig(
        mission=_parse_mission(raw["mission"]),
        telemetry=_parse_telemetry(raw["telemetry"]),
        attacks=attacks,
        runs=_parse_runs(raw["runs"]),
    )


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        raise ConfigError(f"{path}: file not found")
    with open(path, "r", encoding="utf-8") as f:
        try:
            return yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"{path}: YAML parse error: {e}") from e
