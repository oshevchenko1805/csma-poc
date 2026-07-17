# RESULTS_NOTES.md

Working record of every empirical result, the mechanism behind it, its
caveats, and where it belongs in the dissertation. Written while the
details are fresh; Chapters 4-5 get written from this file at the end.

Rule for this file: record what was **measured** and what it **means**,
including the parts that are inconvenient. Numbers without their
mechanism are unusable a month later.

---

## R1. detector_takeout — mesh gives detection that segmentation cannot

**The headline result.** Closes the Ch.2 (2.9) / Ch.3 (3.4.5, Table 3.10)
claim that distributed local-first detection *with security context
sharing* catches what an isolated segment misses — a claim that had no
empirical support before this.

### Scenario
Adversary silences the **local detectors of the target's own monitor**
(the monitor stays alive and keeps publishing its position to the mesh),
then GPS-spoofs the target (`SIM_GPS_OFF_N=50`).

Threat model, stated precisely: the adversary compromises **node-local
intrusion detection** on the UAV. The UAV keeps broadcasting telemetry —
it must, to hold formation and stay controllable. So the local detection
layer is blind while the mesh signal survives.

### Data (`runs_v2/`, batch 30/30 ok, N=10 per architecture, 90/60 timing)

| Metric | A | B | C |
|---|---|---|---|
| Detection rate | 0/10 (0%) | 0/10 (0%) | **10/10 (100%)** |
| MTTD | n/d | n/d | 8.101 ± 0.233 s |
| MTTR | n/a | n/a | 0.019 ± 0.006 s |
| Impact scope | 0.00 ± 0.00 | 0.00 ± 0.00 | 1.20 ± 0.63 |

### Mechanism — verified, not inferred
Across the 10 C runs: **20 `cross_check` events on the target** (2 per
run = both neighbours) and **zero local `gps` events**. Detection in C is
carried exclusively by mesh context sharing. Sources: `monitor_uav_1`,
`monitor_uav_2`.

MTTD std of ±0.233 s over 10 runs = a stable mechanism, not a lucky
coincidence of SITL timing.

### Why the monitor is left alive (important, non-obvious)
Killing the target's **whole monitor** measures nothing: it also stops
that UAV's peer-position publishing, which blinds the neighbours'
cross_check. C would then degrade to B for a mechanical reason, not an
architectural one, and all three architectures score 0%. The scenario
only isolates the mesh's contribution because the monitor keeps
broadcasting. This must be stated in Ch.4 as a deliberate threat-model
choice, not glossed over.

### Reviewer objection, and the answer
> *"You disabled a detector. C has two, A/B have one. Of course C
> survived. That's arithmetic, not a result."*

Answer: the **same component** was disabled in all three (the target's
local detector), and C was given nothing beyond what its architecture
already provides. Redundancy-through-distribution is the property under
test, not a handicap given to the baselines. Frame it in Ch.5 as an
**ablation study** — isolating the marginal contribution of the mesh
layer — not as "C wins". And state the price (below).

### Caveats to write honestly
- **N=10 is not "100%".** Wilson 95% CI for 10/10 is ≈ [72%, 100%]. Use
  N=30 in the final campaign, or report the interval.
- C's impact_scope 1.20 (not 1.00) = 3 post-attack heartbeat FPs on
  neighbours across 10 runs. Real SITL-load artefact under 3×PX4+Gazebo.
  Report as is; it is the FP price of the extra layer.
- The result is **binary by construction** (deterministic mechanism).
  Fisher exact on 0/10 vs 10/10 gives p ≈ 1.1e-5, but a fair reviewer
  will note this only confirms a deterministic system is deterministic.
  The parametric sweeps (see OPEN-2) are what make it continuous.

### Thesis placement
Ch.4: scenario + threat model + why the monitor stays alive.
Ch.5: detection table + ablation framing + FP price + CI caveat.

---

## R2. monitor_takeout — A's single point of failure, measured

**Closes the Table 3.9 / 3.10 claim about A's SPOF, which was asserted
but never demonstrated.** Before this, A and B were empirically
indistinguishable in every dataset (120 runs of runs_v1: MTTD ~equal,
impact 1.00, detection 100% everywhere; runs_v2: 0/10 both). Three
architectures, two of them measurable.

