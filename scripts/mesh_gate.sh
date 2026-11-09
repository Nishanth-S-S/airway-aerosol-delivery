#!/bin/bash
# Mesh-decision gate: when the medium-mesh airflow has written its QA report, stop the airflow-queue coordinator
# (and any airflow/mesh container it may have just started) so no further airflow runs before the mesh decision.
# The particle queue is left running (it must produce the medium-mesh maps). Completed cases are untouched.
cd "$(dirname "$0")/.."
until [ -f cases/airflow/V_MESH_medium_T_N40_SYM/qa_report.json ]; do sleep 1; done
pkill -f "run_study_v002.py airflow"
sleep 2
for c in $(docker ps -q); do
  cmd=$(docker inspect --format '{{join .Config.Cmd " "}}' "$c")
  case "$cmd" in
    *"/work/cases/airflow/"*|*"/work/cases/mesh/"*) echo "stopping container $c: ${cmd:0:120}"; docker kill "$c" >/dev/null ;;
  esac
done
echo "$(date '+%Y-%m-%d %H:%M:%S') GATE: airflow queue paused for the mesh decision" | tee -a logs/study_v002.log
