#!/bin/bash
# Start a desktop command in the background (keeps running after the terminal is closed); output -> logs/desktop_<cmd>.out
#   bash local/run.sh stage1        bash local/run.sh production        (status / stop / check run in the foreground)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${AIRWAY_PY:-$HOME/micromamba/envs/airway/bin/python3}
[ -x "$PY" ] || { echo "Python env not found at $PY - run: bash local/setup_linux.sh"; exit 1; }
[ -f local/desktop.env ] && source local/desktop.env      # optional: AIRWAY_CORE_GROUPS=... (WSL2), written by setup
export AIRWAY_CORE_GROUPS=${AIRWAY_CORE_GROUPS:-}
CMD=${1:-status}
mkdir -p logs
case "$CMD" in
  stage1|production)
    if [ -f "logs/desktop_$CMD.pid" ] && kill -0 "$(cat "logs/desktop_$CMD.pid")" 2>/dev/null; then
      echo "$CMD is already running (pid $(cat "logs/desktop_$CMD.pid"))"; exit 1
    fi
    nohup "$PY" local/desktop.py "$CMD" >> "logs/desktop_$CMD.out" 2>&1 &
    echo $! > "logs/desktop_$CMD.pid"
    echo "started $CMD (pid $!). Progress: bash local/run.sh status   Log: logs/desktop_$CMD.out"
    ;;
  *)
    exec "$PY" local/desktop.py "$@"
    ;;
esac
