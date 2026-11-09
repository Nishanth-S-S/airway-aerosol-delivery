# Mesh-convergence criteria (v002) — fixed 2026-11-05 17:55, before any medium-mesh result was viewed

Comparison: coarse (study level, ~60 k cells, no layers) vs medium (~240 k cells, 3 boundary layers), condition
T_N40_SYM (40 % narrowing, symmetric breathing, 2 L/min) — the narrowest throat and strongest jet, i.e. the case most
likely to be under-resolved. Particle comparisons use continuous-release runs with 100 000 parcels on each mesh
(same seed) for 1, 3 and 5 µm.

| # | Quantity | Criterion (coarse vs medium) |
|---|---|---|
| C1 | Airflow conservation | both runs: time-averaged imbalance < 0.5 % (QA) |
| C2 | Target-branch flow fraction (inhalation average) | abs. difference ≤ 0.5 percentage points |
| C3 | Pressure drop | peak and mean inlet-to-outlet Δp: relative difference ≤ 5 % |
| C4a | Velocity field near the junction (y = 0 section, peak-flow snapshot) | relative L2 difference of \|U\| on common sample points ≤ 10 % |
| C4b | Velocity field in the narrowing and jet (s = 10–40 mm, target branch) | relative L2 difference ≤ 10 %, and maximum jet speed within 5 % |
| C5 | Target delivery (primary outcome) per size | abs. difference ≤ max(1 pt, 2 × combined Monte Carlo SE) |
| C6 | Total wall deposition per size | abs. difference ≤ max(1 pt, 2 × combined SE); regional deposition reported |
| C7 | Release-time kernel G(F), 10 bins, 3 µm | ≥ 9 of 10 bins within 2 × combined SE |

**Decision rule.** All of C1–C6 pass → the coarse level is adequate for the study's outcomes and the existing coarse
runs are kept. C7 and regional deposition are reported but not gating (target-wall deposition is < 1 % and too noisy
to gate on). If any of C1–C6 fails → run the fine level on the same condition, estimate the discretisation error
(Richardson/GCI where monotone), and repeat on the passing level every simulation whose outcome depends on the failed
quantity (airflow-only failure → all airflow + particle runs; particle-only failure → particle runs).
Velocity sampling: |U| interpolated from both meshes' y = 0 cut-plane cells onto the same 0.2 mm grid points that lie
inside both lumens, at the write time nearest peak inlet flow (t = 1.0 s).
