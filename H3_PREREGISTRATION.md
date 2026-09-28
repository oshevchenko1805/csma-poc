# H3 — pre-registration (review stage 5, step 2; B1: inter-UAV ranging)

Status: 2a + 2b + 2c (2026-09-27). The design, rules and predictions
are fixed here. [2c] changed the attribution rule before any B1 code or
flight (section "Attribution check [2c]"). The [2b] numbers were
computed from data that existed before B1 (the B0 series and the
stage-3 flights) by `scripts/h3_predict_2b.py`, and are frozen **before
any B1 flight**. Once the first B1 flight is
flown, any rule change goes to "Amendments", dated and with a reason,
and the original rule's result is still reported. The executable form of
the rules, `metrics/h3_analysis.py` (+ tests), is committed before the
first flight.

Basis: DATA_DEPENDENCY_GRAPH.md (sections 2 and 5, P-B1-1…8),
B0_PREREGISTRATION.md "Results" (blind zone at 1 m/s), H2_PREREGISTRATION.md.

## Hypothesis

**H3.** In architecture C, a detector that compares inter-UAV ranges
with the ranges implied by the mesh announcements raises an alarm
against the victim of a 1 m/s position-only GNSS spoof. This is the B0
blind zone, where every v1 detector stays silent. The victim's
navigation error at the first alarm is ≤ H_max.

**H3₀.** No alarm against the victim within the window, or an alarm
only after the navigation error has exceeded H_max.

H3 is tested within C: the same flights carry the v1 detectors (the
paired control: C without ranging) and the ranging detector.

### What H3 can and cannot show (stated before the data)

In SITL, the live ranges and announcements carry almost no GNSS noise.
Under those conditions, detection at 1 m/s is expected once the
navigation error grows, so the fact of detection alone is close to
"true by construction", as H1 was. The substantive content of B1 is:

1. **H_max:** how much harm occurs before the alarm;
2. **attribution:** the alarm names the victim, not an honest peer;
3. **no false alarms** in flights without an attack;
4. **P-B1-2:** at fast spoofs ranging does **not** fire before the EKF
   reset, a prediction that can fail;
5. **the offline noise map** (section "Offline coverage map"), which
   decides where the detector stops working.

Chapter 4 reports H3 in this order and does not present the bare
detection as a finding.

## Detector (defined here, implemented after this file is committed)

`detectors/ranging.py`, class `RangingConsistencyDetector`. It is a mesh
consumer like `CrossCheckDetector`, instantiated in every C monitor when
the config lists `ranging`. It is enabled by config only: a new file
`configs/architecture_c_ranging.yaml`, and v1 configs are untouched.
There is no architecture branch.

Per monitor i, on each announcement of peer j (1 Hz, the existing
cadence; **no new mesh messages**):

    rho_ij(t) = | p̂_j(t) - p̂_i(t) |  -  r_ij(t)          (3D, metres)

- p̂_j(t): the announced position of j (EKF_pos of j, GLOBAL_POSITION_INT).
- p̂_i(t): i's own EKF position, interpolated to the announcement's
  sample_timestamp.
- r_ij(t): the range measured by i, sampled at the same timestamp.
- **bad_ij**: |rho_ij| > theta for k = 3 consecutive announcements. This
  mirrors the gps detector's k = 3 at 1 Hz; hysteresis is as in
  cross_check.

Attribution (the residual is symmetric: it cannot say which end is
wrong). [2c; changed before any B1 code or flight, reason below.]

- **fine_ik**: |rho_ik| ≤ theta_ok for k = 3 consecutive announcements,
  theta_ok = 1.3 m. "Fine" is positive evidence of consistency, not the
  mere absence of a sustained alarm.
- bad_ij, and fine_ik for some other peer k: flag **j**.
- bad_ij for **every** peer (≥ 2 peers): flag **i itself** (self-check:
  "my own position is inconsistent with everyone").
- **Latch:** once monitor i has flagged itself, it flags no peer for the
  rest of the flight. Its own position p̂_i is then known to be tainted,
  and every peer judgement it could make is computed from p̂_i. The self
  flag itself keeps the hysteresis above.
- Only one peer is heard and bad_ij: no flag (ambiguous; with 3 UAVs
  this happens only if a peer is silent).
- (2a rule, replaced: flag j if bad_ij and **not** bad_ik; no latch.)

