# 02 — Airflow conservation

Every airflow run already checks |Q_in − (Q_target + Q_comparison)| automatically
(`config/experiment.yaml → qa.airflow_mass_imbalance_percent`). This study collects all of them.

```bash
python scripts/run_validation.py conservation
```
Output: `results/airflow_conservation.csv`, `results/summary.json`.
