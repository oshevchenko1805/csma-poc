"""
CommandInjectionDetector — MAVLink command injection via sysid whitelist.

Signature
---------
A COMMAND_LONG or COMMAND_INT message arrives at the target UAV from a
source system ID that is not on the whitelist of legitimate command
sources. By default the whitelist is {1, 2, 3, 255}: the three SITL UAV
peers plus the standard ground-control-station sysid.

Each illegitimate command produces its own SecurityEvent — there is no
hysteresis. An attacker spraying ten waypoint overrides should produce
ten security events, because (a) the count itself is a useful metric of
attack intensity and (b) we want the *same* command-id and parameters in
the evidence of every alert for post-hoc forensics. If alert volume
becomes operationally noisy in a real deployment, rate-limiting belongs
in the decision module, not here.

Operational caveat (Chapter 4)
------------------------------
The detector requires that the host monitor receives a copy of every
command directed at the target UAV. PX4 SITL by default does not echo
incoming commands on its outbound stream. The PoC realizes this by
running an additional listener on a MAVLink router endpoint into which
the attack-injection script publishes; a real deployment would either
inspect the local MAVLink router on the companion computer or run a
kernel-level packet filter on the command channel. The detector logic
itself is independent of this transport detail.

The `_src_sysid` metadata field is populated by core.telemetry from
`msg.get_srcSystem()`.
"""

from __future__ import annotations

from typing import Iterable, Optional

from core.events import SecurityEvent, TelemetryEvent
from detectors.base import Detector


# Message types that count as "commands" for the purposes of this
# detector. COMMAND_LONG and COMMAND_INT are the standard surface area
# for waypoint overrides, mode changes, and arming. Mission-item
# messages (MISSION_ITEM, MISSION_ITEM_INT) are deliberately excluded
# from the v1 detector — they are part of normal mission upload from
# the GCS, and policing them requires mission-state awareness rather
# than a sysid whitelist. Future detector revisions can add them once
# we have mission-state tracking.
COMMAND_MSG_TYPES: frozenset[str] = frozenset({"COMMAND_LONG", "COMMAND_INT"})


class CommandInjectionDetector(Detector):
    """Detect command injection via source-system-ID whitelist."""

    DEFAULT_WHITELIST: frozenset[int] = frozenset({1, 2, 3, 255})
    DEFAULT_SEVERITY: str = "high"

    def __init__(
        self,
        target_uav: str,
        source: str,
        *,
        whitelist: Optional[Iterable[int]] = None,
        severity: str = DEFAULT_SEVERITY,
    ) -> None:
        self._target_uav = target_uav
        self._source = source
        self._whitelist: frozenset[int] = (
            frozenset(int(x) for x in whitelist)
            if whitelist is not None
            else self.DEFAULT_WHITELIST
        )
        self._severity = severity

    # ----- Detector API -----

    @property
    def name(self) -> str:
        return "command"

    @property
    def target_uav(self) -> str:
        return self._target_uav

    @property
    def whitelist(self) -> frozenset[int]:
        return self._whitelist

    def feed(self, event: TelemetryEvent) -> Optional[SecurityEvent]:
        # Defensive routing check.
        if event.uav_id != self._target_uav:
            return None
        if event.msg_type not in COMMAND_MSG_TYPES:
            return None

        src = event.data.get("_src_sysid")
        if src is None:
            # Origin missing means we can't evaluate. Do not fire an alarm
            # on missing data — that produces false positives on telemetry
            # types that haven't been wired up yet. Log a stat instead in
            # a future revision if useful.
            return None

        try:
            src_int = int(src)
        except (TypeError, ValueError):
            return None

        if src_int in self._whitelist:
            return None  # legitimate sender

        return SecurityEvent(
            source=self._source,
            detector=self.name,
            target_uav=self._target_uav,
            severity=self._severity,
            evidence={
                "src_sysid": src_int,
                "command_type": event.msg_type,
                "command_id": event.data.get("command"),
                "target_system": event.data.get("target_system"),
                "target_component": event.data.get("target_component"),
                "whitelist": sorted(self._whitelist),
            },
        )

    def reset(self) -> None:
        # Stateless detector — nothing to clear. Method exists to satisfy
        # the Detector contract and to keep call sites uniform.
        pass
