#!/bin/bash
# Progress and cost of a run (read-only).   bash cloud/aws/04_monitor.sh <run> [--watch]
set -euo pipefail
cd "$(dirname "$0")"
source ./config.env
RUN=${1:?run name}
show() {
  date
  aws ec2 describe-instances --region "$REGION" --filters "Name=tag:Run,Values=$RUN" \
    --query 'Reservations[].Instances[].[InstanceId,State.Name,LaunchTime,StateReason.Message]' --output table
  echo "== status"
  (aws s3 cp "s3://$BUCKET/$RUN/status.json" - 2>/dev/null || true) | python3 status.py || true
  echo "== cost";  python3 ledger.py "$BUCKET"
  echo "== guard (last lines)"; aws s3 cp "s3://$BUCKET/$RUN/project/logs/guard.log" - 2>/dev/null | tail -5 || true
}
if [ "${2:-}" = "--watch" ]; then while true; do clear; show; sleep 120; done; else show; fi
