# Pre-registered analysis plan — robust release-timing optimization

Written **2026-11-05, before any v002 optimization result exists.** v001 data (approved geometry with
junction defects) were used only for method development (response-map exactness check, timing
feasibility). Changes after this date must be appended as dated amendments with a reason; the
objective and the test set may not be changed after test-set results are seen.

## 1. Geometry and model (frozen)
* Geometry **v002** (`docs/GEOMETRY_QA.md`, hashes in `geometry/FROZEN_v002.json`). v001 results are kept
  in `archive/v001/` and are never mixed with v002 results.
* Airflow: laminar pimpleFoam, settings in `config/experiment.yaml` at the commit/hash recorded in the
  frozen file. Particle solver `airwayParcelFoam` v2 (one-way coupling, drag + gravity, Cunningham, stick).

## 2. Decision variables
* Particle diameter d ∈ {1, 2, 3, 5} µm (tested values only).
* Pulse start s (fraction of inspired volume), continuous, window width **w = 0.10 fixed**.
* Feasibility constraint (configurable, `optimization.s_min`, `s_max`): 0 ≤ s and s + w ≤ 1.
  No claim is made that a real device can deliver an arbitrary pulse; w = 0.10 is a modelling choice.
* Equal introduced aerosol mass for every candidate (flow-proportional release inside the window).

## 3. Outcomes
* **Primary:** target delivery D = % of introduced mass whose first crossing of the target-entry disc
  (s = 28 mm along the target branch) occurs during the 3-s simulation (original protocol).
* **Secondary (declared now, exploratory):** penetration delivery D_V = % of introduced mass that crosses
  the target-entry disc early enough that the target branch then inhales at least V mL more air before
  the end of inhalation (lumped plug-flow downstream airway; no downstream deposition). V ∈ {5, 10, 20} mL.
  Reason: release timing can only matter if aerosol must still travel after crossing; see
  `docs/TIMING_FEASIBILITY.md`.
* Reported for every strategy: mean, minimum, SD of D across conditions; target-wall, upstream, constriction,
  comparison deposition; outlet escapes; still airborne; Monte Carlo standard errors.

## 4. Conditions
**Training set (used for optimisation and model development) — 9 conditions, mean flow 2 L/min:**
narrowing {0, 20, 40} % × waveform {Beta(2,5), Beta(3,3), Beta(5,2)}.

**Reference condition for Method B:** N20 × Beta(3,3) (the central training condition).
Single-condition optima for all 9 training conditions are also reported as a sensitivity analysis.

**Held-out test set (never used for selection or tuning) — 8 conditions:**

| id | narrowing | waveform | mean flow | what changes |
|---|---|---|---|---|
| H1 | 30 % (v002 builder) | Beta(3,3) | 2 L/min | intermediate severity |
| H2 | asymmetric (eccentric) narrowing, same minimum area as 40 % | Beta(3,3) | 2 L/min | anatomy |
| H3 | 20 % | Beta(2,3) | 2 L/min | new waveform |
| H4 | 20 % | Beta(4,4) | 2 L/min | new waveform |
| H5 | 20 % | Beta(3,3) | 1 L/min | flow |
| H6 | 20 % | Beta(3,3) | 3 L/min | flow |
| H7 | 30 % | Beta(2,3) | 3 L/min | combined shift |
| H8 | 40 % | Beta(5,2) | 1 L/min | combined shift |

Eight scenarios are few; generalisation claims are limited to "these conditions".

## 5. Methods compared
* **A — continuous:** release over F ∈ [0, 1] (original definition), for each d; A uses the best d on training
  mean (reported for every d as well).
* **B — single-condition:** (d, s) maximising D on the reference condition.
* **C — robust (primary objective):** (d, s) maximising min_k D_k over the 9 training conditions.
  Alternative objective, used only if C's choice is degenerate (ties within Monte Carlo error) and decided on
  **training data only**: lower-tail CVaR = mean of the worst 3 of 9 training conditions.

## 6. Computation and statistics
* D_k(d, s) on training conditions is computed from release-time response maps (one continuous-release run
  per condition and size, 100 000 parcels); the map is checked against independent direct pulse simulations
  (fresh random seed) before use.
* Search: exhaustive grid over s ∈ [s_min, s_max − w] in steps of 0.005 (the map makes this cheap), all 4 sizes.
  The same grid/budget is used for B and C.
* Selection bias: the chosen strategies are **re-simulated directly with new random seeds** on training and
  on every held-out condition; only these direct, independent runs are used for the evaluation tables.
* Uncertainty: Monte Carlo standard errors from parcel sampling; repeated seeds are numerical replicates,
  not independent subjects. No p-values are computed across the 8 held-out scenarios beyond descriptive
  paired differences (C − B, C − A) with their range.

## 7. Hypothesis test (decided now)
H: C has a higher **minimum** held-out delivery than B, at the cost of at most a small loss in mean.
* Supported if min_H(C) − min_H(B) > 2 × combined Monte Carlo SE and the sign is the same for the
  primary outcome on ≥ 6 of 8 held-out conditions in the paired comparison.
* Rejected if min_H(C) ≤ min_H(B).
* Inconclusive otherwise (differences within numerical uncertainty), which is reported as such.

---
## Amendment 1 — 2026-11-05 (TEAM decision, recorded before any v002 particle result existed)
1. **Primary outcome stays plane crossing** (target delivery D, §3) for the 144-case experiment and for all
   optimisation claims, consistent with the original protocol.
2. **10 mL penetration (D_10) is secondary/exploratory only.** It may not be used to select strategies until its
   definition and validity have been assessed (`docs/PENETRATION_OUTCOME.md`). 5 and 20 mL are sensitivity values.
3. **Only v002 results support quantitative claims.** v001 is archived exploratory data; it was produced with solver
   v1, whose per-step inlet-weight renormalisation (D-13) and parcel dropping at 5 µm (D-07) may bias it.
4. After v002 completes: compare D and D_10 — do they select different particle sizes or release timings? If D is
   nearly identical across release timings in most conditions, that limitation is reported; the primary outcome is
   **not** switched to produce a stronger result.
5. A physiologically more meaningful primary outcome (e.g. regional deposited dose in an extended or anatomically
   realistic airway) is deferred to a **separate, newly pre-registered** validation experiment.