With 3 UAVs and victim uav_0, the predicted pattern is: uav_1 and uav_2
flag uav_0 (the peer path, running outside the victim's failure domain),
and uav_0 flags itself (the self path, running in the victim's domain).
**3 is the minimum group size for attribution**, which is stated as a
limit.

### Attribution check [2c] (before any B1 code or flight)

Step 2b modelled the peers' view of the victim and the victim's self
path, but not what the victim's **own** monitor concludes about its
peers. Its p̂_i is the victim's EKF position (tainted). With the 5 m
layers, uav_1 is ~5 m and uav_2 ~10 m above the victim, so the pair
0–1 crosses theta ~1 s before the pair 0–2. In between, the victim's
monitor sees "bad with uav_1, not bad with uav_2", and the 2a rule flags
uav_1. Later in the lap, when the victim's error is perpendicular to the
line of sight to uav_2, the pair 0–2 is genuinely consistent again; no
threshold can resolve that from two residuals.

`scripts/h3_predict_2c.py` re-runs the 2b model (same data, geometries,
B0 e(t), theta and peer-path seed keys) for all three monitors.
Misattributions by the victim's monitor (misattributions by the peers'
monitors are 0/5200 in every rule; no-attack flags are 0 in every rule):

| rule for "fine" | L1 | L3 | L1 harm ≤ H_max |
|---|---|---|---|
| 2a: not bad | 5196/5200 | 4983/5200 | 5200/5200 |
| 3× ≤ theta | 1367 | 363 | 5200 |
| 3× ≤ 1.3 m | 816 (at 28 s) | 34 | 5200 |
| 3× ≤ 0.9 m | 354 (at 28 s) | 0 | 5193 |
| 2a + latch | 4274 | 4963 | 5200 |
| 3× ≤ theta + latch | 1 | 362 | 5200 |
| **3× ≤ 1.3 m + latch** | **0** | **34** | **5200** |
| 3× ≤ 0.9 m + latch | 0 | 0 | 5193 (max 9.1 m) |

L30 and L10: 0 misattributions in every rule except "not bad" (10, 11).

Chosen: **theta_ok = 1.3 m + latch.** theta_ok is the calibration
maximum of sustained honest |rho| (1.24 m, section "Threshold")
rounded up to 0.1 m, i.e. theta without the 0.5 m margin, so it comes
from the calibration rule rather than a free choice. The confirmatory
cell L1 is clean in the model. The cost is a predicted misattribution by
the victim's monitor at L3 in 0.65 % of model runs, before its self
flag. θ/2 = 0.9 m was rejected: no derivation, and harm > H_max in 7/5200
L1 runs.

This rule was chosen on the same model that produces the predictions;
the flights are the test. The model also assumes that all monitors
receive announcements on the same whole-second ticks; live phases
differ by up to 1 s.

SecurityEvent detector `ranging` -> reason `ranging_anomaly`, which is
added to every policy table:

| policy | action for ranging_anomaly |
|---|---|
| proportionate | mode_loiter |
| trust_aware | hold_zero_velocity |
| detect_only | none |

v1 never emits this reason, so v1 behaviour is unchanged. Detector
takeout also silences the ranging instance on the target's monitor
(self path), because it counts as node-local detection. Peers' instances
are untouched.

### Range source (live)

`r_ij = |x_i - x_j|_truth + b_ij + n + nlos`, from Gazebo truth (the same
feed as TrajectoryRecorder), interpolated to the sample timestamp.

- n ~ N(0, 0.1²) m;
- b_ij = 0.2 m, fixed per pair per flight;
- nlos: with probability p_nlos, an Exp(mean m_nlos) positive excess,
  with p_nlos = 0.05 and m_nlos = 0.5 m.
  [2b] Checked against DW1000 measurements: 0 ± 5 cm in LOS, so sigma
  = 0.1 m is 2x conservative; a 44–60 cm positive bias behind a concrete
  wall or with human-body shadowing (Flueratoru et al., IEEE IoT J. 2022,
  "High-Accuracy Ranging and Localization With Ultrawideband
  Communications for Energy-Constrained Devices"; full reference to be
  verified, P3). m_nlos = 0.5 m matches. **p_nlos has no source and
  stays an assumption.** It enters the false-alarm control through
  theta, not the claim;
- the seed is fixed per flight and logged.

The attacker does not control r (adversary model).

### Threshold theta (calibrated on no-attack data, before the flights)

Calibration set [2b; changed from v1 before any flight]: the **stage-3
flights** (runs_stage3, archive stage3_raw.tar.gz, SHA-256 in
runs_campaign/stage3_raw.sha256), pre-injection window [-45, -1] s.
No attack is active there, the 3 UAVs fly with the 5 m altitude layers
of B1, and per-UAV truth and belief (LOCAL_POSITION_NED) are logged. v1
is not used: it flew without layers, a different geometry. Stage 3 had
0 peer contacts.

Data-quality gate (no interpolation across gaps): every UAV needs a
truth and a belief sample within 0.5 s of ≥ 90 % of the 1 Hz ticks.
Frame alignment per UAV is median(truth − belief) over the same window,
as in B0. This removes any constant error and makes theta slightly
optimistic.

For every flight, ordered pair and cruise second, over 20 seeded
range-noise realisations:

    s(t) = min(|rho(t)|, |rho(t-1)|, |rho(t-2)|)
    theta = max s(t), rounded up to 0.1 m, + 0.5 m

**[2b] theta = 1.8 m**, from 130 of 131 runs. **[2c] theta_ok = 1.3 m**
(the max sustained |rho| below, rounded up to 0.1 m, without the
margin). One run is gated (DT/trust_aware r1: sparse truth and
belief). The max sustained |rho| is 1.24 m, of which navigation alone
is ≤ 0.47 m. By construction there are zero false alarms on the
calibration set; false alarms are tested on the held-out B1 no-attack
flights.

**H_max = theta + 5 m = 6.8 m** (same form as the H2 bound: calibrated
level + 5 m allowance for geometry and sustain).

The max rule is driven by rare runs of 3 consecutive NLOS excesses, so
it depends on the noise seeds. A first scratch run with different seed
keys gave 1.6 m. The value above, from the committed script and its seed
keys, is the frozen one. The predictions barely change between 1.6 and
1.8 m.

## Attack

The pipeline `gps_spoofing` attack gets an optional spoof rate
(SIM_GPS_OFF_R, written before SIM_GPS_OFF_N; both read back and
restored: OFF_N = 0, OFF_R = 0.02). The default None leaves v1
untouched. Levels are as in B0 (v0 = r·f·A, f = 30 Hz, A = 50 m north):

| level | v0, m/s | r |
|---|---|---|
| L30 | 30 | 0.02 |
| L10 | 10 | 0.006667 |
| L3 | 3 | 0.002 |
| L1 | 1 | 0.0006667 |

## Design (all architecture C with ranging, 3 UAVs flying the mission, victim uav_0)

Geometry and timing: `--altitude-layer-step 5` (as H2), attack at 90 s,
**observation 120 s** (L1 offset at 120 s ≈ 45.5 m), per-instance
`parameters*.bson` cleared between flights.

| series | cells | n | purpose |
|---|---|---|---|
| S1 detection | L1 @detect_only | 5 | H3 (confirmatory) |
| | L3, L10, L30 @detect_only | 2 each | P-B1-2, map anchors |
| | no-attack @detect_only | 3 | control: false alarms, held-out |
| S2 detector takeout | DT + L1 @detect_only | 2 | P-B1-3: peer path alone |
| S3 action | L1 @proportionate, L1 @trust_aware | 2 each | P-B1-8: action after a ranging alarm |

20 flights in total. Order: the no-attack flights first and last,
attack cells interleaved (replicate-major). The v1 detectors (gps,
cross_check) run in every flight: this is the paired control.

## Inclusion

A flight is analysed iff the injection took effect (GPS_RAW_INT offset
≥ 5 m at the end of the window) and the run has no error. Excluded
flights are listed with the reason and re-flown. An outcome (an alarm or
no alarm, a misattribution, a contact, an action failure) is **never** a
reason to exclude.

## Metrics (t from injection; B0 definitions and alignment reused)

- `t_rng_peer`, `t_rng_self`, `t_rng` = min of the two: first ranging
  alarm against uav_0; None if none in W.
- `t_gps`, `t_cc`: v1 detectors, same flight.
- `harm_at_alarm_m`: |belief − truth| of uav_0 at t_rng (B0 definition).
- `t_jump`, `max_step_1s_m`, `nav_error_end_m`: as in B0.
- `misattributions`: ranging alarms naming uav_1 or uav_2 in attack
  flights.
- `false_alarms`: any ranging alarm in no-attack flights.
- S3: `drift_itt_m` (H2 definition). `creep_mps` = median truth
  horizontal speed of uav_0 over [t_ack + 5 s, end]. `vel_err_mps` =
  |EKF velocity − truth velocity|, from LOCAL_POSITION_NED vx, vy.
  [Implementation, before any flight: the pipeline monitors already log
  the full LOCAL_POSITION_NED message, vx and vy included (checked in
  the stage-3 raw data); only the B0 probe script dropped them. No
  change needed; a regression test guards it.]

## Decision rule

L1 flight **passes** iff: ranging alarm against uav_0 within W, and
harm_at_alarm_m ≤ H_max, and no misattribution.

- **H3 CONFIRMED**: 5/5 L1 flights pass, 0 false alarms in the 3
  no-attack flights, and the v1 detectors are silent at L1 (blind zone
  reproduced with 3 UAVs).
- **PARTIAL**: 3–4/5 pass, or 5/5 detect but some harm > H_max; the
  false-alarm condition still holds.
- **NOT CONFIRMED**: otherwise, or any false alarm in no-attack flights.
- If the v1 detectors fire at L1, the blind zone is not reproduced in
  the 3-UAV setting. This is reported as such, and H3 is reported as
  "not applicable", not as confirmed.

Report k/5 with the Wilson 95 % CI and every per-flight value. This is
a boundary demonstration, not a frequency estimate: generalisation comes
from the offline map.

## Predictions ([2b] numbers frozen)

Model (`scripts/h3_predict_2b.py`): the B0 nav-error vectors e(t), 2
flights per level, are placed on the clean stage-3 geometry one lap
(36 s) before injection: 130 geometries × 20 noise seeds. The victim's
announced position stays on the route; its true position is route −
e(t); peers are as flown.

Assumptions:
- e(t) of a single UAV (B0) carries over to the 3-UAV mission;
- announcements fall on whole seconds after injection (the live phase is
  random, ±1 s).

Geometry at the injection phase: the peers are almost **above** the
victim (horizontal 1–4 m, vertical 5 / 10 m). A horizontal divergence
therefore changes the range only to second order until the formation
opens up. The spoof direction hardly matters: rotating e(t) to east
gives the same median (5.8 m).

- **L1:** v1 silent. Peers flag uav_0 at **t_rng_peer = 9 s** (p5–p95
  8–9, range 7–10), with **harm_at_alarm = 5.8 m** (p5–p95 5.1–5.9,
  max 6.6). This is ≤ H_max = 6.8 m in 5200/5200 model runs, with a
  margin of ~1 m. uav_0 flags itself at 10 s (9–11). 0 misattributions.
  **[2c, supersedes the line above; attribution rule with theta_ok and
  latch, all three monitors]:** t_rng_peer = 9 s (p5–p95 8–10, range
  7–10); harm_at_alarm = 5.9 m (p5–p95 5.1–6.6, max 6.6), ≤ H_max in
  5200/5200, worst-case margin **0.2 m**; t_rng_self = 10 s (p5–p95
  9–10, range 8–11); 0 misattributions on every monitor.
- **L30, L10 (P-B1-2):** t_rng = t_jump + 2…3 s (model: 10 s; t_jump
  7.3 / 7.7 s; 0/5200 alarms before t_jump − 0.5 s; [2c] rule: range
  9–13 s, 0 misattributions). gps fires first
  (2.6 / 3.7 s). **Falsified** if t_rng < t_jump − 0.5 s in any flight.
  harm_at_alarm by the B0 definition is ≈ the jump (49 / 41 m). That is
  estimate error, not physical displacement at that moment, so it is not
  the outcome metric for these levels.
- **L3:** ranging fires **before** the jump in 98 % (5095/5200): t = 8 s
  (p5–p95 8–10), harm 3.7 m (3.6–3.9); the rest fire at the jump. Local
  gps fires earlier (B0: 5.7 s), so at L3 ranging adds value only when
  local detection is taken out.
  [2c] With the chosen rule: t_rng_peer 8 s (p5–p95 8–11), harm 3.7 m;
  the victim's monitor flags uav_1 or uav_2 at 6–7 s in 34/5200 model
  runs (0.65 %), before its self flag. Peers' monitors: 0.
- **DT + L1 (P-B1-3):** the peer path alone detects: t ≈ 9 s, harm ≈
  5.8 m, as at L1. The self path is silent (taken out).
- **No-attack:** 0 ranging alarms.
- **S3 (P-B1-8):**
  - proportionate (LOITER): drift ≈ |e|(120 s) − |e|(t_alarm) ≈ 45.2 −
    5.8 ≈ **39 m** (B0 L1: |e| is 34.3 m at 60 s and 45.2 m at 120 s);
  - trust_aware: drift ≤ 7.91 m (the H2 bound) and creep_mps ≪ 1 m/s,
    **if** EKF velocity stays close to the true velocity during slow
    absorption. vel_err_mps decides this. If creep ≥ 0.5 m/s, the
    zero-velocity hold is not independent of a slow spoof, and this is
    reported as a limit of H2.
- nav_error_end ≈ offset(W) in every flight: no arm repairs navigation.

## Offline coverage map (step 4; rules fixed here)

Input: the S1 flights (truth and belief of all 3 UAVs). Same detector
class, replayed offline.

- **GNSS noise added to every announcement:** first-order Gauss–Markov
  horizontal error per UAV, σ ∈ {0, 0.5, 1.5, 3} m, τ = 60 s (an
  assumption, stated).
- **Range model as live:** bias b ∈ {0, 0.2, 0.4} m, plus n and nlos.
- 50 seeds per (flight, σ, b); calibration seeds are disjoint from
  evaluation seeds.
- **theta(σ, b)** by the same calibration rule, with the same noise
  added to the calibration set.
- **Outputs per (v0, σ, b):** P(peer-path detection within W), median
  t_rng, median harm_at_alarm, false alarms per flight-hour (no-attack).
- **Predictions:** harm_at_alarm is roughly flat in v0 for v0 ≤ 3 m/s
  and grows with theta(σ). The boundary is a displacement (≈ theta), not
  a speed. At fast spoofs the alarm stays tied to t_jump.
- **Limit:** the noise is added to post-EKF announcements, not passed
  through the peers' EKF.

## During the flights

Allowed: batch status, the injection check, disk space. **Not allowed
before S1–S3 are complete:** computing any metric on the B1 flights
(except theta if the fallback calibration is used, frozen before the
attack flights).

## Stated limitations (go into Ch. 3/4/5 as written)

- Position-only GNSS spoof of a single victim; the attacker does not
  control ranging. Rigid whole-swarm spoofing is invisible to any
  relative detector (Park & Yoo, Ch. 5).
- Ranges are simulated (Gazebo truth + UWB model), not radio.
- The peer path depends on the victim's announcements. If the victim's
  own monitor is taken out, ranging is blind like cross_check (P-B1-4,
  not flown).
- 3 UAVs = the minimum for attribution. One spoof direction (north),
  one magnitude (50 m), one route.
- The victim's own monitor judges its peers from its own tainted
  position. Before its self flag, a victim/peer ambiguity remains; the
  [2c] rule reduces it (predicted 0.65 % at L3, 0 at L1) but does not
  remove it. After the self flag, the latch removes it.
- SITL GNSS noise ≈ 0 live; noise enters only in the offline map.

## Implementation (after this file is committed; additive, defaults = v1, tests for each)

1. `detectors/ranging.py`: detector + attribution (pure functions),
   [2c] rule: theta_ok and latch.
2. Range source seam (`RangeSource`) + simulated UWB source from the
   Gazebo truth feed.
3. `configs/architecture_c_ranging.yaml`.
4. `ranging_anomaly` in the isolation and recovery tables (all three
   policies).
5. `gps_spoofing`: optional rate + restore of OFF_R.
6. Detector takeout also silences the target's ranging instance.
7. EKF velocity (vx, vy) logging. [Already logged by the pipeline;
   guarded by tests/test_ekf_velocity_logged.py.]
8. `metrics/h3_analysis.py`: calibration, metrics and decision as code.
   [Implementation, before any flight. Where the text above left a
   choice open, the code fixes it as follows (tests/test_h3_analysis.py):
   - t0 = attack_evidence.gps_spoofing.t_target_set (the OFF_N write),
     not the runner's attack_fired_wall, which precedes it by the OFF_R
     round trips, nor the inject_start marker, which the runner logs
     after fire() returns, i.e. just after t0 (inject_lag_s = t0 -
     inject_start <= 0). No-attack flights use the marker.
     [Wording corrected before any flight, 2026-09-27: the first
     version said the marker precedes t0; the code is unchanged.]
   - Inclusion also requires t_target_set present and rate_confirmed
     True (OFF_R read back = requested rate). Both are setup checks, not
     outcomes; otherwise the flight's level is unknown. Every flight
     (attack or not) also needs the Gazebo truth feed (trajectory_stats
     samples_written > 0, uav_0's track not empty): without it the range
     source returns nothing, ranging stays silent by construction, and
     harm is unmeasurable.
   - misattributions: ranging alarms naming uav_1/uav_2 in [0, W].
     Ranging alarms before t0 in attack flights are reported separately
     and do not enter the decision; false_alarms = every ranging alarm
     of a no-attack flight, whole flight.
   - An alarm with no navigation sample within +-0.25 s (harm unknown)
     counts as a failed L1 flight, not an exclusion.
   - vel_err_mps: same interval as creep_mps ([t_ack + 5 s, t0 + W]);
     truth velocity = 1 s central difference of the Gazebo track.
     drift_itt_m window ends at t0 + W (W = 120 s).
   - Order of the verdict: INVALID CONFIG (architecture != C, no
     range_source seed in run_summary, or ranging events carrying
     constants other than theta 1.8 / theta_ok 1.3 / k 3) > INCOMPLETE
     (included L1 != 5 or no-attack != 3) > NOT APPLICABLE (any gps or
     cross_check alarm against uav_0 in [0, W] of an included L1 flight)
     > NOT CONFIRMED on any false alarm > the k/5 rule.
   - P-B1-2 is UNDETERMINED if an L10/L30 flight lacks t_rng or t_jump.
   - `python3 -m metrics.h3_analysis <root>` prints only the batch
     status (counts, exclusions); `--final` computes the metrics.]
9. `run_batch`: spoof-rate option, cells for the C-ranging config.
   [Implementation, before any flight: `run_one --arch c_ranging
   --spoof-rate r --range-seed s` (seed default: crc32 of the run id,
   logged as run_summary.range_source); `run_batch --preset h3` fixes
   the 20 flights, attack at 90 s, layers 5 m and an observation of
   125 s: the analysis window W = 120 s starts at t_target_set, just
   before the inject_start marker, and inject_end = inject_start + 125 s,
   so W always ends inside the observation (5 s margin kept; wording
   corrected before any flight, 2026-09-27).
   Order: no-attack flights 1st, 10th and 20th; attack cells
   replicate-major, generalised to unequal n (replicate r of n at
   (r - 0.5)/n), so the 5 L1 flights spread over the batch. Every
   flight has its own replicate number; a re-flown excluded flight gets
   the next free number of its cell.]

10. Ranging health counters and one technical flight (written
    before any B1 flight, 2026-09-27).
    [Counters (d54a2ca): RangingConsistencyDetector.stats and
    Monitor.stats `ranging_evaluated`, `ranging_no_own_position`,
    `ranging_no_range` (per peer announcement; the two skip counters are
    independent). Setup diagnostics, not outcomes.
    Technical flight: exactly one, L30, before the series, in its own
    root, so it can never enter the H3 analysis (which reads runs_h3):
      python3 scripts/run_batch.py
        --cells C_RANGING/gps_spoofing:L30@detect_only -n 1
        --attack-at-sec 90 --observation-after-attack-sec 125
        --altitude-layer-step 5 --log-root runs_h3_smoke
    Read ONLY these setup fields (run_summary and the attack phase
    markers), with a script that prints nothing else:
      - error is null; range_source present with a seed;
      - attack_evidence.gps_spoofing: t_target_set present,
        rate_confirmed True, spoof_rate = 0.02;
      - trajectory_stats: samples_written > 0, on_sample_errors = 0,
        uav_0's truth track not empty (row count only);
      - every monitor (3): ranging_evaluated > 0,
        ranging_evaluated / (evaluated + no_own_position + no_range)
        >= 0.95, handler_errors = 0;
      - window_short_s = 0 (t_target_set + 120 s <= inject_end).
    NOT read before S1-S3 are complete: security events of any detector,
    alarm times, targets, residuals, harm, the GPS offset series, the
    trajectory itself. The flight's data never enter theta, the
    predictions or the decision; its raw run goes into an archive with
    SHA-256, unread.
    PASS on every field -> `run_batch --preset h3 --log-root runs_h3`.
    FAIL -> fix the setup (additive code, tests), re-fly in the same
    root with -n 2 (resume skips r1), same fields, same criteria.
    This is the first B1 flight: from it on, every change to this file
    (a rule, or a setup fix that leaves the rules unchanged) goes into
    Amendments with a date.]

## Amendments

**A1 (2026-09-28): offline coverage map, implementation choices.**
Written after the H3 results, before any map code exists and before any
map number is computed. The rules of "Offline coverage map" are
unchanged; this entry fixes what they leave open, plus one input they
assume that is not in the raw data.

Reason: the mesh announcements (GLOBAL_POSITION_INT) are published but
not logged. The monitors log GPS_RAW_INT, LOCAL_POSITION_NED and
ESTIMATOR_STATUS only (checked on runs_h3), so the replay has to
rebuild the announcements.

1. **Input.** S1 flights only, as written (14: L1 x 5, L3 / L10 / L30 x 2,
   no-attack x 3). S2 and S3 are not used. The B0 flights are not an
   input of the map (they fed only [2b]). Calibration set: stage-3,
   as in [2b]. SHA-256 of all three archives checked on 2026-09-28.
2. **Announcements.** Rebuilt from each UAV's LOCAL_POSITION_NED (the
   same EKF as GLOBAL_POSITION_INT), 3D, placed in the Gazebo world
   frame by a per-UAV offset median(truth - belief) over [t0 - 45,
   t0 - 1] s. The offset is computed on the logged belief **before** any
   noise is added, so it cannot absorb the GNSS noise. Instants: 1 Hz
   per UAV, with a phase phi_u ~ U[0, 1) s per (flight, seed, UAV).
   Own position p_i = i's aligned belief at the announcement instant.
3. **GNSS noise.** Per UAV, independent north and east first-order
   Gauss-Markov processes, stationary sigma **per axis** (horizontal
   RMS = sigma * sqrt 2), tau = 60 s, started from the stationary
   distribution, on a 0.1 s grid (linear interpolation between grid
   points). No vertical noise. One UAV's error is added both to its
   announcements and to its own position as used by its own monitor
   (one EKF produces both).
4. **Ranges.** As live: r_ij = |x_i - x_j|_truth + b + n + nlos, with
   n ~ N(0, 0.1^2), p_nlos 0.05, m_nlos 0.5 m. b in {0, 0.2, 0.4} m, the
   same for every ordered pair; n and nlos drawn per ordered pair. Truth
   is interpolated, never across a gap > 0.5 s.
5. **Calibration of theta(sigma, b), theta_ok(sigma, b).** Stage-3,
   window, data-quality gate, alignment and the max rule exactly as
   [2b] / [2c]: theta = max sustained |rho| rounded up to 0.1 m + 0.5 m;
   theta_ok = the same without the 0.5 m. The noise from items 3 and 4
   is added after alignment. 50 seeds per flight, seed keys "map-cal|...";
   evaluation keys are "map-eval|..." (disjoint). The (0, 0.2) cell uses
   its recalibrated theta like every other cell; that value is reported
   next to the live 1.8 m (it can differ: 50 seeds instead of 20).
6. **Replay.** RangingConsistencyDetector unchanged, one per monitor,
   constants theta(sigma, b), theta_ok(sigma, b), k = 3. t0 =
   t_target_set (no-attack: the inject_start marker), W = 120 s.
   Per (flight, seed): t_rng_peer, t_rng_self, t_rng, misattributions;
   harm_at_alarm_m at t_rng by the B0 definition on the **logged** belief
   (the spoof-induced error; the offline GNSS noise is not passed through
   an EKF and exists without an attack, so it is not part of harm).
7. **Outputs per (v0, sigma, b)**, pooled over flights x seeds of a level:
   share of peer-path detection within W (with the flight count, not a
   CI: seeds are not independent flights); median and p5-p95 of t_rng and
   harm_at_alarm; misattributions (reported, not a map output).
   False alarms: no-attack flights, window [t0 - 45, t0 + 120] s, every
   ranging alarm, per flight-hour of replay (3 flights x 50 seeds x
   165 s = 6.9 h per cell); if 0, the rule-of-three upper bound is
   given as well.
8. **Replay check, read before any map cell.** sigma = 0, b = 0.2 m,
   live constants (theta 1.8, theta_ok 1.3). PASS iff (a) 0 ranging
   alarms in the no-attack flights, and (b) in every attack flight of
   S1, peer-path detection in >= 95 % of seeds and a median t_rng_peer
   within +-1.5 s of the live value (live announcement phase up to 1 s,
   plus the k = 3 granularity). FAIL: the replay does not represent the
   live detector; this is reported and no map is produced.
9. **The map predictions, operationalised now.** The wording stays; the
   tests are:
   - M1 "harm roughly flat in v0 for v0 <= 3 m/s": median harm(L3) /
     median harm(L1) in [0.8, 1.25] at every (sigma, b). **Expected not
     to hold at sigma = 0**, stated before computing: the frozen [2b]
     numbers (5.9 vs 3.7 m) and the live flights (5.45 vs 3.8 m) already
     differ by more. The wording was inconsistent with [2b] when written.
     Reported as it comes.
   - M2 "grows with theta(sigma)": for L1 and for L3, at every b,
     median harm is non-decreasing in sigma (tolerance 0.1 m).
   - "The boundary is a displacement (~ theta), not a speed" is M1 and M2
     together and is not tested on its own. Taken literally, "~ theta" is
     also contradicted by [2b] (harm 5.9 m vs theta 1.8 m; H_max = theta
     + 5 m exists for that reason).
   - M3 "at fast spoofs the alarm stays tied to t_jump": at L10 and L30,
     for every (sigma, b), 0 (flight, seed) with t_rng < t_jump - 0.5 s
     (the P-B1-2 rule), and t_rng - t_jump in [-0.5, +4] s in >= 95 %.
10. **Limits added** (Ch. 4): the announcements are rebuilt from
    LOCAL_POSITION_NED; the v0 axis has 4 points, three of them from
    2 flights; one b for all pairs; the noise does not pass through the
    EKF (as stated).

## Results

Flights 2026-09-27/28, code at 52e3d97 (VM). Amendments: none (two
wording corrections were made before any flight, marked in place).
Raw data (not in git): h3_raw.tar.gz SHA-256
a1746b37b5867b5e55f284e18d74611a88eb0c38e7dd5e65c2ef31f66d2483aa;
technical flight h3_smoke_raw.tar.gz SHA-256
647c6bcaff88b57d3c6f7278123d7c07685b21877275c661eee7b3dd4fc5d65d
(item 10: PASS on every setup field; its alarms were not read).
`python3 -m metrics.h3_analysis runs_h3 --final` (rows in
runs_h3/h3_rows.json); re-run on the Mac copy of the archive gives the
same verdict.

Status: 20/20 included, 0 excluded, 0 unplanned, 0 config problems,
0 duplicate seeds. 0 contacts (min peer separation 4.8-5.6 m).

**H3: CONFIRMED.** L1 5/5 pass, Wilson 95 % [0.57, 1.00]; 0 ranging
alarms in the 3 no-attack flights; gps and cross_check silent in all 5
L1 flights (blind zone reproduced with 3 UAVs); 0 ranging alarms before
injection.

Per flight (t in s from t_target_set; harm = harm_at_alarm_m):

| cell | r | t_rng_peer | t_rng_self | harm | t_gps | t_cc | t_jump | t_action | misattr. |
|---|---|---|---|---|---|---|---|---|---|
| L1 | 1 | 8.43 | 9.49 | 5.45 | - | - | 37.01 | - | 0 |
| L1 | 2 | 7.55 | 8.60 | 4.64 | - | - | 37.22 | - | 0 |
| L1 | 3 | 9.58 | 9.59 | 6.41 | - | - | 37.02 | - | 0 |
| L1 | 4 | 7.20 | 8.25 | 4.49 | - | - | 37.01 | - | 0 |
| L1 | 5 | 9.54 | 9.60 | 6.37 | - | - | 37.06 | - | 0 |
| L3 | 1 | 6.48 | 8.49 | 3.87 | 6.18 | - | 13.21 | - | 1 (uav_0 -> uav_1, 6.47) |
| L3 | 2 | 7.62 | 8.72 | 3.71 | 6.20 | - | 13.36 | - | 0 |
| L10 | 1 | 7.65 | 7.70 | 35.12 | 3.13 | - | 4.77 | - | 0 |
| L10 | 2 | 7.43 | 10.50 | 34.61 | 2.94 | - | 4.62 | - | 0 |
| L30 | 1 | 9.56 | 9.60 | 49.32 | 2.94 | 7.56 | 7.33 | - | 0 |
| L30 | 2 | 7.40 | 7.44 | 48.34 | 2.76 | 5.39 | 5.28 | - | 0 |
| DT+L1 | 1 | 8.52 | - | 5.66 | - | - | 37.18 | - | 0 |
| DT+L1 | 2 | 7.33 | - | 4.43 | - | - | 37.05 | - | 0 |
| L1@proportionate | 1 | 7.51 | 8.55 | 4.72 | - | - | 37.01 | 8.55 | 0 |
| L1@proportionate | 2 | 9.63 | 10.66 | 6.44 | - | - | 37.07 | 9.66 | 0 |
| L1@trust_aware | 1 | 9.52 | 9.57 | 6.38 | - | - | 36.96 | 9.55 | 0 |
| L1@trust_aware | 2 | 9.53 | 9.53 | 6.40 | - | - | 37.00 | 9.57 | 0 |
| no-attack | 1-3 | - | - | - | - | - | - | - | 0 alarms |

Against the predictions:
- L1 ([2c]): t_rng_peer median 8.43 s (predicted 9, p5-p95 8-10, range
  7-10); harm median 5.45 m, max 6.41 m (predicted 5.9, p5-p95 5.1-6.6,
  max 6.6); worst margin to H_max 0.39 m (model 0.2 m); t_rng_self
  8.25-9.60 s (predicted 9-10, range 8-11); 0 misattributions. Ranging
  alarms ~28 s before the estimate error crosses the jump threshold.
- P-B1-2 (L10, L30): **HOLDS**. t_rng - t_jump = +2.88, +2.82, +2.23,
  +2.12 s (predicted +2...3 s; falsified only if < -0.5 s). gps first
  (2.76-3.13 s; predicted 2.6 / 3.7 s); harm ~ the jump (34.6-49.3 m;
  predicted 41 / 49 m).
- L3: ranging 6.48 / 7.62 s before the jump (13.2 / 13.4 s), harm 3.87 /
  3.71 m (predicted 8 s, 3.7 m). gps at 6.18 / 6.20 s, i.e. at the same
  time or earlier (predicted: local gps first at L3). One misattribution
  by the victim's own monitor (uav_1 at 6.47 s, before its self flag at
  8.49 s); the peers' monitors flagged uav_0 at 6.48 s. This is the
  stated [2c] limit (model 34/5200 runs, 6-7 s); 1 of 2 flights here, a
  frequency cannot be read from n = 2.
