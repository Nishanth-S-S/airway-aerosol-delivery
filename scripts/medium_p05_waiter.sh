#!/bin/bash
# Adds the 5 um medium-mesh map once the medium airflow has passed QA (mesh-convergence criterion C5/C6).
cd "$(dirname "$0")/.."
until [ -f cases/airflow/V_MESH_medium_T_N40_SYM/qa_report.json ]; do sleep 60; done
python3 - <<'PY'
import sys; sys.path.insert(0,'scripts')
import run_study_v002 as S
from lib.common import load_config
from lib.conditions import all_conditions
cfg=load_config(); c=[c for c in all_conditions() if c['id']=='T_N40_SYM'][0]
S.particle_job(cfg, c, 'V_MESH_medium_T_N40_SYM', 5, 'continuous', 100000, 1, 'MAP_V_MESH_medium_T_N40_SYM_P05')
PY
