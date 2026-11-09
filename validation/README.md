# Validation framework

**Nothing in this project is scientifically validated yet.** These folders hold the studies that must be run
and reviewed before the 144-case results can be trusted. Every study is driven by one command:

```bash
python scripts/run_validation.py --list
```

| # | Folder | What it shows | Status |
|---|---|---|---|
| 1 | `01_straight_tube_analytical` | Poiseuille Δp / velocity, Pich settling | see `results/summary.json` |
| 2 | `02_airflow_conservation` | Q_in = Q_out for every airflow run | automatic per run |
| 3 | `03_particle_mass_conservation` | introduced = deposited + escaped + suspended; tracer floor | automatic per run |
| 4 | `04_mesh_independence` | coarse / medium / fine + GCI | prepared, not run |
| 5 | `05_timestep_independence` | Courant 0.5–5; particle dt | prepared, not run |
| 6 | `06_parcel_convergence` | 2.5 k – 40 k parcels | prepared, not run |
| 7 | `07_random_seeds` | seed-to-seed scatter | prepared, not run |
| 8 | `08_experimental_benchmark` | comparison with measured data you supply | needs data |
| 9 | `09_outlet_bc_sensitivity` | prescribed flow splits vs equal pressure | prepared, not run |

The HTML report (`results/report.html`) shows the current state of each study.