### Scenario
Adversary compromises the host running **uav_1's** monitor, stopping
every monitor in that host's failure domain. Then GPS-spoofs **uav_0** (a
*different* UAV).

### Data (live smoke, N=1 each — batch pending)

| | A | B |
|---|---|---|
| detected | **False** | **True** |
| MTTD | n/d | 2.73 s |
| security events | 0 | 1 |

Verified mechanically: in A all three monitor logs are empty (the whole
contour died with the shared `ground_station` domain); in B
`monitor_uav_0` logged at +2.7 s.

### Why the takeout target must differ from the attack target
Taking out the attack target's own domain gives 0%/0%/0% — no contrast
(same reason as R1). Attacking a *neighbour's* domain leaves B/C's
detection of the target fully intact while collapsing A's. That
difference **is** the blast radius.

### Fairness argument (write it before the reviewer asks)
The action is identical in all three: compromise the host of one
monitor. That this removes three monitors in A and one in B/C is not a
handicap — it is the *definition* of a single point of failure, and it
is exactly what Table 3.9 asserts. Centralisation means the monitors
share a host; the blast radius is the property under test.

### Thesis placement
Ch.4: scenario. Ch.5: the A-vs-B/C table — the only place in the whole
work where A and B are distinguished by data.

---

## R3. The mesh costs latency (trade-off, not a flaw)

- B detects the spoof with a **local** detector in **2.73 s** (R2).
- C detects the same spoof via **cross_check** in **8.10 s** (R1).

