#!/bin/bash
# Upload the inputs of one run to s3://$BUCKET/<run>/project (encrypted in transit and at rest; incremental).
#   bash cloud/aws/02_upload.sh <run-name> benchmark
#   bash cloud/aws/02_upload.sh <run-name> production     (refused unless the production mesh is approved)
# Uploads code, config, frozen geometry, base cases, the particle solver (source + the Mac-built binary), the meshes
# and the Mac verification data each plan needs. It NEVER uploads coarse-mesh v002 results (the particle queue would
# otherwise skip them as "done"). Writes a SHA-256 manifest (cloud/results/upload_manifest_<run>.json, also on S3).
set -euo pipefail
cd "$(dirname "$0")"
source ./config.env
RUN=${1:?run name}; PLAN=${2:?benchmark|production}
cd ../..                                            # project root
P="s3://$BUCKET/$RUN/project"
paths=(scripts config base_cases tools docs cloud geometry validation/04_mesh_independence cases/mesh/n40_medium cases/mesh/n40_fine)
if [ "$PLAN" = "benchmark" ]; then
  paths+=(cases/airflow/V_MESH_medium_T_N40_SYM
          cases/particles/MAP_V_MESH_medium_T_N40_SYM_P01 cases/particles/MAP_V_MESH_medium_T_N40_SYM_P03
          cases/particles/MAP_V_MESH_medium_T_N40_SYM_P05
          cases/airflow/V_MESH_fine_T_N40_SYM/logs)          # Mac fine-case log = per-step reference for B6
elif [ "$PLAN" = "production" ]; then
  python3 - <<'PY'
import json, sys, yaml
d = json.load(open("validation/04_mesh_independence/results/MESH_DECISION.json"))
lvl = yaml.safe_load(open("config/experiment.yaml"))["mesh"]["level"]
if d.get("approved") is not True:
    sys.exit("production refused: MESH_DECISION.json is not approved")
if d.get("production_level") != lvl:
    sys.exit(f"production refused: config mesh.level={lvl} but the approved production level is {d.get('production_level')}")
print(f"production mesh: {lvl} (approved {d.get('decided')})")
PY
  LVL=$(python3 -c 'import yaml;print(yaml.safe_load(open("config/experiment.yaml"))["mesh"]["level"])')
  for d in cases/airflow/V_MESH_*_T_N40_SYM cases/particles/MAP_V_MESH_*_T_N40_SYM_P0?; do
    [ -d "$d" ] && paths+=("$d")
  done
  [ -d "cases/mesh/n40_$LVL" ] && paths+=("cases/mesh/n40_$LVL")
else
  echo "plan must be benchmark or production"; exit 1
fi
python3 cloud/tools/manifest.py "$RUN" "${paths[@]}"
for p in "${paths[@]}"; do
  echo "upload $p"
  aws s3 sync "$p" "$P/$p" --only-show-errors --exclude "*processor*" --exclude "*.pyc" --exclude "*state.env" \
    --exclude "*config.env" --exclude "*results/benchmark/*"
done
aws s3 cp "cloud/results/upload_manifest_$RUN.json" "$P/cloud/results/upload_manifest_$RUN.json" --only-show-errors
echo "uploaded run $RUN ($PLAN) to $P"
