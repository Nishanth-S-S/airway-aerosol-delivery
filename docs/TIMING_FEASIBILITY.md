# Can this model reveal a release-timing effect?

Data: v001 archive (144 particle cases; release-time kernels from the 27 continuous runs at 1–3 µm;
5 µm v001 runs cannot be decomposed, see D-07). Scripts: `scripts/response_map_check.py`,
`scripts/lib/response_map.py`. Figures: `results/figures/response_map/v001/`. Tables:
`results/tables/release_time_kernels_v001.csv`, `transit_times_v001.csv`, `response_map_check_v001.*`.

## 1. Findings (measured)

| Question | Answer from the data |
|---|---|
| Transit time inlet → target plane | median 54–71 ms, 90th percentile 155–184 ms (all sizes, geometries, waveforms) vs a 2000 ms inhalation |
| Does release timing change target-plane crossing? | **No, except at the very end.** G(F) is flat within Monte Carlo noise from F = 0 to ≈ 0.9 (healthy ≈ 46 %, N20 ≈ 44 %, N40 ≈ 36 %), then falls to ≈ 6–10 % for F > 0.95 |
| Why the drop near F = 1? | Aerosol released in the last ≈ 5–10 % of the breath is still in the parent tube when inhalation stops (still airborne at 3 s: 35 % for F ≈ 0.93, 97 % for F ≈ 0.98) |
| Early vs middle vs late (original protocol) | All three windows (F 0.1–0.6) lie in the flat region; their differences (≲ 1 pt) are within Monte Carlo error |
| Continuous release | ≈ 2–3 pts lower than the pulses, entirely from the F > 0.9 part of the breath |
| Particle size 1 vs 2 vs 3 µm | Curves practically identical (Stokes 0.004–0.03: particles follow the air). Only 5 µm differs noticeably |
| Is wall deposition analysable? | Total deposition ≈ 6–8 %, mostly at the junction (v001 shelf) and carina; target-wall deposition < 1 %, too small to optimise reliably at 20 000 parcels |
| Is the target plane too close to the narrowing? | It is 2 mm past the narrowing; moving it downstream would add ~30 ms of transit and not change the conclusion |
| Does the 1-s observation period favour some windows? | Only F > 0.9: their aerosol cannot reach the plane before flow stops. Windows ending before F ≈ 0.9 are unaffected |

**Conclusion.** The short geometry (volume upstream of the target plane ≈ 3–4 mL vs 66.7 mL inspired) makes the
primary outcome almost insensitive to release timing. Optimising s on the primary outcome would select among
statistically tied options; the hypothesis could not be tested meaningfully with that outcome alone.

## 2. Smallest justified modification (implemented as a pre-declared secondary outcome, no new CFD)

**Penetration delivery D_V**: the aerosol must cross the target plane early enough that the target branch then
inhales at least V mL more air before inhalation ends (lumped plug-flow downstream airway). This represents the
airway volume beyond the narrowing that the aerosol must still traverse — the same idea as the bolus
"volumetric front depth" / inhaled-volume tracking in the literature (docs/LITERATURE_REVIEW.md).

v001, 3 µm, kernel in F-bins of 0.1 (%):

| condition | outcome | 0.05 | 0.15 | 0.25 | 0.35 | 0.45 | 0.55 | 0.65 | 0.75 | 0.85 | 0.95 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| healthy, symmetric (target branch inhales 33.2 mL) | D | 47.2 | 47.4 | 47.3 | 46.0 | 45.8 | 47.6 | 43.8 | 43.8 | 46.3 | 25.6 |
|  | D_10mL | 47.1 | 47.4 | 47.2 | 45.9 | 45.7 | 47.0 | 22.7 | 0 | 0 | 0 |
| N40, symmetric (26.0 mL) | D | 37.2 | 37.9 | 35.2 | 34.6 | 36.0 | 36.1 | 36.1 | 34.9 | 36.5 | 17.8 |
|  | D_10mL | 37.1 | 37.8 | 35.2 | 34.4 | 35.5 | 23.0 | 0 | 0 | 0 | 0 |

D_V produces a sharp cut-off F_c ≈ 1 − V / V_target-branch that is **the same for all three waveforms** (because F
already tracks inspired volume) but **moves with breath volume and branch flow share** — i.e. with mean flow and
narrowing. This makes robustness to flow/anatomy a real question.

## 3. Consequence for the optimisation (important, not yet resolved)

If releasing early carries no penalty — which is what v001 shows for 1–3 µm — then the robust optimum of D_V is a
corner solution: release as early as the device allows (s = s_min). A max-min optimiser is then not needed to find
it, and "single-condition optimisation" differs from it only because it is indifferent among all s below its own
cut-off. Whether a genuine trade-off exists (e.g. 5 µm deposition depending on the flow rate at release, or a
device constraint s ≥ s_min > 0) will be checked on the v002 response maps before any optimisation result is
interpreted. This is reported as a limitation, not hidden.

## 4. Statistical note
All runs used random seed 1, so injection positions are shared across sizes and geometries (common random numbers):
the same up/down pattern appears in every kernel. This helps paired comparisons but means sizes and geometries are
not independent samples. v002 maps use 100 000 parcels; evaluation runs use fresh seeds.