The mesh buys redundancy at roughly **3× detection latency**. This is
exactly the decomposition 3.4.5 asks for ("в одних випадках перевага в
ранньому detection, в інших — у швидшому recovery").

Write it as an engineering trade-off, not as an embarrassment: an
architecture dissertation that reports only its own advantages is weaker
than one that quantifies its own price.

---

## R4. First physical measurement — and recovery does NOT stop the drift

**Only visible because of the external ground-truth observer.**

Live run `run_c_gps_spoofing_1784198230`, arch C, `SIM_GPS_OFF_N=50`:

| | before attack | +0..20 s | +40..60 s |
|---|---|---|---|
| uav_0 (target) | y = 0.0 | y = **-48.3** | y = **-50.0** |
| uav_1 (control) | y = 0.1 | y = 0.0 | y = 0.0 |

- Displacement is **exactly 50 m**, matching the injected offset. Gazebo
  world is ENU (x = east, y = north); GPS claims "you are 50 m north", so
  the controller compensates by flying 50 m **south**. The UAV believes it
  is holding position the whole time.
- This is the first **physical** confirmation of the GZBridge patch —
  previously it was confirmed only through the detector's reaction
  (`pos_horiz_ratio`), i.e. through a number inside the attacked system.

### The uncomfortable part
C detected at 8.1 s and issued loiter at 8.2 s (MTTR = 0.019 s,
recovery_status = success) — **and the UAV still ended up 50 m off**.

Reason: `action.hold()` holds the **estimated** position, and the
estimate is exactly what the attack poisons. The drone holds position in
a falsified frame and keeps physically drifting. Recovery succeeded by
every event-log metric and prevented no physical harm.

### Why this is a strong result, not a failure
It is a genuine finding of the kind only an external observer can
produce: **architectural detection works; the chosen recovery action is
inadequate for an attack on navigation integrity.** Loiter is the right
response to an availability attack (comm loss), not to an integrity
attack on the position estimate.

For Ch.5/6: report MTTR *and* physical residual drift side by side, and
discuss that recovery-action selection must be attack-class aware
(MITRE T0856/T0832 integrity vs T0826/T0814 availability — the
distinction already drawn in the thesis tables). This is a concrete,
defensible line of future work that falls out of the measurements.

To quantify: compare final drift across A/B (no recovery) vs C (loiter)
across the campaign. If drift is equal, the point is proven
quantitatively. **Now feasible** — see R7: with a mission actually in
progress the drift is large and unambiguous. See also R8 for what an
*undetected* spoof does physically, which is the natural control case for
this comparison.

### Related: "MTTR" is currently misnamed (raise in Ch.5, do not paper over)
MTTR across runs_v3 is **0.015 ± 0.006 s**. Fifteen milliseconds is not a
recovery time; it is the latency from decision to *issuing* the loiter
command. Combined with the finding above — that loiter does not restore a
safe state under an integrity attack — the metric measures reaction
dispatch, not recovery. The number is not wrong, the name is. Ch.5 needs
the honest decomposition (dispatch latency vs. actual restoration vs.
PX4 cold-start, per PROJECT_STATE) rather than a headline "MTTR = 15 ms",
which a reviewer will correctly attack.

---

## R5. Analyzer defect found and fixed — impact_scope time anchor

`compute_run_metrics` counted **every** security event into
`affected_uavs`, while `detected` correctly required
`timestamp >= inject_start`. Pre-attack noise therefore inflated
`impact_scope`.

Observed in runs_v2 arch A: `impact_scope = 0.50 ± 1.08` with detection
**0%** — a contradiction. Traced to 5 heartbeat events in 2 of 10 runs,
all **before** the attack (−12.9 s, −36.8 s), clustered = transient SITL
stalls.

Fix: `impact_scope` now uses the same `inject_start` anchor as
`detected`. Events before an attack cannot be its consequence.
`has_false_positive` deliberately **not** changed — a security event on a
non-target UAV is a false positive regardless of when it fired.

After fix: A 0.00, B 0.00, C 1.20. **runs_v1 unchanged (1.00 everywhere)**
— the 120-run dataset is unaffected; verified, not assumed.

Worth one honest sentence in Ch.4 (methodology): the defect existed
during the runs_v1 collection but did not affect it.

---

## R6. Known dead axes (do not re-investigate)

- **τ_isolate = 0.0001 s** in every architecture. Isolation is a local
  in-process decision; it does not discriminate. Level-1 "free metrics"
  from `model_experiment_map.md` were checked and are dead.
- **τ_total** — only available in C (needs recovery).
- **impact_scope in runs_v1 = 1.00 constant** — single-target scenario has
  no propagation. Only multi-target revives it.
- **runs_v1 detection = 100% everywhere** — the local gps detector catches
  the 50 m spoof unaided in all architectures, which is why the mesh looks
  redundant there. That is what R1 exists to correct.

---

## R7. OPEN-1 resolved — the mission now outlasts the trial

**Was the campaign blocker. Closed with data, not argument.**

### The measurement that established it
Trajectory of `run_c_gps_spoofing_*` (ground truth, uav_1 = control):

| t | state |
|---|---|
| 0 – 10.9 s | on ground (arm / pre-arm) |
| 10.9 – 21 s | climb to 20 m |
| **21 – 57 s** | **flying the square** |
| **57 – 161 s** | **hovering at home, v ≈ 0.03 m/s** |

The single-lap route finished at **t ≈ 57 s** while attacks fire at
**t = 90 s**. Every attack in R1-R4, runs_v1 and runs_v2 therefore hit a
**hovering** UAV, and mission resilience (3.4.5) was unmeasurable.

### The fix
`mission.laps` in `configs/experiment.yaml` (new, `core/config.py`),
default 1. The authored lap pattern is repeated `laps` times at load
time; `MissionConfig.waypoints` is the fully expanded plan, so
`runners/mission_mavsdk.py` and `runners/experiment.py` are untouched and
know nothing about laps. Architecture discipline holds: config only, no
`if architecture` anywhere.

Shipped value: **`laps: 5`**, square lap of 4 corners → 20-item plan.

Sizing, from measurement rather than estimate:
- lap time ≈ 34 s (120 m perimeter, 5 m/s cruise, ≈3.5 m/s average with
  corner deceleration)
- motion from t ≈ 21 s to t ≈ 191 s
- attack at t = 90 s → lap 3, in motion (**verified**, v = 2.7-5.1 m/s on
  all three UAVs)
- observation ends t = 150 s → lap 4, in motion (**verified**, v = 1.5-5.0
  m/s on all three)

4 laps also clears the window but only by ~8 s; `is_armable` (EKF/GPS
convergence) varies run to run and 8 s would not survive a 1000+ trial
campaign. 5 costs nothing: **the runner never waits for mission
completion** (`wait_until_complete` is never called; it sleeps
`attack_at + observation`), so route length does not change trial
duration — confirmed: 160.7 s before, 160.5 s after.

The mission deliberately does **not** complete inside a trial. That is
what "attack on a mission in progress" requires.

### Guards added (14 new tests, 512 → 526, all passing)
- `laps` validated: integer (rejects `2.5`, rejects `true`), ≥ 1
- expanded plan rejects **identical consecutive waypoints** — a
  self-closing lap would produce one at every seam and it is a no-op for
  PX4. Previously this could only be caught by eyeballing a trajectory.
- `test_experiment_mission_is_multi_lap` asserts the shipped config still
  flies ≥ 4 laps. If someone trims it back to one, a test fails instead of
  a campaign silently collecting hover data again.

### For Ch.4 (methodology)
Route length is an experiment parameter with a stated derivation, and the
earlier datasets (runs_v1, runs_v2, R1-R4) are explicitly
attacks-on-hover. That is defensible if stated; it is indefensible if
discovered by a reviewer.

---

## R8. Detection under motion is stable — 20/20, and a detector gradient

**The question R7 forced:** if every prior result measured a hovering
UAV, does detection survive when the UAV is actually flying? The
`gps_spoofing` row of Ch.5 depended on the answer.

### Data (`runs_v3/`, batch N=20, arch C, 5-lap route, 90/60 timing)

| Metric | value |
|---|---|
| Detection rate | **20/20** — Wilson 95% CI **[84%, 100%]** |
| MTTD | 3.113 ± 0.677 s |
| Impact scope | 1.00 ± 0.00 |
| False positives | 0/20 |

Write it as "20/20, 95% CI [84%, 100%]", never as a bare "100%".

Two things settled at once: detection is not an artefact of hovering,
**and** the metrics did not break on the new route — `cross_check` does
not fire falsely on genuinely moving neighbours (impact_scope 1.00,
FP 0/20).

### The gradient — do not omit this from Ch.5
Detectors firing per run were not constant:

| runs | detectors fired | MTTD |
|---|---|---|
| 19 of 20 | 3 | 2.58 – 3.28 s (mean 2.97, sd 0.22) |
| **r10** | **1** | **5.84 s** |
| `run_c_gps_spoofing_1784210522` (manual, outside runs_v3) | **0** | not detected |

Excluding r10 is a **post-hoc** exclusion and must not be used for the
headline: report 3.113 ± 0.677 (N=20). The point of the breakdown is that
the sd is driven entirely by one run, and that 3 → 1 → 0 is a gradient,
not a binary.

So `1784210522` (the one manual run that was never detected, whose UAV
then flew uncontrolled to −83 m and dropped to **z = 0.5 m** — see below)
is the far end of a real distribution, not an isolated glitch. Something
in the ramp-onset signature varies run to run. **Cause unknown.**

### The physical control case (extends R4)
`1784210522` is the natural control for R4's drift comparison: same
attack, detection simply did not occur, so nothing issued loiter.

| | `208189` (detected, mttd 2.6) | `210522` (not detected) |
|---|---|---|
| t = 110 s | (29.8, 28.4) z = 20.3 | (−6.6, −29.1) **z = 0.5** |
| t = 120 s | (30.0, −16.7) | (−80.9, −40.0) |
| range | x[0..30] y[−20..30] | x[−83..30] y[−50..31] |

Read the causality correctly: the wild trajectory is a **consequence** of
non-detection, not its cause. Detected → isolation → loiter → the UAV
stopped at ~20 m offset and held. Undetected → the mission kept executing
in a falsified frame → the UAV was thrown across the field and nearly
touched the ground. This is what R4's "loiter is inadequate" costs when
even the inadequate response is absent.

### What was ruled out (do not re-investigate)
The natural hypothesis was `SIM_GPS_OFF_N` leaking between runs via
per-instance param storage: `run_batch` clears
`rootfs/{0,1,2}/parameters*.bson` between trials, the manual `run_one.py`
does not. **Checked and false** — after a normal run only
`parameters_backup.bson` exists and `SIM_GPS_OFF_N` is **not in it** on
any instance. Nothing leaks. See also OPEN-4.

### Thesis placement
Ch.5: the gps_spoofing row with CI. Ch.4: the honest note that the
detectable signature is the ramp onset, and its strength varies (OPEN-3).

---

## OPEN-2 — what turns binary results into curves

Recorded here so the intent is not lost:

1. **Sweep over spoof magnitude** (5/10/20/30/50/80 m) → detection-rate
   curves per architecture. Finds the local detector's threshold vs
   cross_check's. If cross_check catches *smaller* offsets, the mesh adds
   sensitivity, not just redundancy — a strong, fully numeric result. A
   null result (cross_check is coarser) is also honest and publishable.
2. **Sweep over k compromised monitors** (0/1/2/3) → three qualitatively
   different degradation functions: A cliffs at k=1 (SPOF), B steps only
   when its own monitor is hit, C degrades gracefully while a quorum of
   neighbours survives.
3. **Sweep over mesh loss/delay** (0/10/30/50%) → where C's advantage
   dies. Currently the mesh is ZeroMQ over localhost: zero loss, zero
   delay, no partitions — while Ch.2 reviews FANETs where none of that
   holds. This is the single most exposed assumption in the work.
4. **Statistics that then apply for real**: bootstrap CIs, Mann-Whitney U
   for MTTD, Fisher exact for binary cells, and logistic regression
   `detection ~ magnitude × architecture` (gives threshold estimates and
   their difference between architectures).

`mission.laps` (R7) makes flight duration a single-number parameter, so
route length can join these sweeps without hand-editing waypoints.

---

## OPEN-3 — the ramp-onset signature varies run to run

From R8: 19/20 runs fired 3 detectors at ~2.97 s; one fired 1 at 5.84 s;
one manual run fired none. Cause unknown.

Why it matters: the detectable signature of the GZBridge offset injection
is the **onset transient** (the ramp), not the steady state — already
documented as a methodological note for Ch.4. If the onset is sometimes
weak enough to miss, the detection rate is a property of the *injection*
as much as of the architecture, and that belongs in threats-to-validity.

**Cannot be investigated with current data.** `run_c_gps_spoofing_1784210522`
contains zero security events — monitors log events, not raw telemetry, so
there is nothing to inspect. Needs the instrumentation below (PX4 true vs
believed position, and the raw `pos_horiz_ratio` series) before it can be
answered. Do not spend more runs guessing at it first.

---

## OPEN-4 — is the bson-clearing discipline actually necessary?

PROJECT_STATE records as an operational rule: per-instance param storage
at `build/px4_sitl_default/rootfs/{0,1,2}/parameters*.bson` persists
across restarts and **must** be cleared between runs to stop
`SIM_GPS_OFF_N` leaking into baseline runs.

Contradicting observation (R8): after a completed run, only
`parameters_backup.bson` exists — no `parameters.bson` — and
`SIM_GPS_OFF_N` appears in **none** of the three instances. If the param
never reaches persistent storage, there is nothing to leak and the rule
protects against nothing.

Low priority, no action now: `run_batch` clears the files anyway and the
clearing is harmless. But the rule is currently stated as fact in
PROJECT_STATE on the basis of something that was apparently never
verified — either confirm it or correct it before Ch.4 cites it as
methodology. Do not remove the cleanup step on the strength of one
observation.

---

## Work queue (order matters)

1. **Instrumentation — before the campaign, not after.** Mission plan in
   `run_summary` (so "was the UAV flying?" is checkable per run instead of
   by hand-reading trajectories — R7 was found by eye and should never
   need to be again); mesh cost counters; PX4 true-vs-believed position;
   mesh loss/delay. Omitting this means re-running ~1160 trials.
2. R2 batch (currently N=1 smoke; R1 already has N=10).
3. OPEN-2 sweeps.
4. Full campaign, N=30/cell, with the statistics from OPEN-2.4.

## R9. MTTD decomposes — and most of it is the test rig, not the architecture

**What forced this:** the instrumentation for OPEN-3 (item 2A) recorded
the raw `pos_horiz_ratio` series for the first time. The very first
instrumented run explained MTTD arithmetically, and the explanation is
inconvenient.

### Data (`runs/run_c_gps_spoofing_1784270714`, arch C, gps_spoofing)

MTTD 3.276 s, detected, impact_scope 1, flying at inject: True.
uav_0 series: rate 0.9855 Hz, baseline_median 0.0104, n=159.

| t_rel (s) | pos_horiz_ratio | |
|---|---|---|
| -0.773 | 0.0141 | quiet |
| +0.233 | 0.3726 | ramp begins |
| **+1.278** | **2.0** | first crossing of threshold 1.0 |
| +2.307 | 2.0 | 2 of 3 |
| **+3.299** | **2.0** | 3 of 3 -> sustain satisfied, detector fires |
| +4.337 … +6.371 | 2.0 | still breaching (6 samples total) |
| **+7.364** | **0.0007** | collapse to baseline in ONE sample |

Detector fired at 3.276 s; the third breach sample is at +3.299 s. The
series accounts for MTTD to within the sample period.

### The decomposition

    MTTD = first_cross + (sustained_samples - 1) / rate
         = 1.278       + (3 - 1) / 0.9855
         = 1.278       + 2.03
         ~ 3.3 s

**2.0 s of the 3.113 s headline is a floor**, set by
`sustained_samples=3` and PX4's 1 Hz ESTIMATOR_STATUS. It is not a
property of the architecture. All variance lives in `first_cross`
(~1.1 +/- 0.7 across runs_v3).

### Why this matters, stated plainly

The floor is **identical for A, B and C** — same detector, same PX4 — so
it cancels in the architectural comparison. It costs nothing there. What
it costs is the headline: "MTTD 3.113 s" presented as the speed of
Architecture C would be 64% a property of the rig. A reviewer who spots
that unaided will read it as not understanding one's own test bench; the
same reviewer reading the decomposition reads methodological control.

This is the same story as MTTR (15 ms = dispatch latency, not recovery).
**Both time metrics in this PoC measure the rig more than the
architecture.** That is not a failure of the work — it is its boundary,
and the boundary has to be named. What carries the comparison is
`impact_scope` and the FACT of detection: `detector_takeout` gives C
10/10 via cross_check against A=B=0/10, and that difference is the
presence of a second signal channel, not speed.

### A confound this exposes — do NOT report 3.3 vs 8.1 as a speed result

`cross_check` MTTD is 8.101 +/- 0.233 s (R5). It has its OWN floor, set
by `peer_publish_period_sec = 1.0` and the cross-check's own logic. How
much of 8.101 is architecture and how much is publish cadence is
currently **unknown**. Until it is decomposed the same way, the
gps-detector's 3.3 s and cross_check's 8.1 s are not comparable as
"faster/slower".

### OPEN-3: a mechanism, not yet an answer

The breach window was **6 samples where 3 are required** — a 2x margin,
and everything rests on it. The ratio does not decay: it collapses
2.0 -> 0.0007 in one sample at +7.36 s, i.e. the EKF re-converges onto
the biased position in a step. If in some run the ramp starts later or
the EKF re-converges sooner, `max_consecutive_above` drops below 3 and
the detector stays silent while the attack works perfectly.

That is the "signature present, sustain rejected" branch, and it now
PREDICTS non-detections instead of rationalising them after the fact.

**Not closed.** N=1, and it detected. The undetected run predates the
instrument and has no series — it never will. Honest statement: the
instrument exists; the question becomes answerable the next time a
non-detection occurs in an instrumented run. Do not spend runs hunting it
deliberately.

### `peak` is censored — matters for the OPEN-2 magnitude sweep

The ratio clips at exactly 2.0 and holds. `peak: 2.0` therefore means
">= 2.0" and nothing more; no measure of signal strength can be built on
it. At 50 m of offset the signal is already at the ceiling, so the
planned magnitude sweep (5/10/20/30/50/80 m) will only resolve
differences BELOW it. Design the sweep around that, or the top of the
curve will be flat by construction rather than by physics.

### What to do about the floor

1. **Decompose and name it** — a table "MTTD = floor + variable part" per
   detection channel, including cross_check. Mandatory regardless of the
   rest.
2. **Sweep `sustained_samples`** (1/2/3/5) — turns the floor from an
   artefact into an AXIS: detection rate vs false positives vs MTTD.
   Cheap: a detector parameter, the rig is untouched. Add to OPEN-2.
3. **Raise the ESTIMATOR_STATUS rate** (MAVLink stream interval). 5 Hz
   would drop the floor 2.0 -> 0.4 s and make `first_cross` dominant.
   **Rejected for now**: it makes runs_v3 incomparable and introduces a
   fresh PX4-side unknown immediately before a ~1160-run campaign.

### Thesis placement

Ch.5: the decomposition table, and the honest reading that MTTD's floor
is a rig constant shared by all three architectures. Ch.4: the 6-sample
breach window and the one-sample EKF re-convergence, as the mechanism
behind the ramp-onset signature note. Threats to validity: OPEN-3's
prediction that detection rate is partly a property of the injection.

## INSTRUMENTATION 2B CLOSED — true vs believed divergence in run_summary

Item 2, second half. Item 2 (2A + 2B) is now complete. Tests 644 -> 674.

### Added

- `metrics/belief_divergence.py` — pure functions, no I/O in the maths:
  - `resolve_ekf_origin()` — median Gazebo pose over a UAV's
    chronologically-first pre-liftoff ground block. Measured, not the
    `instance*5` constant. None (never (0,0,0)) when no ground sample
    exists.
  - `belief_divergence()` — pairs believed LOCAL_POSITION_NED against
    Gazebo truth mapped into NED (north=gz.y-oy, east=gz.x-ox,
    down=-(gz.z-oz)), ±0.2 s tolerance, downsampled to ~1 Hz. Works with
    OR without an attack anchor; the `anchor` field records which.
- `runners/experiment.py`: `RunResult.belief_divergence`,
  `_compute_belief_divergence`, folded in `_finalize` after the detector
  loop with the same "errors go to `error`, never fail the run" contract
  as flight_check / estimator_series.

### Decisions

- **Origin measured, not configured.** This module is architecture-blind
  and has no business knowing fleet-spacing config; and the project got
  an axis assumption wrong once by reasoning instead of measuring (2A
  calibration). Validated live: baseline origins recovered 0/5/10 m
  exactly and healthy medians are sub-metre — a hardcoded `*5` would have
  been correct here but silently wrong under any future re-spacing (the
  5-7 drone step).
- **First pre-liftoff block only**, not all low-z samples: a later crash
  or landing must not pull the origin. Confirmed on real data — the
  recorder starts on the ground (z ≈ -0.013), so the block exists.
- **airborne threshold pinned to flight_check** by a direct equality
  test, not a second copy of the literal 1.0.
- **No anchor requirement** (unlike estimator_series): a working baseline
  is the ONLY condition where a frame error is distinguishable from a
  real spoof (truth == belief there). In practice the runner supplies the
  nominal instant even on baseline, so anchor is "attack"; the
  "first_sample" fallback fires only when the instant was never captured.

### Live verification

Matched pair, arch C, gps_spoofing, target uav_0, SIM_GPS_OFF_N=50:

- baseline `run_c_none_1784288796`: origins x = -0.0 / 5.0 / 10.0,
  medians 0.228 / 0.179 / 0.077 m. Spawn offset removed. Peaks 1-2 m are
  cornering/stitching artefacts (scatter across the run, incl.
  pre-injection and +57 s on a no-attack run) — baseline ceiling ~2 m.
- attack `run_c_gps_spoofing_1784289089`: uav_0 peak 50.03 m @ +55.9 s
  (== the injected offset; EKF fused the spoof), uav_1/uav_2 at baseline.
  Alongside pos_horiz_ratio (first_cross +1.374 s, collapse per R9) this
  closes the truth -> input -> belief triangle. See RESULTS_NOTES R10.

### Not done

- Third leg: GPS_RAW_INT (the falsified input, geodetic) — deferred.
- Items 3 (mesh cost counters) and 4 (mesh loss/delay). Unlike 1/2 they
  touch the system under test — a defect there corrupts the already-
  validated runs_v1/runs_v3. Design them in a fresh chat.

Do not launch the ~1160-run campaign until 3 and 4 are closed.
