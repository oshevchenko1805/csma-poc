"""
Tests for CommandInjectionDetector.

The detector is stateless: every test exercises a single feed() call.
"""

from __future__ import annotations

import pytest

from core.events import SecurityEvent, TelemetryEvent
from detectors.command import COMMAND_MSG_TYPES, CommandInjectionDetector


def _command(
    *,
    uav_id: str,
    src_sysid: int,
    msg_type: str = "COMMAND_LONG",
    command_id: int = 192,  # MAV_CMD_DO_REPOSITION
    target_system: int = 1,
    target_component: int = 1,
    extra: dict | None = None,
) -> TelemetryEvent:
    data = {
        "command": command_id,
        "target_system": target_system,
        "target_component": target_component,
        "_src_sysid": src_sysid,
    }
    if extra:
        data.update(extra)
    return TelemetryEvent(
        source=f"monitor_{uav_id}",
        uav_id=uav_id,
        msg_type=msg_type,
        data=data,
    )


class TestCommandInjectionDetector:
    def test_default_whitelist(self):
        d = CommandInjectionDetector(target_uav="uav_0", source="m")
        assert d.whitelist == frozenset({1, 2, 3, 255})

    def test_name_and_target(self):
        d = CommandInjectionDetector(target_uav="uav_2", source="m")
        assert d.name == "command"
        assert d.target_uav == "uav_2"

    @pytest.mark.parametrize("legit_sysid", [1, 2, 3, 255])
    def test_whitelisted_sysid_passes(self, legit_sysid: int):
        d = CommandInjectionDetector(target_uav="uav_0", source="m")
        result = d.feed(_command(uav_id="uav_0", src_sysid=legit_sysid))
        assert result is None

    @pytest.mark.parametrize("bad_sysid", [0, 4, 10, 100, 200, 254])
    def test_non_whitelisted_sysid_fires(self, bad_sysid: int):
        d = CommandInjectionDetector(
            target_uav="uav_0", source="monitor_uav_0"
        )
        result = d.feed(_command(uav_id="uav_0", src_sysid=bad_sysid))

        assert isinstance(result, SecurityEvent)
        assert result.detector == "command"
        assert result.target_uav == "uav_0"
        assert result.source == "monitor_uav_0"
        assert result.severity == "high"
        ev = result.evidence
        assert ev["src_sysid"] == bad_sysid
        assert ev["command_type"] == "COMMAND_LONG"
        assert ev["command_id"] == 192
        assert ev["target_system"] == 1
        assert ev["target_component"] == 1
        assert ev["whitelist"] == [1, 2, 3, 255]

    def test_command_int_also_checked(self):
        d = CommandInjectionDetector(target_uav="uav_0", source="m")
        result = d.feed(
            _command(uav_id="uav_0", src_sysid=10, msg_type="COMMAND_INT")
        )
        assert result is not None
        assert result.evidence["command_type"] == "COMMAND_INT"

    def test_non_command_msg_type_ignored(self):
        d = CommandInjectionDetector(target_uav="uav_0", source="m")
        # Heartbeat from rogue sysid is not the command-injection signature.
        ev = TelemetryEvent(
            source="m",
            uav_id="uav_0",
            msg_type="HEARTBEAT",
            data={"_src_sysid": 99},
        )
        assert d.feed(ev) is None

    def test_wrong_uav_ignored(self):
        d = CommandInjectionDetector(target_uav="uav_0", source="m")
        # Even if a bad sysid is observed, this detector instance only
        # cares about its own target UAV.
        result = d.feed(_command(uav_id="uav_1", src_sysid=99))
        assert result is None

    def test_missing_src_sysid_does_not_fire(self):
        """No evidence -> no alarm. Avoids false positives on partial data."""
        d = CommandInjectionDetector(target_uav="uav_0", source="m")
        ev = TelemetryEvent(
            source="m",
            uav_id="uav_0",
            msg_type="COMMAND_LONG",
            data={"command": 192, "target_system": 1, "target_component": 1},
        )
        # _src_sysid missing
        assert d.feed(ev) is None

    def test_invalid_src_sysid_does_not_fire(self):
        """Non-numeric src_sysid is bad data, not an attack signature."""
        d = CommandInjectionDetector(target_uav="uav_0", source="m")
        ev = TelemetryEvent(
            source="m",
            uav_id="uav_0",
            msg_type="COMMAND_LONG",
            data={"command": 192, "_src_sysid": "garbage"},
        )
        assert d.feed(ev) is None

    def test_custom_whitelist(self):
        """An operator can tighten the whitelist (e.g. exclude GCS)."""
        d = CommandInjectionDetector(
            target_uav="uav_0", source="m", whitelist={1, 2, 3}
        )
        # GCS no longer trusted.
        result = d.feed(_command(uav_id="uav_0", src_sysid=255))
        assert result is not None
        assert result.evidence["whitelist"] == [1, 2, 3]

        # Self still trusted.
        assert d.feed(_command(uav_id="uav_0", src_sysid=1)) is None

    def test_severity_configurable(self):
        d = CommandInjectionDetector(
            target_uav="uav_0", source="m", severity="medium"
        )
        result = d.feed(_command(uav_id="uav_0", src_sysid=99))
        assert result is not None
        assert result.severity == "medium"

    def test_no_hysteresis_each_command_fires_separately(self):
        """A burst of injected commands should produce N alerts, not 1."""
        d = CommandInjectionDetector(target_uav="uav_0", source="m")
        results = [
            d.feed(_command(uav_id="uav_0", src_sysid=99))
            for _ in range(5)
        ]
        assert all(r is not None for r in results)
        # Each alert is a distinct SecurityEvent.
        ids = {r.event_id for r in results}
        assert len(ids) == 5

    def test_reset_does_not_crash(self):
        d = CommandInjectionDetector(target_uav="uav_0", source="m")
        d.feed(_command(uav_id="uav_0", src_sysid=99))
        d.reset()  # stateless, but must not raise

    def test_command_msg_types_constant(self):
        """Constant exposed for monitors to know which messages to route."""
        assert COMMAND_MSG_TYPES == frozenset({"COMMAND_LONG", "COMMAND_INT"})
