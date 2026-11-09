# Scientific decision record

Each entry: problem · alternatives · reasoning · tests · what the tests showed · open uncertainty.
**Who:** `TEAM` = research team (human) decision; `AI` = proposed and implemented by the AI assistant —
these need to be understood, checked and either accepted or changed by the team. `AI→TEAM` = AI
recommendation that explicitly requires team sign-off.

## Research-design decisions (TEAM)
* **T-1** Research question, hypothesis and objectives (upgrade of 2026-11-05).
* **T-2** Particle sizes 1/2/3/5 µm; release strategies continuous/early/middle/late as F windows; narrowing
  0/20/40 %; Beta(2,5)/(3,3)/(5,2) waveforms; 2 s inhalation at 2 L/min mean, 1 s observation after.
* **T-3** One-way coupling, drag + gravity, stick on contact, equal introduced mass, primary outcome = first
  crossing of a target-entry plane downstream of the narrowing.
* **T-4** Three methods (continuous / single-condition / robust max-min), w = 0.10, train/test separation.
* **T-5 (2026-11-05)** Plane crossing remains the primary outcome; 10 mL penetration is secondary and must be justified
  before use; v002 only for quantitative claims, v001 archived as exploratory; no outcome switching for a stronger
  result; a deposited-dose primary outcome is deferred to a separately pre-registered experiment.

---

### D-01 Approved geometry v002 (AI→TEAM, sign-off required)
* **Problem.** The approved v001 STL has a flat shelf at the junction covering 35 % of the parent area and facing
  the flow, plus wall pockets where the branch cylinders protrude (docs/GEOMETRY_QA.md).
* **Alternatives.** (a) keep v001 as approved; (b) fix in Onshape (loft) and re-export; (c) rebuild the surface
  implicitly from the documented dimensions (v002).
* **Reasoning.** (b) is best for CAD traceability but needs the team's CAD work; (c) keeps every documented
  dimension and the exact measured narrowing profile and removes only the junction artefacts.
* **Tests.** Watertight/manifold; cap areas within 0.14 % of πr²; flat flow-facing area 17.6 → 0 mm²; max radius
  below junction 4.42 → 4.04 mm; narrowing profile identical to v001 within 0.01 mm; volume +0.3 %.
* **Uncertain.** The 1 mm junction blend and 0.5 mm carina blend are modelling choices (sensitivity not tested).
  v002 is STL-only (no STEP). v001 results are archived in `archive/v001/` for comparison.

### D-02 Laminar, transient airflow (AI, derived)
* Max Reynolds ≈ 970 (N40 throat at peak flow), Womersley ≈ 1.3 → laminar pimpleFoam, no turbulence model.
* **Uncertain.** Post-stenotic jets can become unsteady below pipe-transition Re; checked only via the mesh study.

### D-03 Mesh level and time step (AI, provisional)
* **Problem.** Compute cost on this machine (~6 µs per cell-step via Docker).
* **Choice.** Coarse mesh (~60 k cells, 0.4 mm wall cells, no layers), max Courant 3 with 2 PIMPLE outer iterations.
* **Tests (v002).** Medium mesh (~240 k cells, boundary layers) and Courant 1 on T_N40_SYM. Full acceptance criteria
  C1–C7 (conservation, branch split, pressure drop, velocity fields at junction and jet, delivery, deposition, kernel)
  were fixed on 2026-11-05 17:55 before viewing any medium result: validation/04_mesh_independence/CRITERIA.md.
* **Result (2026-11-06).** Coarse vs medium (218 k cells, 3 layers): PASS C1, C3, C4a; FAIL C2 (0.57 vs 0.5 pts),
  C4b (jet L2 36.5 %; peak speed −2.3 %), C5 (delivery −1.3 pts at 1/3/5 µm), C6 (deposition +3.7 to +4.0 pts).
  Diagnosis: spurious wall deposition of air-following particles on the layer-free coarse mesh, plus a post-narrowing
  jet that bends toward a wall on the coarse mesh. **Coarse mesh rejected.** Fine-mesh check (V_MESH_fine_T_N40_SYM)
  running; production mesh (medium or fine) decided by fine vs medium against the same criteria.
  Details: validation/04_mesh_independence/results/MESH_DECISION.json.
* **Consequence.** v002 coarse-mesh particle results (N40 maps, 36 N40 baseline cases) are exploratory only; all
  airflow conditions must be run on the adopted mesh.

### D-04 Outlet boundary condition (AI, provisional)
* Equal static pressure at both outlets (split set by geometry only). Sensitivity: prescribed target share 30 % and
  50 % on T_N40_SYM (planned).

### D-05 Particle forces (AI, derived)
* Drag (Schiller–Naumann) + gravity along +z (upright subject; PROVISIONAL direction).
* Cunningham slip applied exactly by an effective density ρ·C_c (C_c = 1.17 at 1 µm); mass uses true density.
* Brownian motion omitted: RMS displacement ≈ 13 µm over 3 s at 1 µm vs 3 mm branch radius.
* **Planned test.** Cunningham off and gravity off on one condition (force-model sensitivity).

