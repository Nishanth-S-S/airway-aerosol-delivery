# 08 — Experimental benchmark comparison

**No experimental data is bundled and none has been invented.** To compare, put a CSV in `data/` with:

| column | meaning |
|---|---|
| `label` | short description of the measurement |
| `particle_size_um` or `stokes_number` | condition |
| `measured_deposition_percent` | measured value |
| `measured_uncertainty_percent` | optional |
| `cfd_case_id` | the case in `results/results.csv` you consider equivalent |

```bash
python scripts/run_validation.py benchmark --data validation/08_experimental_benchmark/data/my_benchmark.csv
```

Candidate literature to look for (check the papers yourself before relying on them): bench-top
deposition measurements in symmetric single/double-bifurcation airway models (e.g. work by C. S. Kim and
co-workers in *Aerosol Science and Technology* / *J. Aerosol Science*), and published
impaction-efficiency-vs-Stokes-number correlations for bifurcations. A matching benchmark generally needs
a similar geometry, steady inspiratory flow and monodisperse particles, so a dedicated benchmark geometry
may be required.
