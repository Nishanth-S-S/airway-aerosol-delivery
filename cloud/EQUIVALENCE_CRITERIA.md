# Cloud-vs-Mac scientific equivalence criteria (fixed 2026-11-06, before any cloud run)

The cloud may be used for production results only if every test below passes. All tests are run during the
paid benchmark by `cloud/bench/bench.py`; the comparison is `cloud/bench/equivalence.py`. Thresholds are fixed here
and are not changed after seeing results. A failure stops the move to the cloud until it is diagnosed.

Scale reference: over 0.02 s of simulated time the medium-mesh velocity field changes by 0.1 % (relative L2,
measured from the Mac run at t = 1.00 to 1.02 s). Field tolerances are therefore set far below that.

| Test | What is compared | Pass if |
|---|---|---|
| E1 Toolchain identity | OpenFOAM image digest, SHA-256 of pimpleFoam / decomposePar / reconstructPar / snappyHexMesh / core libraries; particle-solver source hash; Python package versions | all identical to `cloud/toolchain_reference.json` (the compiled airwayParcelFoam binary hash is reported; behaviour is tested by E2) |
| E2 Particle solver, same airflow | Cloud re-run of `MAP_V_MESH_medium_T_N40_SYM_P03` (seed 1, 100 000 parcels) on the uploaded Mac airflow | injected parcels identical; delivery, deposition, suspended and escaped mass within 0.01 percentage points of the Mac result |
| E3 Mesh reproducibility | Cloud snappyHexMesh of n40 / medium vs the Mac mesh | cell count identical and checkMesh quality metrics within 0.1 %; otherwise the Mac meshes are used for n40 and the difference is reported (meshes of other geometries are always made on the cloud by the same gated procedure) |
| E4 Parallel decomposition | Restart segments (t = 0.24, 1.00, 2.00 to the next 0.02 s write) from the Mac state, run with 1, 2, 4, 8, 16 ranks, compared with the Mac's own field at the end time (Mac used 8 ranks) | relative L2 difference of U and p <= 1e-4 for every rank count, and <= 10 % of the field change over the segment |
| E5 Interruption / restart | Segment 1.00 to 1.02 s, 8 ranks: uninterrupted vs stopped mid-run by the Spot-interruption mechanism (stopAt writeNow) and resumed | relative L2 difference of U and p <= 1e-4; the off-schedule checkpoint time is moved out of the snapshot set |
| E6 Complete case | Full 0 to 3 s medium T_N40_SYM on the cloud (production rank count) vs the Mac verification case, including reconstruction, QA and 1/3/5 um response maps (seed 1) | target split within 0.05 points; peak and mean pressure drop within 0.5 %; relative L2 of U <= 2 % at t = 0.5, 1.0, 1.5 s; delivery and deposition within max(0.3 points, 2 x combined SE) at each size; release-time kernel (3 um) within 2 SE in >= 9 of 10 bins |

Notes
* Bitwise identity is not expected: the cloud CPU (AMD Zen 4) may use different vectorised maths-library paths than the
  Mac (Intel), and different rank counts change the order of floating-point sums in the pressure solver. E4 and E5
  measure the size of those differences directly.
* E6 is the end-to-end test of the whole cloud path (case generation, decomposition, solver, reconstruction, QA,
  particle maps). If medium is the adopted production mesh, the passing E6 case is the production T_N40_SYM case.
* No mesh level, solver tolerance, time-step control, physics or particle setting differs between Mac and cloud.
