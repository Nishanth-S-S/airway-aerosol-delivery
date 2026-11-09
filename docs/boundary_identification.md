# How the CFD boundaries were identified

The approved STL files contain **one un-named surface** each (Open CASCADE export), so the
inlet / outlets / walls had to be separated. This is done by `scripts/identify_boundaries.py`
(called automatically by `scripts/setup_geometry.py`).

## Rule

A triangle belongs to a cap only if **both** are true:

1. all 3 vertices are within **0.02 mm** of the cap plane (plane through the cap centre from `QA_report.json`, perpendicular to the branch axis);
2. its normal is parallel to the outward cap normal (|cos θ| > 0.999).

Everything else is `walls`. The script stops with an error if a cap is empty or its area differs from
π r² by more than 2 % - it never guesses.

| Boundary | Plane / centre (mm) | Outward normal | Meaning |
|---|---|---|---|
| `inlet` | z = 0, centre (0, 0, 0) | (0, 0, −1) | parent airway entrance (air enters, +Z flow) |
| `targetOutlet` | centre (30, 0, 91.96) | (sin30°, 0, cos30°) | **right / +X branch = target** |
| `comparisonOutlet` | centre (−30, 0, 91.96) | (−sin30°, 0, cos30°) | left / −X branch = comparison |
| `walls` | remaining surface | — | airway wall (no-slip, particles stick) |

## Results

| Geometry | inlet area err | target area err | comparison area err | wall triangles | measured min target Ø | at s |
|---|---|---|---|---|---|---|
| healthy | -0.01 % | -0.01 % | -0.01 % | 39074 | 6.00 mm | 14.2 mm |
| n20 | -0.01 % | -0.01 % | -0.01 % | 45726 | 4.80 mm | 20.0 mm |
| n40 | -0.01 % | -0.01 % | -0.01 % | 48230 | 3.60 mm | 20.0 mm |

Area errors are the faceting error of the STL (polygon vs circle).

**Important — what "20 % / 40 % narrowing" means here.** The QA report gives minimum diameters of
4.8 mm and 3.6 mm in a 6 mm branch, i.e. a 20 % / 40 % reduction in **diameter**. In cross-sectional
**area** these are 36 % and 64 % reductions. The study labels follow the diameter convention of the
geometry package; quote both in any write-up.

The narrowing position s (distance along the target-branch centre-line from the bifurcation point
(0.0, 0.0, 40.0) mm) was measured from the STL vertices and matches the README (14–26 mm, centre 20 mm).

Figures: `results/figures/geometry_healthy.png`, `geometry_n20.png`, `geometry_n40.png`

## Target entry plane

Perpendicular to the target-branch axis at s = **28.0 mm** (i.e. 2 mm past the end of the narrowing),
disc radius 3.3 mm. Defined in `config/experiment.yaml -> regions` and
used identically for all three geometries (the healthy case uses the same s-position).
