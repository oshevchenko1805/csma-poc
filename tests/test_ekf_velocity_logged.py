"""B1 item 7: EKF velocity (LOCAL_POSITION_NED vx, vy) must be in the
per-monitor telemetry log, for vel_err_mps and creep_mps in S3
(H3_PREREGISTRATION.md, P-B1-8). The pipeline already records the full
message; this guards against a future field filter dropping it (the B0
probe script did drop it)."""

from __future__ import annotations

import json

from core.events import TelemetryEvent
from core.telemetry import _sanitize_dict
from detectors.heartbeat import HeartbeatDetector
from runners.monitor import DEFAULT_TELEMETRY_LOG_TYPES, Monitor
from tests.test_ranging_wiring import FakeConnection


class _Msg:
    """pymavlink-like LOCAL_POSITION_NED."""

    def to_dict(self):
        return {"mavpackettype": "LOCAL_POSITION_NED", "time_boot_ms": 1000,
                "x": 1.0, "y": 2.0, "z": -20.0, "vx": 0.5, "vy": -0.25, "vz": 0.0}


def test_local_position_ned_is_recorded_by_default():
    assert "LOCAL_POSITION_NED" in DEFAULT_TELEMETRY_LOG_TYPES


def test_listener_keeps_velocity_fields():
    fields = _sanitize_dict(_Msg().to_dict())
    assert fields["vx"] == 0.5 and fields["vy"] == -0.25 and "vz" in fields


def test_monitor_log_contains_vx_vy(tmp_path):
    log = tmp_path / "telemetry_monitor_uav_0.jsonl"
    mon = Monitor(
        uav_id="uav_0", source="monitor_uav_0", telemetry_endpoint="x", sysid=1,
        detectors=[HeartbeatDetector(target_uav="uav_0", source="m", timeout_sec=60.0)],
        log_path=tmp_path / "m.jsonl", telemetry_log_path=log,
        _telemetry_connection=FakeConnection(),
    )
    mon._on_telemetry(TelemetryEvent(source="l", uav_id="uav_0",
                                     msg_type="LOCAL_POSITION_NED",
                                     data=_sanitize_dict(_Msg().to_dict())))
    mon.stop()
    rec = [json.loads(l) for l in log.read_text().splitlines()]
    assert len(rec) == 1
    assert rec[0]["data"]["vx"] == 0.5 and rec[0]["data"]["vy"] == -0.25
