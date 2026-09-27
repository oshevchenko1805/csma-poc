# B0 — spoof-rate sweep: pre-registration (review stage 5, 2026-09-27)

Committed BEFORE the first B0 flight. Executable form of every rule:
`metrics/spoof_rate_probe.py` (+ tests), flown by
`scripts/probe_spoof_rate.py` — both committed before the first flight
too. Exploratory characterisation (n = 2 per level), no hypothesis test.

## Question

Is there a spoofing speed at which neither detector of the current
architectures notices the attack while the UAV is still dragged off
course? The local GPS detector (`detectors/gps.py`: `pos_horiz_ratio`
> 1.0 for k = 3 consecutive ESTIMATOR_STATUS samples, ~1 Hz) and the
mesh cross-check (`detectors/cross_check.py`: jump between consecutive
announcements > 25 m/s · dt + 10 m, announcements every 1.0 s) are both
driven by the victim's own data. In v1 and stage 3 the cross-check fired
on the EKF estimate jump (~7.5 s, 50 m in one step), not on the spoof
itself. A slow spoof that the EKF absorbs gradually would produce no
jump and possibly no residual — a blind zone. If it exists, it is the
case that needs an independent measurement (B1, inter-UAV ranging).

## Attack mechanism (fixed, not changed in B0)

PX4 `9fe69d4f33` + local GZBridge patch (tag `OFFSET_INJECT`,
`GZBridge::addGpsNoise`, called from `navSatCallback` for every navsat
message; x500_base navsat `update_rate` = 30 Hz):

    off += SIM_GPS_OFF_R * (SIM_GPS_OFF_N - off)     # per GPS message

A first-order approach to the target, not a linear ramp. With f = 30 Hz,
target A = 50 m north:

- initial spoof speed  v0 = r · f · A  (the maximum; it decays after)
- time constant        tau = -1 / (f · ln(1 - r))

Campaign value r = 0.02: v0 = 30 m/s, tau = 1.65 s.

## Levels

Defined by v0; r = v0 / (f · A). Window W = 180 s from injection
(tau <= 50 s, so every level reaches >= 95 % of 50 m inside W).

| level | v0, m/s | r | tau, s | offset at 180 s |
|---|---|---|---|---|
| L30 (= campaign, control) | 30 | 0.02 | 1.65 | 50 m |
| L10 | 10 | 0.006667 | 5.0 | 50 m |
| L3 | 3 | 0.002 | 16.7 | 50 m |
| L1 | 1 | 0.0006667 | 50.0 | 48.6 m |

Extension, only if L1 is DETECTED: L0.5 (r = 0.0003333, tau = 100 s)
with W = 300 s (47.5 m at 300 s).

## Flight

One UAV (uav_0), campaign route (`configs/experiment.yaml`, 5 m/s),
route repeated so the UAV is cruising for the whole window. Injection
once cruising (ground speed >= 4 m/s), as in the stage-3b pilot. No
response action (detect-only): B0 measures what the detectors see, not
what the response does. SIM_GPS_OFF_R is set BEFORE SIM_GPS_OFF_N. After
landing: OFF_N = 0, OFF_R = 0.02, both read back; per-instance
`parameters*.bson` cleared before the next flight (OFF_R persists
otherwise). Order: L30, L10, L3, L1, then the second flight of each in
the same order.

Logged (pymavlink on the monitor endpoint 14570, plus the Gazebo
recorder): ESTIMATOR_STATUS, GLOBAL_POSITION_INT, LOCAL_POSITION_NED,
GPS_RAW_INT, Gazebo truth. Raw data archived + SHA-256, not in git.

## Detection (offline replay with the campaign classes)

- `gps`: the logged ESTIMATOR_STATUS stream fed to `GpsSpoofingDetector`
  with campaign defaults (threshold 1.0, k = 3).
- `cross_check`: GLOBAL_POSITION_INT sampled every 1.0 s (the monitor's
  announce cadence) fed to `CrossCheckDetector` with campaign defaults
  (25 m/s, 10 m). Equals a lossless mesh; the loss sweep (fig. 4.1)
  covers the rest.

Same classes, same parameters as the campaign; no detector code changes.

## Metrics (t from injection, [0, W])

- `ramp_ok`: GPS_RAW_INT north offset (minus the pre-injection median)
  at t = tau and t = 2·tau within 5 m of the model (31.6 m and 43.2 m).
- `t_gps`, `t_cc`: first alarm of each detector; None if none in W.
- `t_jump`: first t with |belief - truth| > 25 m
  (`metrics.physical_outcomes.JUMP_M`); None if never.
- `max_step_1s_m`: largest increase of |belief - truth| over any 1 s —
  whether the estimate moved in one jump (> 35 m = the cross-check
  budget) or gradually.
- `nav_error_end_m`: median |belief - truth| over the last 10 s of W.
- `harm_at_alarm_m`: |belief - truth| at the first alarm of either
  detector; if no alarm, its maximum over W. How far the UAV had been
  dragged before anyone noticed.

Frames and alignment as `metrics/trust_hold_probe.py` (truth ENU,
belief NED, constant offset removed with the pre-injection median), with
one change made before the first flight: truth is linearly interpolated
to belief timestamps instead of nearest-sample pairing (at 5 m/s the
nearest Gazebo sample can be ~2.5 m off). The GPS ramp is measured the
same way: GPS_RAW_INT north minus interpolated truth north.

