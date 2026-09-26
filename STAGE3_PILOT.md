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

## Results — Part B (2026-09-26, pipeline, runs_pilot3b, commit 8d14fb8)

| run | policy | action (acks) | modes after inject | drift | jump | evidence |
|-----|--------|---------------|--------------------|-------|------|----------|
| B1 GPS | trust_aware | hold_zero_velocity ×2 ok | OFFBOARD +3.9 s, held | 9.28 m | 7.58 s | confirmed |
| B2 MT+GPS | trust_aware | hold_zero_velocity ×2 ok | OFFBOARD +4.0 s, held | 1.14 m | 7.45 s | confirmed |
| B3 DT+GPS | trust_aware | hold_zero_velocity ok | OFFBOARD +8.2 s, held | 3.28 m | 7.36 s | confirmed |
| B4 GPS | proportionate | mode_loiter ×2 ok | HOLD +3.9 s | 50.10 m | 7.80 s | confirmed |
| B5 GPS | detect_only | none | no change (MISSION) | — | 7.97 s | confirmed |

**Technical GO** (rule above): B1–B3 acknowledged, OFFBOARD held to window
end; B4 > 40 m; B5 no action.

**B1 decomposition.** Distance from the action point stayed ≤ 1.9 m for
the first 30 s (the estimate jump at +7.6 s and the second request on it
had no visible effect). At +33.1 s uav_2, still flying its own square in
the same 20 m layer, passed at a 3D distance of **0.39 m** (world frame,
uav_0 z 20.35 m, uav_2 z 19.99 m) — a collision in SITL — and uav_0 was
displaced to ~9 m. B2: closest peer 2.5 m, no displacement. The three
squares are 30×30 m, offset only 5/10 m east, so a vehicle that STOPS on
its route lies on its peers' routes.

## Decision after the pilot (2026-09-26, before H2 is fixed)

- The action is NOT changed. B = 7.91 m and the primary metric
  (post_response_drift_m, all causes) are NOT changed. Drift caused by a
  peer collision is an outcome of the policy (ITT rule above); if H2
  misses the bound in a cell because of collisions, that is reported.
- New **secondary, descriptive** swarm-safety metric, all arms, defined
  in metrics/peer_separation.py before the campaign: min 3D separation
  from the target to any peer over [t_inject, t_inject + 60 s], number of
  contacts (< 1.0 m) and near misses (< 3.0 m). Truth (Gazebo world)
  frame. No hypothesis is tested on it.
- Altitude deconfliction (stop + climb out of the formation layer) is a
  separate, later arm — not mixed into H2.

## Correction — contacts are a property of the testbed, not of the policy

metrics.peer_separation over the 60 s BEFORE injection (no response
possible yet): contact (< 1 m) in **13 of 34** clean v1 flights
(runs_campaign/base_pass1-3, A/B/C none; min 0.28 m) and in 3 of 5 pilot
runs; near miss (< 3 m) in 30 of 34. Cause: the three 30×30 m squares
share the 20 m layer and are offset only 5/10 m east, so on the
east-west legs the UAVs fly in line, and any start-time lag closes the
gap. The statement "stopping one vehicle creates a collision hazard for
the swarm" (previous section) is therefore WITHDRAWN as a finding: the
hazard exists without any response. What is specific to a stop is only
the closing speed (a stationary UAV is hit at cruise speed — B1).

## Decision (2026-09-26): vertical separation for the stage-3 campaign

- `mission.altitude_layer_step_m` (default 0.0 = v1 geometry): sysid s
  flies (s−1)·step higher, takeoff and every waypoint. Campaign value
  **5.0 m** → uav_0 20 m (unchanged: attack target, same as v1 and as
  the Part-A reference), uav_1 25 m, uav_2 30 m. Recorded per run in
  run_summary.mission_plan.altitude_layer_step_m.
- All three arms, including the control "current C", fly the new
  geometry: within-campaign comparisons are unaffected. The control arm
  also bridges to v1: if it reproduces v1 C (drift ~50 m, jump ~7.5 s),
  the geometry change does not move the key metrics.
- B = 7.91 m unchanged (Part A flew uav_0 alone at 20 m).
- Part B is re-flown (n=1 per row) with the new geometry before the
  campaign; GO additionally requires no contact (< 1 m) in those runs.
- **OPEN-5** (after the campaign, existing data, no new flights): check
  whether v1 false positives (fp_census, 17 runs) and the 1–2 m baseline
  deviation peaks coincide with peer contacts.