- P-B1-3 (DT + L1): peer path alone detects at 8.52 / 7.33 s, harm 5.66 /
  4.43 m (predicted ~9 s, ~5.8 m); self path silent (taken out); gps and
  cross_check silent.
- nav_error_end ~ offset(W) in every attack flight (44.7-50.0 m vs
  45.3-50.0 m): no arm repairs navigation. As predicted.
- P-B1-8 (S3), as pre-registered (drift over [t_ack, t0 + W], W = 120 s):
  proportionate 46.62 / 46.08 m (predicted ~39 m); trust_aware 9.63 /
  9.62 m, **above the stated 7.91 m: this prediction is not met.**
  creep_mps trust_aware 0.063 / 0.057 (< 0.5, so not the "limit of H2"
  case), proportionate 0.29 / 0.28; vel_err_mps 0.06 in all four;
  action failures 0; trust_aware / proportionate drift ratio ~4.8.

POST-HOC (exploratory, written after these results; not part of the
decision): `scripts/h3_posthoc_s3_windows.py`. The 7.91 m bound was
calibrated for the H2 window (60 s from injection); the prediction
applied it to W = 120 s. Same drift, truncated at t0 + 30 / 60 / 90 /
120 s: trust_aware 4.19 / 7.08 / 8.72 / 9.63 and 4.58 / 7.26 / 8.80 /
9.62 m; proportionate 22.2 / 35.4 / 42.7 / 46.6 and 21.6 / 34.8 / 42.1 /
46.1 m. On the H2 window trust_aware is within the bound (7.1-7.3 m),
but the drift keeps growing after it (+2.4 m over the next 60 s),
consistent with the zero-velocity hold following an EKF velocity that
carries part of a slow, absorbed spoof (creep ~ vel_err ~ 0.06 m/s).
Under the fast spoofs of H2 the same action drifted 1.5 m.

