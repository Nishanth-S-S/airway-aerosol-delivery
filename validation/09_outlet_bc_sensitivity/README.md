# 09 — Alternate outlet boundary conditions

Baseline: both outlets at the same pressure (flow split decided by the geometry alone).
Alternatives: the target outlet is given a **prescribed share** of the inlet flow (e.g. 40 / 50 / 60 %),
the comparison outlet stays at p = 0. Shows how strongly the answer depends on downstream (lung) resistance.

```bash
python scripts/run_validation.py outletbc --geometry n40 --waveform symmetric --splits 0.4 0.5 0.6
```
