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
     not the runner's inject_start marker, which precedes it by the
     OFF_R round trips (reported as inject_lag_s). No-attack flights
     use the marker.
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
   125 s: the analysis window W = 120 s starts at t_target_set, which
   lags the runner's marker by the OFF_R round trips, so 5 s margin.
   Order: no-attack flights 1st, 10th and 20th; attack cells
   replicate-major, generalised to unequal n (replicate r of n at
   (r - 0.5)/n), so the 5 L1 flights spread over the batch. Every
   flight has its own replicate number; a re-flown excluded flight gets
   the next free number of its cell.]

## Amendments

(none)

## Results

(empty until the flights)
