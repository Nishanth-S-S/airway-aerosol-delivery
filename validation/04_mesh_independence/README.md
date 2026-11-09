# 04 — Mesh independence

Runs the same airflow (+ the 3 µm continuous particle case) on the `coarse`, `medium`, `fine` mesh
levels defined in `config/experiment.yaml → mesh.levels`, then reports peak Δp, branch flow split and
target delivery vs. cell count, and a Roache grid-convergence index (GCI) from the three levels.

```bash
python scripts/run_validation.py mesh --geometry n40 --waveform symmetric          # hardest case: narrowest throat
python scripts/run_validation.py mesh --geometry healthy --levels coarse medium fine
```
Then set `mesh.level` in the config to the level that is converged.

**Cost warning (measured on this Mac via Docker):** about 6 µs per cell per time step. `medium` (~240 k cells)
≈ several hours per 3-s breath; `fine` more. Run overnight.
