# The 10 mL penetration outcome: definition, measurement and validity

Status: **secondary / exploratory** (PREREGISTRATION Amendment 1, decision T-5). Not used for strategy selection
until the questions in §4 are resolved by the research team.

## 1. Exact definition
For each computational parcel that first crosses the target-entry disc (the primary-outcome event) at time t_c:

    V_after(t_c) = ∫_{t_c}^{T_insp} Q_target(t) dt        [mL]

where Q_target(t) is the CFD air flow leaving the target outlet (taken from `postProcessing/flowTargetOutlet`) and
T_insp = 2 s is the end of inhalation (no air moves into the branch after it in this protocol).

* **D_V (plug, pre-declared):** the parcel's mass counts if V_after(t_c) ≥ V.
* **D_V (Poiseuille, sensitivity):** counts if 2 (1 − r²/R²) · V_after(t_c) ≥ V, with r = the parcel's radial distance
  from the branch axis where it crossed the disc and R = 3 mm.

D_V = 100 × (counted mass) / (introduced mass). V = 10 mL (5 and 20 mL as sensitivity values).

## 2. How it is measured
Entirely in post-processing (`scripts/lib/response_map.py → add_penetration`) from quantities the CFD already
records: each parcel's first-crossing time and point (`targetPlaneCrossings.csv`) and the target-outlet flow history.
No extra simulation; it is computed for every case, map and evaluation run.

## 3. What it represents — and what it does not
**It is a volumetric reachability criterion, not a simulation of deeper transport.** The CFD domain ends 32 mm
past the target plane; the target branch holds ≈ 0.85 mL beyond the plane, while it inhales ≈ 26–33 mL during the
breath (2 L/min). "10 mL" lies far outside the simulated airway. D_10 asks: *given when this aerosol entered the
target branch, could the remaining inhaled air in that branch carry it 10 mL deeper?*

It is grounded in a real mechanism — aerosol inhaled late stays in the conducting volume (the "dead-space" /
volumetric-front-depth idea behind bolus and inhaled-volume-tracking studies) — but it assumes:

| Assumption | Effect |
|---|---|
| Downstream airway = lossless conduit (no deposition) | overestimates delivery for larger particles |
| No branching, widening or mixing downstream | real airways branch; the volume to a given generation and the velocity profile change |
| Plug flow (pre-declared) or fully developed Poiseuille (sensitivity) | brackets the axial-dispersion effect; real flow lies somewhere else, with secondary flows from curvature/branching |
| Nothing moves after inhalation | no breath-hold settling, no exhalation |
| V = 10 mL is a modelling choice | not tied to a specific anatomical target |

## 4. Does it depend on the downstream-transport model? (measured, v001 exploratory data)
3 µm, symmetric breathing, kernel in release-point bins of 0.1 (% of aerosol released in the bin):

| condition | outcome | 0.05 | 0.15 | 0.25 | 0.35 | 0.45 | 0.55 | 0.65 | 0.75 | 0.85 | 0.95 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| healthy | D (primary) | 47.2 | 47.4 | 47.3 | 46.0 | 45.8 | 47.6 | 43.8 | 43.8 | 46.3 | 25.6 |
|  | D_10 plug | 47.1 | 47.4 | 47.2 | 45.9 | 45.7 | 47.0 | 22.7 | 0 | 0 | 0 |
|  | D_10 Poiseuille | 46.2 | 45.8 | 45.0 | 43.3 | 42.1 | 41.0 | 30.8 | 12.3 | 0 | 0 |
| N40 | D (primary) | 37.2 | 37.9 | 35.2 | 34.6 | 36.0 | 36.1 | 36.1 | 34.9 | 36.5 | 17.8 |
|  | D_10 plug | 37.1 | 37.8 | 35.2 | 34.4 | 35.5 | 23.0 | 0 | 0 | 0 | 0 |
|  | D_10 Poiseuille | 37.1 | 37.9 | 35.2 | 34.5 | 35.4 | 34.4 | 27.8 | 4.4 | 0 | 0 |

**Robust to the model:** a cut-off exists; it lies earlier for the narrowed airway (its branch inhales less air) and
it would move with breath size. **Not robust:** where the cut-off lies (it shifts by ≈ 0.1–0.2 in F between plug and
Poiseuille) and how much near-wall aerosol is lost before it. Any optimal release timing that sits near the cut-off is
therefore model-dependent, and claims based on D_10 must be reported under both variants.

## 5. Recommendation
* Keep D_10 secondary. Report D (primary), D_10 plug and D_10 Poiseuille side by side, and state when the optimal
  choice differs between them.
* A genuine test needs CFD of the downstream airway itself — e.g. the target branch extended with additional
  generations or an anatomically realistic distal airway, with **regional deposited dose** as the outcome. That
  belongs in the separately pre-registered validation experiment (Amendment 1, point 5).
