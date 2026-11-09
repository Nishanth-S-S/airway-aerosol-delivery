| # | Criterion | Measured (coarse vs medium) | Threshold | Result |
|---|---|---|---|---|
| C1 | Airflow conservation | imbalance 9.9e-07 % / 3.2e-06 % | < 0.5 % each | PASS |
| C2 | Target-branch flow fraction | 39.07 vs 38.50 % (Δ +0.57 pts) | ≤ 0.5 pts | FAIL |
| C3 | Pressure drop | peak 2.637 vs 2.615 Pa (+0.8 %); mean 1.856 vs 1.861 Pa (-0.3 %) | ≤ 5 % each | PASS |
| C4a | Velocity near junction (L2 of \|U\|, t≈1.00 s) | 6.2 % (2254 points) | ≤ 10 % | PASS |
| C4b | Velocity in narrowing/jet | L2 36.5 %; jet max 2.994 vs 3.065 m/s (-2.3 %) | ≤ 10 %; ≤ 5 % | FAIL |
| C5 | Target delivery, 1 µm | 34.81 vs 36.09 % (Δ -1.28 pts) | ≤ 1.00 pts | FAIL |
| C5 | Target delivery, 3 µm | 34.81 vs 36.11 % (Δ -1.30 pts) | ≤ 1.00 pts | FAIL |
| C5 | Target delivery, 5 µm | 34.67 vs 36.02 % (Δ -1.35 pts) | ≤ 1.00 pts | FAIL |
| C6 | Total deposition, 1 µm | 4.44 vs 0.49 % (Δ +3.96 pts) | ≤ 1.00 pts | FAIL |
| C6 | Total deposition, 3 µm | 4.72 vs 0.78 % (Δ +3.94 pts) | ≤ 1.00 pts | FAIL |
| C6 | Total deposition, 5 µm | 5.34 vs 1.64 % (Δ +3.70 pts) | ≤ 1.00 pts | FAIL |
| C7 | Release-time kernel, 3 µm (not gating) | 6/10 bins within 2 SE | ≥ 9/10 | FAIL |
