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
quantitatively.

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

## OPEN-1 (BLOCKER for the campaign) — the mission ends before the attack

In `run_c_gps_spoofing_1784198230`, uav_1 is at (5, 0) = home at attack
time, and the trajectory range shows it had already flown the full route
(to x≈30, y≈30) and returned. **The mission completes before t=90 s**, so
the attack hits a hovering drone.

Consequences:
- **Mission resilience is currently unmeasurable** — there is no mission
  in progress to degrade. The 3.4.5 property cannot be closed as is.
- Every existing result (R1-R4, runs_v1, runs_v2) describes an attack on a
  **hovering** UAV, not on one executing a mission. This is defensible but
  must be stated — or fixed.

Options: lengthen the route, or fire earlier (but not before EKF
convergence, ~30-60 s — 30 s is known to be too early).

**Must be decided before the ~1160-run campaign**, or the campaign
collects the wrong thing.

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
