"""B1 item 6: detector_takeout also silences the ranging detector on the
target's monitor (both paths); the peers' ranging keeps running
(H3_PREREGISTRATION.md, P-B1-3)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from attacks.base import AttackContext
from attacks.detector_takeout import DetectorTakeoutInjector
from detectors.cross_check import CrossCheckDetector
from detectors.heartbeat import HeartbeatDetector
from detectors.ranging import RangingConsistencyDetector
from runners.monitor import Monitor
from tests.test_ranging_wiring import (
    DictRangeSource,
    FakeConnection,
    RecordingMesh,
    _ann,
    _fleet,
    _own_fix,
)

TRUTH = {"uav_0": (0.0, 20.0, 10.0), "uav_1": (0.0, 0.0, 10.0), "uav_2": (20.0, 0.0, 10.0)}


def _takeout(fleet, target="uav_0"):
    inj = DetectorTakeoutInjector()
    loop = asyncio.new_event_loop()
    loop.run_until_complete(inj.arm(AttackContext(
        target_uav=target, target_sysid=1, log_dir=Path("/tmp"),
        monitors=tuple(fleet.monitors))))
    loop.run_until_complete(inj.fire())
    return inj


def _ranging_events(log: Path):
    if not log.exists():
        return []
    return [e for e in map(json.loads, log.read_text().splitlines())
            if e.get("event_type") == "security" and e.get("detector") == "ranging"]


def test_only_the_targets_ranging_is_silenced(tmp_path):
    fleet, _ = _fleet(tmp_path, range_source=DictRangeSource(TRUTH))
    assert all(m.ranging_active for m in fleet.monitors)
    inj = _takeout(fleet)
    assert inj.disabled_uavs == ["uav_0"]
    active = {m.uav_id: m.ranging_active for m in fleet.monitors}
    assert active == {"uav_0": False, "uav_1": True, "uav_2": True}
    others = [m for m in fleet.monitors if m.uav_id != "uav_0"]
    assert all(len(m._detectors) == 3 for m in others)


def test_peer_path_still_detects_after_takeout(tmp_path):
    """DT on uav_0, then uav_0 announces a position 3 m off along the line
    of sight to uav_1: uav_1's monitor flags uav_0; uav_0's monitor emits
    no ranging event (its self path is taken out)."""
    fleet, meshes = _fleet(tmp_path, range_source=DictRangeSource(TRUTH))
    _takeout(fleet)
    mons = {m.uav_id: m for m in fleet.monitors}
    mesh_of = dict(zip([m.uav_id for m in fleet.monitors], meshes))
    for k in range(8):
        t = 100.0 + k
        off = 3.0 if k >= 3 else 0.0
        belief = dict(TRUTH)
        belief["uav_0"] = (0.0, 20.0 + off, 10.0)
        for u, m in mons.items():
            m._on_telemetry(_own_fix(u, belief[u], t))
        for j in ("uav_0", "uav_1", "uav_2"):
            a = _ann(j, belief[j], t)
            for u, mesh in mesh_of.items():
                if u != j:
                    mesh.deliver("peer_position", a)
    ev1 = _ranging_events(fleet.log_dir / "monitor_uav_1.jsonl")
    assert [e["target_uav"] for e in ev1] == ["uav_0"]
    assert _ranging_events(fleet.log_dir / "monitor_uav_0.jsonl") == []
    assert mons["uav_0"].ranging._own.samples == []   # not fed after takeout


def _single_monitor(tmp_path, ranging):
    mesh = RecordingMesh()
    cc = CrossCheckDetector(monitor_uav_id="uav_1", source="monitor_uav_1")
    mon = Monitor(
        uav_id="uav_1", source="monitor_uav_1", telemetry_endpoint="x", sysid=2,
        detectors=[HeartbeatDetector(target_uav="uav_1", source="m", timeout_sec=60.0)],
        log_path=tmp_path / "m.jsonl", mesh=mesh, cross_check=cc, ranging=ranging,
        _telemetry_connection=FakeConnection(),
    )
    return mon, mesh, cc


def test_cross_check_keeps_running_after_takeout(tmp_path):
    det = RangingConsistencyDetector("uav_1", "m", lambda p, t: 20.0)
    mon, mesh, cc = _single_monitor(tmp_path, det)
    mon.disable_local_detectors()
    mesh.deliver("peer_position", _ann("uav_0", (0.0, 0.0, 10.0), 0.0))
    mesh.deliver("peer_position", _ann("uav_0", (0.0, 500.0, 10.0), 1.0))
    assert cc.is_alerted("uav_0")
    assert det._pairs == {}


def test_v1_monitor_without_ranging_unaffected(tmp_path):
    mon, mesh, cc = _single_monitor(tmp_path, None)
    assert not mon.ranging_active
    mon.disable_local_detectors()
    assert mon._detectors == [] and not mon.ranging_active
    mesh.deliver("peer_position", _ann("uav_0", (0.0, 0.0, 10.0), 0.0))
    mesh.deliver("peer_position", _ann("uav_0", (0.0, 500.0, 10.0), 1.0))
    assert cc.is_alerted("uav_0")
