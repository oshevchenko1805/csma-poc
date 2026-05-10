"""
GpsSpoofingDetector — GPS spoofing via EKF innovation residuals.

Signature
---------
PX4's EKF2 publishes ESTIMATOR_STATUS messages containing six
"innovation test ratios" — normalized deviations between sensor
measurements and the filter's own predictions. The relevant field for
horizontal-position spoofing is `pos_horiz_ratio`. Values > 1.0 mean
the GPS measurement failed the filter's chi-squared test at the 1-sigma
level, which is PX4's own internal warning threshold.

A genuine spoofing attack drifts the reported position slowly enough to
evade outlier rejection, but the filter's residual still grows because
the inertial-only prediction (driven by the IMU) diverges from the
spoofed GPS over seconds. We therefore declare an alarm when
`pos_horiz_ratio > threshold` is sustained over `N` consecutive
ESTIMATOR_STATUS samples.

This is the canonical GPS-spoofing detection approach in the UAV
literature (PX4 itself uses the same residuals to switch to GPS-denied
modes). It does not require any model beyond what the autopilot
already publishes.

Timing
------
ESTIMATOR_STATUS arrives at 1 Hz on PX4 SITL (verified empirically in
the live smoke-test). With `sustained_samples=3` the minimum detection
latency is therefore ~3 seconds. This is documented as the MTTD floor
for GPS spoofing in Chapter 5 — it is a property of PX4's publishing
rate, not of the detector. Increasing the rate (param
SDLOG_PROFILE / SDLOG_MISSION_LOG, or MAVLink stream interval) is a
PX4-side knob the dissertation can discuss as deployment guidance.

Hysteresis
----------
One SecurityEvent per detection cycle. When the ratio drops back below
threshold, the consecutive counter resets *and* the hysteresis flag
clears, so a fresh sustained spike fires a fresh alarm. This is
critical for runs that span attack-recovery-attack cycles.

Output evidence fields
----------------------
    pos_horiz_ratio       at the moment of detection
    threshold             configured threshold (for reproducibility)
    sustained_samples     number of consecutive samples above threshold
    vel_ratio             secondary signal — useful in post-hoc forensics
    pos_vert_ratio        secondary signal
"""

from __future__ import annotations

from typing import Optional

from core.events import SecurityEvent, TelemetryEvent
from detectors.base import Detector


class GpsSpoofingDetector(Detector):
    """Detect GPS spoofing via sustained EKF innovation residuals."""

    DEFAULT_THRESHOLD: float = 1.0
    DEFAULT_SUSTAINED_SAMPLES: int = 3
    DEFAULT_SEVERITY: str = "high"

    def __init__(
        self,
        target_uav: str,
        source: str,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        sustained_samples: int = DEFAULT_SUSTAINED_SAMPLES,
        severity: str = DEFAULT_SEVERITY,
    ) -> None:
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        if sustained_samples < 1:
            raise ValueError("sustained_samples must be >= 1")

        self._target_uav = target_uav
        self._source = source
        self._threshold = float(threshold)
        self._sustained_samples = int(sustained_samples)
        self._severity = severity

        self._consecutive_above: int = 0
        self._alerted: bool = False

    # ----- Detector API -----

    @property
    def name(self) -> str:
        return "gps"

    @property
    def target_uav(self) -> str:
        return self._target_uav

    def feed(self, event: TelemetryEvent) -> Optional[SecurityEvent]:
        # Defensive routing checks.
        if event.uav_id != self._target_uav:
            return None
        if event.msg_type != "ESTIMATOR_STATUS":
            return None

        ratio_raw = event.data.get("pos_horiz_ratio")
        if ratio_raw is None:
            return None

        try:
            ratio = float(ratio_raw)
        except (TypeError, ValueError):
            return None

        if ratio > self._threshold:
            self._consecutive_above += 1
            if (
                self._consecutive_above >= self._sustained_samples
                and not self._alerted
            ):
                self._alerted = True
                return self._build_alert(ratio, event)
        else:
            # Below threshold: reset both counter and hysteresis flag so
            # the next sustained spike fires a fresh alarm.
            self._consecutive_above = 0
            if self._alerted:
                self._alerted = False

        return None

    def reset(self) -> None:
        self._consecutive_above = 0
        self._alerted = False

    # ----- Diagnostics -----

    @property
    def consecutive_above_threshold(self) -> int:
        return self._consecutive_above

    @property
    def is_alerted(self) -> bool:
        return self._alerted

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def sustained_samples(self) -> int:
        return self._sustained_samples

    # ----- internals -----

    def _build_alert(
        self, ratio: float, event: TelemetryEvent
    ) -> SecurityEvent:
        # Pull secondary signals if present. They don't affect detection
        # but are valuable for post-hoc forensics — e.g. distinguishing
        # spoofing (vel_ratio low, pos_horiz_ratio high) from raw GPS
        # noise (both ratios spike together).
        evidence: dict = {
            "pos_horiz_ratio": ratio,
            "threshold": self._threshold,
            "sustained_samples": self._consecutive_above,
        }
        for secondary in ("vel_ratio", "pos_vert_ratio", "mag_ratio"):
            v = event.data.get(secondary)
            if v is not None:
                try:
                    evidence[secondary] = float(v)
                except (TypeError, ValueError):
                    pass

        return SecurityEvent(
            source=self._source,
            detector=self.name,
            target_uav=self._target_uav,
            severity=self._severity,
            evidence=evidence,
        )