### Offline coverage map (step 4; rules: "Offline coverage map" + A1)

Code 32d9036 (`python3 -m metrics.h3_offline_map --h3 runs_h3 --stage3
runs_stage3 --check` / `--map`), run 2026-09-28 on the Mac copies of
h3_raw (a1746b37...) and stage3_raw (c419d204...). Outputs (not in git):
h3_map.json SHA-256
7bdc210a931f879b3c8964244b41d0bd45204f4d63041b3b4c37422b07feecf9,
h3_map_check.json SHA-256
ba9584e37eacfdcbb3bf57a0a013a4d76e1f222852dabd45da3ffff69d27a956.
Input: 14 S1 flights; calibration 130 stage-3 runs (1 gated, as in [2b]).

**Replay check (A1.8): PASS.** sigma 0, b 0.2, theta 1.8 / 1.3, 50 seeds:
peer-path detection 100 % in all 11 attack flights; |median offline
t_rng_peer - live| <= 0.84 s (L1 r5: 8.70 vs 9.54 s); 0 alarms in 150
no-attack replays (6.9 h). Not criteria: t_rng_self offline vs live
within 1 s except L10 r2 (7.4 vs 10.5 s, the live value is the late
one); the live L3 r1 misattribution did not recur in 50 replays
(consistent with the [2c] model rate, 0.65 %). The [2b] calibration is
reproduced by the same code with the [2b] keys: max 1.242 m -> 1.8 / 1.3.