### D-06 Release model (AI)
* Flow-proportional release (mass ∝ inspired volume inside the window) through `patchFlowRateInjection`;
  parcels start with the local air velocity. Area-random injection positions are re-weighted by 2(1 − r²/R²)
  so that the aerosol flux matches the parabolic inlet profile.

### D-07 Keep every parcel (AI, bug fix found in v001)
* **Problem found.** OpenFOAM discards parcels representing < 1 physical particle (`minParticlesPerParcel 1`).
  At 1 ng and 20 000 parcels a 5 µm parcel carries 0.76 particles, so ~50 % of 5 µm parcels were dropped
  (their mass was carried forward; introduced mass still within 0.6 %).
* **Fix.** `minParticlesPerParcel 1e-12` (nParticle is a statistical weight). v001 5 µm results are valid but have
  half the parcels; they are flagged in the archive.

### D-08 Custom solver reading the stored airflow (AI)
* `airwayParcelFoam` interpolates U linearly in time between stored airflow snapshots (every 0.02 s) and never
  re-solves the air: exact one-way coupling, each airflow solution reused by all its particle cases.
* **Tests.** Mass balance closes to < 1e-5 % in every case; straight-tube Pich settling 29.2 % vs 29.5 %.
* **Uncertain.** Snapshot interval 0.02 s (time interpolation error) — part of the time-step study.

### D-09 Target-entry plane at s = 28 mm (TEAM protocol, AI placement)
* Disc perpendicular to the target branch, 2 mm past the end of the narrowing, radius 3.3 mm; same position in all
  geometries. First crossing per parcel recorded inside the solver (an OpenFOAM function-object bug made the
  built-in face-zone logger unusable).

### D-10 Release-time response map (AI; mathematical basis)
* Under D-05/D-06/D-08 (one-way coupling, no particle interaction, deterministic forces), a particle's fate depends only
  on its release time and position; therefore delivered mass is **linear** in the release schedule:
  M_target = ∫ m(F) G(F) dF, and an equal-mass pulse on [s, s+w] gives D(s,w) = (1/w)∫_s^{s+w} G(F) dF.
  G is estimated from one continuous-release run by binning parcels by release F.
* **Test (v001).** P03 healthy/symmetric: map predictions for early/middle/late pulses 47.40/46.05/47.61 % vs direct
  runs 47.02/46.46/46.47 % (map SE ±1.29 pts with 2 000 parcels per window) — consistent with sampling noise only.
* **Consequence.** Map runs need ~100 000 parcels for ±0.5 pt per 0.1-wide window.

### D-11 Secondary outcome: penetration depth (AI→TEAM)
* **Problem.** In this short geometry aerosol reaches the target plane ~70 ms after release (90 %: 180 ms), so the
  primary outcome is flat in release time until F ≈ 0.9 (v001 kernels); timing barely matters.
* **Proposal.** Pre-declared secondary outcome D_V: aerosol must cross the plane early enough that ≥ V mL more air then
  enters the target branch before inhalation ends (lumped plug-flow downstream airway; V = 5, 10, 20 mL).
  Analogous to the bolus "volumetric front depth" / inhaled-volume-tracking concept in the literature.
* **Uncertain.** Plug-flow and no downstream deposition are strong simplifications.
* **TEAM decision (T-5):** D stays primary; D_V is secondary/exploratory until assessed in docs/PENETRATION_OUTCOME.md.

### D-12 Pre-registered split and objective (AI→TEAM)
* See docs/PREREGISTRATION.md (9 training, 8 held-out conditions; max-min objective; CVaR alternative only on
  training data; direct re-simulation with new seeds for all evaluation numbers).

### D-13 Inlet flux-weight normalisation (AI, bug found by the response-map test)
* **Problem found.** v001 map-vs-direct check (81 pairs, 1–3 µm): every |z| < 2 but a systematic bias, direct − map =
  −0.66 pts on average (late window −1.03 ± 0.57 pts). With exact superposition the mean should be 0.
* **Diagnosis.** Solver v1 renormalised the flux weights of each time step's new parcels to sum to the step's mass.
  Pulsed runs inject ~190 parcels per step (renormalisation harmless); continuous runs ~10 per step, where it partly
  cancels the weighting (one parcel per step → no weighting at all). The two run types therefore sampled the
  inlet differently.
* **Fix (v2, before any v002 particle run).** Weight w = 2(1 − r²/R²) applied without renormalisation; E[w] = 1 exactly
  for area-uniform positions, so expected mass is unchanged and measured introduced mass is still the denominator.
* **Test.** Repeat the map-vs-direct comparison on v002 (expected mean z ≈ 0). If the bias persists, the diagnosis is wrong.
