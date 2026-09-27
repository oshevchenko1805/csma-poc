"""B1 item 3: configs/architecture_c_ranging.yaml, config validation,
factory and monitor wiring of the ranging detector. No ZMQ, no MAVLink:
a recording mesh and direct callbacks drive the monitor."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable

import pytest

from core.config import ConfigError, load_architecture_config, load_experiment_config
from core.events import BaseEvent, PeerPositionAnnounce, TelemetryEvent
from core.mesh import MeshBus
from detectors.heartbeat import HeartbeatDetector
from detectors.ranging import RangingConsistencyDetector
from runners.factory import build_fleet
from runners.monitor import Monitor

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
REF = (47.397742, 8.545594, 488.0)
R = 6_371_000.0


def geo(e, n, u):
    return (REF[0] + math.degrees(n / R),
            REF[1] + math.degrees(e / (R * math.cos(math.radians(REF[0])))),
            REF[2] + u)


class FakeConnection:
    def recv_match(self, **_kw):
        return None

    def close(self):
        pass


class RecordingMesh(MeshBus):
    def __init__(self):
        self.published: list[BaseEvent] = []
        self._subs: dict[str, list[Callable]] = {}

    def start(self):
        pass

    def stop(self):
        pass

    def publish(self, event):
        self.published.append(event)

    def subscribe(self, topic, callback):
        self._subs.setdefault(topic, []).append(callback)

    def deliver(self, topic, event):
        for cb in self._subs.get(topic, []):
            cb(event)


class DictRangeSource:
    """Exact ranges from fixed truth positions (local ENU metres)."""

    def __init__(self, truth):
        self.truth = truth
        self.calls = []

    def range_m(self, a, b, t):
        self.calls.append((a, b, t))
        return math.dist(self.truth[a], self.truth[b])


def _cfg(name):
    return load_architecture_config(CONFIG_DIR / f"architecture_{name}.yaml")


def _fleet(tmp_path, arch="c_ranging", range_source=None):
    meshes = []

    def mesh_factory(_self_ep, _peers):
        m = RecordingMesh()
        meshes.append(m)
        return m

    fleet = build_fleet(
        arch_cfg=_cfg(arch),
        exp_cfg=load_experiment_config(CONFIG_DIR / "experiment.yaml"),
        run_id="t", log_root=tmp_path,
        connection_factory=lambda _ep: FakeConnection(),
        mesh_factory=mesh_factory,
        range_source=range_source,
    )
    return fleet, meshes


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_c_ranging_loads(self):
        cfg = _cfg("c_ranging")
        assert cfg.architecture == "C"
        for m in cfg.monitors:
            assert m.detectors == ("heartbeat", "command", "gps", "cross_check", "ranging")

    def test_c_ranging_differs_from_c_only_by_the_detector(self):
        c, cr = _cfg("c"), _cfg("c_ranging")
        assert cr.mesh == c.mesh and cr.recovery == c.recovery and cr.isolation == c.isolation
        assert [m.location for m in cr.monitors] == [m.location for m in c.monitors]
        for a, b in zip(c.monitors, cr.monitors):
            assert b.detectors == a.detectors + ("ranging",)

    def test_v1_configs_have_no_ranging(self):
        for name in ("a", "b", "c"):
            assert all("ranging" not in m.detectors for m in _cfg(name).monitors)

    @pytest.mark.parametrize("name", ["a", "b"])
    def test_ranging_rejected_outside_c(self, tmp_path, name):
        text = (CONFIG_DIR / f"architecture_{name}.yaml").read_text()
        text = (text.replace("detectors: [heartbeat, command, gps]",
                             "detectors: [heartbeat, command, gps, ranging]")
                    .replace("      - gps\n", "      - gps\n      - ranging\n"))
        assert "ranging" in text
        p = tmp_path / "arch.yaml"
        p.write_text(text)
        with pytest.raises(ConfigError, match="ranging detector is C-only"):
            load_architecture_config(p)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestFactory:
    TRUTH = {"uav_0": (0.0, 0.0, 10.0), "uav_1": (0.0, 0.0, 15.0), "uav_2": (0.0, 0.0, 20.0)}

    def test_every_c_monitor_gets_a_ranging_detector(self, tmp_path):
        fleet, _ = _fleet(tmp_path, range_source=DictRangeSource(self.TRUTH))
        for mon in fleet.monitors:
            assert isinstance(mon.ranging, RangingConsistencyDetector)
            assert mon.ranging.monitor_uav_id == mon.uav_id
            assert all(not isinstance(d, RangingConsistencyDetector) for d in mon._detectors)

    def test_range_fn_is_bound_to_the_measuring_uav(self, tmp_path):
        src = DictRangeSource(self.TRUTH)
        fleet, _ = _fleet(tmp_path, range_source=src)
        mon = next(m for m in fleet.monitors if m.uav_id == "uav_2")
        mon.ranging._range_fn("uav_0", 5.0)
        assert src.calls == [("uav_2", "uav_0", 5.0)]

    def test_missing_range_source_fails_fast(self, tmp_path):
        with pytest.raises(ValueError, match="range_source"):
            _fleet(tmp_path, range_source=None)

    def test_v1_c_has_no_ranging_even_with_a_source(self, tmp_path):
        fleet, _ = _fleet(tmp_path, arch="c", range_source=DictRangeSource(self.TRUTH))
        assert all(m.ranging is None for m in fleet.monitors)

    def test_v1_c_builds_without_a_source(self, tmp_path):
        fleet, _ = _fleet(tmp_path, arch="c")
        assert all(m.ranging is None for m in fleet.monitors)


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


def _monitor(tmp_path, ranging, mesh="default", uav="uav_1"):
    return Monitor(
        uav_id=uav, source=f"monitor_{uav}", telemetry_endpoint="x", sysid=2,
        detectors=[HeartbeatDetector(target_uav=uav, source="m", timeout_sec=60.0)],
        log_path=tmp_path / "m.jsonl",
        mesh=RecordingMesh() if mesh == "default" else mesh,
        ranging=ranging,
        _telemetry_connection=FakeConnection(),
    )


def _own_fix(uav, enu, t):
    lat, lon, alt = geo(*enu)
    return TelemetryEvent(source="l", uav_id=uav, msg_type="GLOBAL_POSITION_INT",
                          timestamp=t,
                          data={"lat": int(round(lat * 1e7)), "lon": int(round(lon * 1e7)),
                                "alt": int(round(alt * 1000))})


def _ann(uav, enu, t):
    lat, lon, alt = geo(*enu)
    return PeerPositionAnnounce(source=f"monitor_{uav}", uav_id=uav, lat=lat, lon=lon,
                                alt=alt, sample_timestamp=t)


class TestMonitor:
    def test_ranging_requires_mesh(self, tmp_path):
        det = RangingConsistencyDetector("uav_1", "m", lambda p, t: 1.0)
        with pytest.raises(ValueError, match="requires mesh"):
            _monitor(tmp_path, det, mesh=None)

    def test_ranging_uav_mismatch_rejected(self, tmp_path):
        det = RangingConsistencyDetector("uav_0", "m", lambda p, t: 1.0)
        with pytest.raises(ValueError, match="does not match"):
            _monitor(tmp_path, det)

    def test_subscribes_to_peer_positions(self, tmp_path):
        det = RangingConsistencyDetector("uav_1", "m", lambda p, t: 1.0)
        mesh = RecordingMesh()
        _monitor(tmp_path, det, mesh=mesh)
        assert "peer_position" in mesh._subs

    def test_no_ranging_no_subscription(self, tmp_path):
        mesh = RecordingMesh()
        _monitor(tmp_path, None, mesh=mesh)
        assert "peer_position" not in mesh._subs

    def test_own_fix_feeds_the_detector(self, tmp_path):
        det = RangingConsistencyDetector("uav_1", "m", lambda p, t: 1.0)
        mon = _monitor(tmp_path, det)
        mon._on_telemetry(_own_fix("uav_1", (1.0, 2.0, 3.0), 100.0))
        assert len(det._own.samples) == 1
        t, lat, lon, alt = det._own.samples[0]
        assert t == 100.0 and alt == pytest.approx(REF[2] + 3.0, abs=1e-3)

    def test_end_to_end_peer_alarm_is_emitted_and_logged(self, tmp_path):
        """uav_1's monitor: own fixes from telemetry, announcements from the
        mesh, exact ranges; uav_0 announces a position 3 m off along the line
        of sight -> one ranging SecurityEvent against uav_0."""
        truth = {"uav_0": (0.0, 20.0, 10.0), "uav_1": (0.0, 0.0, 10.0), "uav_2": (20.0, 0.0, 10.0)}
        src = DictRangeSource(truth)
        det = RangingConsistencyDetector("uav_1", "monitor_uav_1",
                                         lambda p, t: src.range_m("uav_1", p, t))
        mesh = RecordingMesh()
        mon = _monitor(tmp_path, det, mesh=mesh)
        for k in range(8):
            t = 100.0 + k
            mon._on_telemetry(_own_fix("uav_1", truth["uav_1"], t))
            mesh.deliver("peer_position", _ann("uav_2", truth["uav_2"], t))
            off = 3.0 if k >= 3 else 0.0
            mesh.deliver("peer_position", _ann("uav_0", (0.0, 20.0 + off, 10.0), t))
        events = [json.loads(l) for l in (tmp_path / "m.jsonl").read_text().splitlines()]
        rng = [e for e in events if e.get("event_type") == "security"
               and e.get("detector") == "ranging"]
        assert len(rng) == 1
        assert rng[0]["target_uav"] == "uav_0"
        assert rng[0]["evidence"]["path"] == "peer"
        assert mon.stats["security_emitted"] == 1
        assert mon.stats["handler_errors"] == 0

    def test_failing_ranging_does_not_block_cross_check(self, tmp_path):
        class Boom(RangingConsistencyDetector):
            def feed_peer_position(self, ann):
                raise RuntimeError("x")

        from detectors.cross_check import CrossCheckDetector
        cc = CrossCheckDetector(monitor_uav_id="uav_1", source="monitor_uav_1")
        mesh = RecordingMesh()
        mon = Monitor(
            uav_id="uav_1", source="monitor_uav_1", telemetry_endpoint="x", sysid=2,
            detectors=[HeartbeatDetector(target_uav="uav_1", source="m", timeout_sec=60.0)],
            log_path=tmp_path / "m.jsonl", mesh=mesh, cross_check=cc,
            ranging=Boom("uav_1", "m", lambda p, t: 1.0),
            _telemetry_connection=FakeConnection(),
        )
        mesh.deliver("peer_position", _ann("uav_0", (0.0, 0.0, 10.0), 0.0))
        mesh.deliver("peer_position", _ann("uav_0", (0.0, 500.0, 10.0), 1.0))  # teleport
        assert mon.stats["handler_errors"] == 2
        assert cc.is_alerted("uav_0")