**Calibration theta / theta_ok (m)**, 50 seeds, "map-cal" keys:

| sigma per axis | b = 0 | b = 0.2 | b = 0.4 |
|---|---|---|---|
| 0 | 1.6 / 1.1 | 1.8 / 1.3 | 2.0 / 1.5 |
| 0.5 | 3.6 / 3.1 | 3.8 / 3.3 | 4.0 / 3.5 |
| 1.5 | 9.3 / 8.8 | 9.1 / 8.6 | 8.9 / 8.4 |
| 3 | 18.4 / 17.9 | 18.2 / 17.7 | 18.0 / 17.5 |

theta ~ 6 sigma: with tau = 60 s the GNSS error is almost constant over
3 announcements, so k = 3 does not filter it, and the max rule puts
theta beyond the tail of the relative error of two UAVs. b hardly
matters (absorbed by the calibration).

**Map, b = 0.2 m** (b = 0 and 0.4 differ by <= 1 m in harm; full table
in h3_map.json). Per level: 5 (L1) or 2 flights x 50 seeds. Peer-path
detection within W = 100 % in every cell. False alarms: 0 in every cell
(150 no-attack replays, 6.9 h; < 0.44 per flight-hour, rule of three).

| sigma | theta | v0 1 m/s: t_rng / harm (p5-p95) | 3 m/s: t_rng / harm | 10 m/s: t_rng / harm | 30 m/s: t_rng / harm |
|---|---|---|---|---|---|
| 0 | 1.8 | 8.5 s / 5.5 m (4.5-6.1) | 7.1 / 3.8 | 7.1 / 34.0 | 8.7 / 49.0 |
| 0.5 | 3.8 | 10.2 / 7.0 (5.7-8.8) | 12.3 / 24.1 (3.9-24.8) | 7.1 / 34.0 | 8.7 / 49.0 |
| 1.5 | 9.1 | 22.7 / 16.9 (15.2-21.9) | 16.3 / 28.6 | 16.0 / 46.1 | 8.7 / 49.0 |
| 3 | 18.2 | 40.4 / 26.3 (23.8-30.7) | 19.0 / 31.8 | 18.0 / 47.4 | 9.5 / 49.3 |

