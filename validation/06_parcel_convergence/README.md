# 06 — Parcel-count convergence

Same physical case with 2 500 … 40 000 computational parcels (same introduced mass every time).
Target delivery should stop changing beyond the chosen `particles.parcels_per_case`.

```bash
python scripts/run_validation.py parcels --parcels-list 2500 5000 10000 20000 40000
```
