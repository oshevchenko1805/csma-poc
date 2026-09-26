# Stage 3b — pilot before H2 (review stage 3, 2026-09-26)

Written BEFORE the first pilot flight. Pilot runs are never part of the
confirmatory H2 data set; they are reported in Ch.4 as a pilot.

## Why a pilot

Stage 2 showed the zero-velocity hold on a HOVERING UAV (0.18 m vs
LOITER 49.8 m, n=1). The campaign flies a mission at 5 m/s, and in the
campaign the OFFBOARD setpoint stream comes from the mission connection
(code 3a-2), not from the probe. Two things are unknown:

1. the braking/hold distance of each action at cruise WITHOUT an attack
   (the reference the H2 magnitude bound must come from — not from the
   old LOITER data);
2. whether the pipeline path works: action requested by the coordinator,
   executed over the borrowed mission connection, OFFBOARD entered and
   held for the whole window (flight_modes, code 3a-3).

## Runs

Part A — reference, no attack (probe, uav_0 only, campaign route):

| # | command | n |
|---|---------|---|
| A1 | `probe_trust_hold.py --mission --offset 0 --action zerovel` | 3 |
| A2 | `probe_trust_hold.py --mission --offset 0 --action loiter`  | 1 |

Part B — full pipeline, architecture C, target uav_0, 90/60 s recipe,
log root `runs_pilot3b` (n=1 per row):

| # | cell | --recovery-policy | checks |
|---|------|-------------------|--------|
| B1 | C/gps_spoofing | trust_aware | action = hold_zero_velocity, ack success, OFFBOARD entered and held to window end |
| B2 | C/monitor_takeout+gps_spoofing | trust_aware | same |
| B3 | C/detector_takeout+gps_spoofing | trust_aware | same (action via cross_check) |
| B4 | C/gps_spoofing | proportionate | control: HOLD in flight_modes, drift ~50 m reproduced |
| B5 | C/gps_spoofing | detect_only | no recovery_request, mission continues |

## What the pilot decides (rules fixed now)

- **Technical go / no-go.** GO if B1–B3 each show the requested action
  acknowledged and OFFBOARD held to the window end, and B4 reproduces
  LOITER drift > 40 m. Otherwise the defect is fixed and the pilot
  repeated; the campaign does not start on a failed pilot.
- **H2 magnitude bound B** = max post_response_drift over the three A1
  runs + 5 m (CAPTURE_RADIUS_M). Not the old 11.1 m LOITER figure.
- **DT equivalence margin** δ = 5 m on the difference of medians
  (trust_aware − proportionate). Tested with TOST only if the pilot
  shows DT drift spread small enough for N to support it; otherwise DT
  is reported as a mechanism check without an equivalence claim.
- **N** from a power calculation using A1/B-run spread and the v1
  campaign LOITER drift distribution; 15 per cell unless the
  calculation says more.
- Pilot drift values are descriptive only (n=1). No hypothesis is
  judged on them.

## Inclusion rule for the campaign (fixed now)

A run is analysed if the injection was technically executed
(SIM_GPS_OFF_N read back = offset). Rejected action, OFFBOARD fallback,
no estimate jump or small drift are OUTCOMES of the policy, never
exclusion reasons. Runs where the response precedes the EKF estimate
jump are additionally analysed as a separate stratum.

## Results — Part A (2026-09-26, flown after this plan was committed, 0359d0b)

| run | action | offset | speed at action | post_response_drift | fallback |
|-----|--------|--------|-----------------|---------------------|----------|
| zerovel_1790440133 | zerovel | 0 | 4.20 m/s | 2.32 m | none |
| zerovel_1790440608 | zerovel | 0 | 4.61 m/s | 2.90 m | none |
| zerovel_1790440769 | zerovel | 0 | 4.50 m/s | 2.91 m | none |
| loiter_1790441027  | loiter  | 0 | 4.21 m/s | 3.99 m | none |

Raw: VM ~/probe_runs/<run>.

- **H2 magnitude bound B = 2.91 + 5 = 7.91 m** (rule above, applied as written).
- OFFBOARD held to window end in all three zero-velocity runs (probe path).
- LOITER brakes only ~1 m longer than zero-velocity hold without attack.
  The v1 DT LOITER drift (median 8.4 m, action after the estimate jump)
  is therefore ~4 m above plain braking: something after the jump (EKF
  reset transient, most likely — not verified) adds drift even when the
  hold point is already in the shifted frame. Consequence, decided BEFORE
  any pipeline pilot run: the earlier prediction "no difference in DT" is
  WITHDRAWN. DT is reported as a mechanism check — difference of medians
  with CI, no directional or equivalence claim.