## Classification (per flight, then per level)

- `NOT_LANDED`: nav_error_end_m < 25 m — the EKF rejected the spoof;
  harmless, not blind.
- `DETECTED`: landed and gps or cross_check fired in W (which one is
  recorded: gps only / cc only / both).
- `BLIND`: landed and neither fired in W.

A level takes the class both flights agree on; on disagreement a third
flight decides (majority). A flight is invalid (re-flown, never
reinterpreted) only if the injection did not take effect (GPS_RAW_INT
offset < 5 m at t = W) or the script errored; the outcome itself is never
a reason to re-fly.

## Control and ramp check

- L30 must reproduce the campaign: t_jump in [5, 10] s and gps fires
  within 10 s in both flights. Otherwise the setup is wrong: stop, nothing
  is concluded.
- ramp_ok must hold on the first L30 flight. If it fails, f is not
  30 Hz: stop, recompute v0 from the measured ramp and re-register the
  levels before flying further.

## Decision rule

- Some level BLIND -> blind zone exists; v_blind = the highest BLIND v0.
  B1 goes ahead with the BLIND level(s) as its test case.
- All levels DETECTED after the L0.5 extension -> no blind zone in this
  mechanism. Stop B as planned: decide between a velocity-consistent
  spoof (PX4 patch) and describing B as future work (Ch. 5).
- Either way the sweep goes to Ch. 4/5 as the empirical detection
  boundary of the current detectors (P6).

## Predictions (stated, not tested)

- L30, L10: estimate jump, cross_check fires on it; gps fires.
- L1: gradual absorption (max_step_1s_m < 35 m), cross_check silent;
  gps uncertain.

## Stated limits

n = 2 per level; one direction (north), one magnitude (50 m), one route;
lossless mesh in the cross-check replay; detectors re-evaluated offline
with the campaign classes, not live monitors; position-only spoof (GNSS
velocity stays true).

## Results (2026-09-27)

8 flights, 2 per level, all valid, both flights of every level agree.
Order as pre-registered (L30, L10, L3, L1, then the second round).
Raw data: `b0_raw_runs.tar.gz` (VM `~/b0_runs`), SHA-256
`eb2d96ce1eb0b28bd4e8dea6d840f3483bed36cb452a37aecf1851b4569e07e2`,
4 920 194 bytes; copy on the Mac `~/Documents/csma/`. Report:
`python3 scripts/probe_spoof_rate.py --report ~/b0_runs`.

Checks: ramp_ok on every flight (spoof at tau 31.52–31.66 m, model
31.61 m; at 2·tau 43.19–43.27 m, model 43.23 m) -> f = 30 Hz confirmed.
Control L30 reproduces the campaign in both flights (jump 7.28 / 7.29 s,
gps 2.61 / 2.68 s). No alarm before injection in any flight.

| level | v0, m/s | t_gps, s | t_cc, s | max_step_1s, m | t(err > 25 m), s | harm_at_alarm, m | class |
|---|---|---|---|---|---|---|---|
| L30 | 30 | 2.61 / 2.68 | 7.69 / 7.70 | 49.0 / 49.0 | 7.28 / 7.29 | 0.40 / 0.35 | DETECTED (both) |
| L10 | 10 | 3.67 / 3.69 | 7.72 / 7.64 | 39.0 / 39.1 | 7.69 / 7.65 | 0.51 / 0.57 | DETECTED (both) |
| L3 | 3 | 5.67 / 5.69 | — / — | 19.2 / 19.3 | 13.3 / 13.4 | 4.3 / 4.1 | DETECTED (gps only) |
| L1 | 1 | — / — | — / — | 0.99 / 0.99 | 37.1 / 37.3 | 48.4 / 48.5 (max, no alarm) | **BLIND** |

nav_error_end 48.2–50.1 m in every flight (the attack landed at every
level). L0.5 not flown (L1 already BLIND; extension not triggered).

**Decision (pre-registered rule): BLIND ZONE, v_blind = 1 m/s -> B1.**

Observations (descriptive, n = 2):

- The cross-check path exists only through the EKF reset. The size of the
  1 s estimate step matches the spoof offset accumulated by ~7.5 s
  (model at t = 7.28 / 7.65 / 7.5 s: 49.4 / 39.2 / 18.1 m for L30 / L10 / L3; measured 49.0 / 39.1 /
  19.2 m), i.e. consistent with a timeout-driven EKF2 reset to GPS. That
  the reset is timeout-driven is an interpretation, not checked in the PX4
  source. Below ~35 m of accumulated offset (the cross-check budget) the
  mesh path is silent: already at 3 m/s.
- At 1 m/s the EKF accepts the spoof without rejection (estimate moves
  <= 1 m per second with the spoof): no innovation, no jump, no alarm;
  the UAV is taken 48 m off route. The local detector's own boundary lies
  between 1 and 3 m/s (not resolved; intermediate levels were not
  pre-registered).
- Every current detector — local and mesh — is driven by the victim's own
  data, so they fail together. This is the case for an independent
  measurement (B1).

Predictions: L30/L10 as predicted; L1 "cross_check silent" as predicted,
"gps uncertain" resolved as silent.