Harm at 10 and 30 m/s, and at 3 m/s once the alarm follows the EKF
jump (~13 s), is the estimate error after the jump (B0 definition), not
the physical displacement at that moment (as stated for L10/L30 in
"Predictions").

Misattributions: **0 by the peers' monitors** in every cell. The
victim's own monitor, before its self flag, names an honest peer in
many replays once sigma > 0 (L1, b 0.2: 89 alarms in 250 replays at
sigma 0.5, 264 at 1.5, 257 at 3; L3 / L10 / L30: 4-86). theta_ok grows
with theta, so "fine" with one peer is easy while the other pair is bad:
the stated [2c] limit, much larger under noise.

**Map predictions (A1.9):**
- M1 (harm flat in v0 <= 3): **NOT MET.** Ratio harm(L3) / harm(L1) =
  0.69 at sigma 0 (expected, stated in A1), 3.45 at 0.5, 1.64-1.76 at
  1.5, 1.20-1.21 at 3 (within [0.8, 1.25] only at sigma 3). At sigma
  >= 0.5 the L3 ratio is confounded by alarms after the jump (above).
- M2 (harm grows with theta(sigma)): **HOLDS** for L1 and L3 at every b
  (L1: 5.5 / 7.0 / 16.9 / 26.3 m).
- M3 (fast spoofs: alarm tied to t_jump): **NOT MET.** No alarm before
  t_jump - 0.5 s in any cell (the P-B1-2 part holds everywhere), but
  t_rng - t_jump <= 4 s in only 40 % (L10, sigma 1.5), 4 % (L10,
  sigma 3) and 88 % (L30, sigma 3) of replays.

