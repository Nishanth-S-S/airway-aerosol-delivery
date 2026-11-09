# 01 — Straight-tube analytical verification

**Purpose.** Prove the solver + mesh + boundary-condition chain reproduces exact solutions.

* Airflow: fully developed laminar (Poiseuille) flow in a straight 6 mm × 60 mm tube.
  Exact: centre-line velocity = 2·Ū and Δp = 128 µ L Q / (π D⁴).
* Particles: gravitational deposition in a **horizontal** tube with Poiseuille flow
  (gravity perpendicular to the axis) vs. the Pich (1972) formula
  `P = 2/π [2ε√(1−ε^(2/3)) − ε^(1/3)√(1−ε^(2/3)) + arcsin(ε^(1/3))]`, `ε = 3 L v_s / (4 D Ū)`.

The tube STL is generated automatically (inlet / outlet split into two halves so the normal
base case can be reused unchanged).

```bash
python scripts/run_validation.py tube                     # default 0.2 L/min, 10 um particles
python scripts/run_validation.py tube --level medium
```

**Acceptance (suggested).** Δp and centre-line velocity within 2 %; deposition within ~10 % relative of Pich.
Results: `results/summary.json`, `results/tube_verification.png`.
