# H2 — pre-registration (review stage 3c, 2026-09-26)

Committed BEFORE the first campaign run. Executable form of every rule:
`metrics/h2_analysis.py` (+ tests). Pilot and its decisions:
`STAGE3_PILOT.md`. Pilot runs are not part of this data set.

## Hypothesis

**H2.** In architecture C under GPS-position spoofing, a recovery action
that does not rely on the compromised position estimate (zero-velocity
hold, policy `trust_aware`) yields a smaller physical post-response drift
of the attacked UAV than the position hold it replaces (LOITER, policy
`proportionate`), when the action is executed before the EKF estimate
jump.

**H2₀.** No difference in post-response drift.

Scope of the confirmatory test: cells `gps_spoofing` and
`monitor_takeout+gps_spoofing` (response at ~3–4 s, jump at ~7.5 s).
`detector_takeout+gps_spoofing` (response after the jump) is a
mechanism check only — no directional or equivalence claim (prediction
withdrawn in the pilot, see STAGE3_PILOT.md).

## Design

| | |
|---|---|
| Arms (all arch C) | `proportionate` (control = current C), `trust_aware`, `detect_only` |
| Cells | gps_spoofing, monitor_takeout+gps_spoofing, detector_takeout+gps_spoofing |
| N | 15 per arm × cell = 135 runs |
| Order | `--order replicate-major` (arms and cells interleaved) |
| Geometry | `--altitude-layer-step 5` (uav_0 20 m target, uav_1 25 m, uav_2 30 m) |
| Timing | attack at 90 s, 60 s observation, target uav_0 (run_batch defaults) |
| Log root | `runs_stage3` on the VM; raw data archived + SHA-256, not in git |

Campaign command (VM):

    python3 scripts/run_batch.py -n 15 --order replicate-major \
      --altitude-layer-step 5 --log-root ./runs_stage3 --cells \
    "C/gps_spoofing@proportionate,C/gps_spoofing@trust_aware,C/gps_spoofing@detect_only,\
    C/monitor_takeout+gps_spoofing@proportionate,C/monitor_takeout+gps_spoofing@trust_aware,C/monitor_takeout+gps_spoofing@detect_only,\
    C/detector_takeout+gps_spoofing@proportionate,C/detector_takeout+gps_spoofing@trust_aware,C/detector_takeout+gps_spoofing@detect_only"

## Inclusion

A run is analysed iff `attack_evidence.gps_spoofing.injection_confirmed`
is `true` and the run has no `error`. Excluded runs are listed with the
reason. Crashed / timed-out trials are re-run by the batch resume only
if they produced no run_summary (never because of their outcome).
Everything that is an outcome of the policy — rejected or failed action,
OFFBOARD/HOLD fallback, peer contact, no estimate jump, small or large
drift — is NEVER a reason to exclude.

## Primary metric

`drift_itt_m`: max horizontal Gazebo-truth displacement of uav_0 from
its position at the first SUCCESSFUL recovery_ack, over
[t_ack, t_inject + 60 s]. If the arm requests an action and none is
acknowledged successfully: **+∞ (worst rank)**.

## Decision rule (per confirmatory cell)

1. One-sided Mann–Whitney, trust_aware < proportionate, on drift_itt_m.
2. Holm over the 2 confirmatory cells; α = 0.05.
3. Magnitude: median trust_aware drift_itt_m ≤ **B = 7.91 m**
   (max no-attack zero-velocity braking in the pilot, 2.91 m, + 5 m).

Cell accepted iff 2 and 3 hold. **H2 CONFIRMED** = both cells;
**PARTIAL** = one; **NOT CONFIRMED** = none. Reported exactly in these
words, with the numbers.

## Power (resampling; pilot values vs 44 v1 C LOITER drifts)

| N / cell | no action failures | 20 % failures | 30 % failures |
|---|---|---|---|
| 5 | 1.00 | 0.12 | 0.04 |
| 10 | 1.00 | 0.46 | 0.14 |
| 15 | 1.00 | 0.71 | 0.28 |

Power is governed by the action failure rate (worst-rank rule); observed
so far 0/9 (stage 2, pilot A and B). Adding +8 m to 20 % of trust_aware
runs (collision-like events) barely changes power.

## Secondary, descriptive (no hypothesis test)

Per arm × cell, medians / counts with CIs:
- DT cell: difference of medians trust_aware − proportionate, bootstrap
  95 % CI (seed fixed in metrics.stats).
- Action failures, fallback modes (`fallback_mode`), response before /
  after the estimate jump (stratum).
- Navigation error at window end — **predicted ≈ 50 m in every arm**: no
  arm repairs the estimate.
- Waypoints captured / mission execution — **predicted: both hold arms
  stop the mission**; zero-velocity hold is damage limitation, not
  mission recovery.
- detect_only — **predicted: physical outcome like A/B in v1** (mission
  continues on the spoofed estimate, ~50 m off-route); no response.
- Peer separation (metrics/peer_separation.py): min 3D distance,
  contacts (< 1 m), near misses (< 3 m); predicted 0 contacts with the
  5 m layers.
- Bridge to v1: proportionate arm vs v1 C (drift, jump time) —
  predicted to reproduce (drift ≈ 50 m, jump ≈ 7.5 s).

## During the campaign

Allowed: batch manifest status (ok / error / timeout) and disk space.
Not allowed before the batch ends: computing any metric on
runs_stage3. A rule change after launch needs a dated entry below with
the reason; the original rule's result is still reported.

## Stated limitations (go into Ch. 3/4 as written)

- The attack falsifies GPS position only; GNSS velocity stays true. A
  spoofer that falsifies velocity consistently defeats zero-velocity
  hold — by construction of this attack model.
- Zero-velocity hold is containment, not recovery of the mission.
- Geometry differs from v1 (vertical layers); comparisons across
  campaigns go through the proportionate bridge arm only.
- One spoof magnitude (50 m north), one route, 3 UAVs.

## Amendments

(none)