POST-HOC (exploratory, after the map; not in any decision):
`scripts/h3_posthoc_m3_residual.py` (1 test), noise-free peer-path
residual rho_p(t) = |b_0 - b_p| - |x_0 - x_p|. After the jump the victim's
controller brings its estimate back to the route, so its true position
leaves it: rho jumps to +16...+31 m, falls through 0 at ~13-15 s and
settles at about -48 m, while |belief - truth| stays at 31-48 m. The
residual is blind where the two distances to a peer are equal, whatever
|e| is. With theta <= 3.8 m both peers reach 3 consecutive ticks in the
positive phase (7-10 s); with theta = 9.1 m the gap below theta between
the phases grows from < 1.5 s to 7-8 s, only one peer per L10 flight
still reaches 3 ticks there (peak ~20 m, marginal), and with GNSS noise
that path often breaks: the alarm moves to the negative phase (16-18 s).
This explains M3; it is a property of a range-difference test, not a
code defect.

For the text (Ch. 4/5): v1 never fires at 1 m/s; ranging always does
within 120 s with 0 false alarms, but the harm it allows scales with
the GNSS quality under this calibration rule (~7 m at sigma 0.5 m,
17-26 m at 1.5-3 m). Attribution relies on the peer path; the victim's
own judgements of its peers are not usable under GNSS noise.
