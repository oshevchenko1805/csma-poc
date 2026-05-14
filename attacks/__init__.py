"""Attack injection modules.

Three concrete attacks implementing the AttackInjector contract:

  - CommDisruptionInjector       (iptables DROP rule)
  - CommandInjectionInjector     (periodic MAVLink commands with spoofed sysid)
  - GpsSpoofingInjector          (PX4 SITL param manipulation)

Plus NullAttackInjector for baseline runs.
"""

from attacks.base import AttackContext, AttackInjector, NullAttackInjector
from attacks.command_injection import (
    CommandInjectionInjector,
    MavlinkSender,
    PymavlinkSender,
)
from attacks.comm_disruption import (
    CommDisruptionInjector,
    IptablesRunner,
    SubprocessIptablesRunner,
)
from attacks.gps_spoofing import (
    DefaultGpsSpoofingRunner,
    GpsSpoofingInjector,
    GpsSpoofingRunner,
)

__all__ = [
    "AttackContext",
    "AttackInjector",
    "NullAttackInjector",
    "CommDisruptionInjector",
    "IptablesRunner",
    "SubprocessIptablesRunner",
    "CommandInjectionInjector",
    "MavlinkSender",
    "PymavlinkSender",
    "GpsSpoofingInjector",
    "GpsSpoofingRunner",
    "DefaultGpsSpoofingRunner",
]
