# Geometry QA — approved v001 models and corrected v002

Checks run by `scripts/setup_geometry.py`, `scripts/identify_boundaries.py` and `scripts/geometry_qa.py`.
Figures: `results/figures/geometry_qa/junction_v001_vs_v002.png`, `junction_v001.png`.

## What is correct in v001 (all three models)

| Check | Result |
|---|---|
| Dimensions vs README / QA report | parent 8 mm × 40 mm, daughters 6 mm × 60 mm at ±30°, outlet centres exact |
| Volume vs QA report | within 0.02 % |
| Narrowing | concentric (min/max radius within 0.05 mm at every slice), minimum 4.80 / 3.60 mm at s = 20.0 mm, 14–26 mm |
| N20 vs N40 STEP | genuinely different files (same byte size by coincidence) |
| Comparison branch | identical in all three models (differences ≤ 0.18 mm = tessellation only) |
| Healthy model symmetry | mirror-symmetric about x = 0 within 0.06 mm |
| Caps | flat, perpendicular to the axes, areas within 0.01 % of π r² |

## Defects found in v001 (identical in healthy, N20 and N40)

1. **Two zero-area triangles** at the junction saddle points (0, ±3, 40) mm → STL not watertight
   (2 open + 2 non-manifold edges). *Fixed losslessly* by `setup_geometry.py` (`airway_clean.stl`).
2. **Flat shelf at z = 40 mm facing the flow.** The 8 mm parent tube simply ends in a flat annular face
   (17.6 mm², 35 % of the parent cross-section) from which the two 6 mm cylinders start. The lumen area
   drops abruptly from 50.3 to 32.6 mm² — a step contraction that a real airway does not have.
   In the CFD it is a stagnation surface: in `P03_CONT_HLT_SYM` most "upstream" deposition sits on it.
3. **Daughter cylinders protrude through the parent wall.** The two branch cylinders were extended
   backwards past the bifurcation point and poke out of the parent tube, leaving pockets up to
   0.42 mm deep at z = 37.4–38.7 mm on the ±x sides (lumen area bump to 53 mm² just below the shelf).

Defects 2 and 3 come from building the junction as a plain union of three cylinders (STEP faces: 6 planes,
3 of which are the inlet/outlets; the rest belong to the shelf). The README's 0.5 mm fillet only rounds
the carina and these edges; it does not create a transition.

## v002 (corrected) — `scripts/build_geometry_v002.py`

* Same parent, daughters, angles, outlet centres and **exactly the measured v001 narrowing profile**
  (difference ≤ 0.01 mm).
* Parent tube ends in a hemispherical dome at the bifurcation point that blends smoothly
  (1 mm blend radius) into the two daughters; carina blend radius 0.5 mm (as the v001 fillet).
* No flat flow-facing wall (0 mm² vs 17.6 mm²); maximum radius below the junction 4.04 mm (vs 4.42 mm).
* Inlet/outlets cut exactly flat (cap areas within 0.14 % of π r²); watertight, manifold, ~143 k triangles.
* Volume: +0.3 % vs v001.

**Limitation:** v002 exists as STL only (implicit surface + marching cubes, 0.25 mm voxels, shape error
~0.003 mm). To get a matching CAD/STEP, rebuild the junction in Onshape as a loft from the parent circle
into the two branch starts (and do not extend the branch cylinders back past the bifurcation point).

## Choosing the version

`config/experiment.yaml → geometry.version: v001 | v002`. All meshing/CFD scripts read the patch file for
that version (`geometry/<g>/airway_patches_m.stl` for v001, `airway_patches_m_v002.stl` for v002).
