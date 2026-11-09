# 05 — Time-step independence

Airflow: maximum Courant number 0.5 / 1 / 3 / 5 (PIMPLE outer correctors are switched on for Co > 1).
Particles: cloud time step 2 ms / 1 ms / 0.5 ms on the same stored airflow.

```bash
python scripts/run_validation.py timestep --co 0.5 1 3 5 --particle-dt 0.002 0.001 0.0005
```
The production setting (`airflow.max_courant: 3`) is PROVISIONAL until this study is run.
