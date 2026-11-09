# Airway aerosol delivery — CFD workflow

> **Running it on a Windows PC: download this repo (Code → Download ZIP), open the `windows` folder and double-click
> `START_HERE.bat`.** Step-by-step: [windows/INSTRUCTIONS.md](windows/INSTRUCTIONS.md).
>
> Running the remaining v002 study on the desktop (Ryzen 9 9950X3D), technical details: [local/README.md](local/README.md).
> Large data (meshes, saved cases, geometry) is not in this repo; it is moved with `local/bundle.py`.
> Cloud (AWS) path: [cloud/README.md](cloud/README.md).

OpenFOAM v2406 (run through Docker image `opencfd/openfoam-default:2406`), Python, pandas, matplotlib.
All settings are in `config/experiment.yaml`; reasoning is in `docs/MODEL_DECISIONS.md`.

## Commands (run from this folder)

```bash
python scripts/setup_geometry.py                       # unzip, check, split inlet/outlets/walls
python scripts/generate_waveforms.py                   # breathing curves + release windows
python scripts/estimate_physics.py                     # Re, Cunningham, Brownian -> docs/MODEL_DECISIONS.md
python scripts/mesh_geometry.py --all                  # blockMesh/snappyHexMesh/checkMesh with quality gate
python scripts/run_airflow_cases.py --case healthy_constant
python scripts/run_airflow_cases.py --case healthy_symmetric
python scripts/run_airflow_cases.py --all              # refused until healthy_symmetric passes QA
python scripts/generate_particle_cases.py --all        # 144 particle case folders
python scripts/run_particle_cases.py --case P03_CONT_HLT_SYM
python scripts/run_particle_cases.py --all --jobs 4    # refused until P03_CONT_HLT_SYM passes QA
python scripts/extract_results.py --all                # results/results.csv
python scripts/run_validation.py --list                # validation studies
python scripts/build_report.py                         # results/report.html (double-click to open)
```

Docker Desktop must be running. Status of every case: `results/run_status.csv`.

## Status (2026-11-02)

**Executed with OpenFOAM (real solver output):**
- geometry setup + boundary split (healthy, N20, N40); meshes coarse + medium, all PASSED checkMesh
- `healthy_constant` airflow — PASSED (imbalance 2e-8 %, 50/50 split, steady dp 1.01 Pa)
- `healthy_symmetric` airflow, full 2 s breath + 1 s settling — PASSED (imbalance 7e-7 %, peak dp 2.32 Pa)
- `P03_CONT_HLT_SYM` particles — PASSED: target delivery 44.1 %, deposition 6.6 %, suspended 7.5 %,
  mass-balance error 4e-7 %
- validation 01 straight tube: dp -1.0 %, centre-line velocity -0.9 % vs Poiseuille;
  10 um settling 29.2 % vs Pich 29.5 %
- validation 02/03 conservation summaries

**Prepared, not run:** remaining 8 airflow cases, 143 particle cases (folders generated), validation
04-09. Study runs use the PROVISIONAL `coarse` mesh and max Courant 3 until validation 04/05 are done.
Nothing is scientifically validated.

**Next step:**
```bash
python scripts/run_airflow_cases.py --all --skip-completed      # ~30 min each on this Mac
```
