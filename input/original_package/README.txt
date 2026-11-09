ONSHAPE AIRWAY IMPORT PACKAGE

DIRECT IMPORT FILES (STEP):
  Healthy_Airway_APPROVED_v001.step
  Airway_N20_APPROVED_v001.step
  Airway_N40_APPROVED_v001.step

MAYA / MESH COPIES (STL):
  Healthy_Airway_APPROVED_v001.stl
  Airway_N20_APPROVED_v001.stl
  Airway_N40_APPROVED_v001.stl

EXTRA:
  Airway_0_20_40_Comparison.step  (three versions spaced apart)
  QA_report.json

UNITS: millimeters

GEOMETRY:
  Parent airway: 8 mm diameter, 40 mm long, +Z direction.
  Daughter branches: 6 mm diameter, 60 mm centerline length.
  Branches: +/-30 degrees from parent axis in the X-Z plane.
  Right/+X branch is the target branch.
  N20: 12 mm constriction from 14-26 mm, center 20 mm, minimum diameter 4.8 mm.
  N40: 12 mm constriction from 14-26 mm, center 20 mm, minimum diameter 3.6 mm.
  Junction: fused into one solid and blended with a 0.5 mm fillet.

ONSHAPE:
  Create/open a document -> click + at bottom-left -> Import -> choose a .step file.
  Onshape should create an imported Part Studio containing one solid part.

NOTE:
  STEP is a neutral CAD solid, so it imports as a solid body rather than an editable feature-history tree.
