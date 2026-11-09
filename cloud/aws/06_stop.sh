#!/bin/bash
# Stop a run early.
#   bash cloud/aws/06_stop.sh <run> --graceful    running cases write their state, everything is copied to S3, then the
#                                                 instance powers itself off (terminates) - resumable later
#   bash cloud/aws/06_stop.sh <run> --terminate   immediate; work since the last 10-minute copy to S3 is lost
set -euo pipefail
cd "$(dirname "$0")"
source ./config.env
RUN=${1:?run name}; MODE=${2:?--graceful or --terminate}
IDS=$(aws ec2 describe-instances --region "$REGION" --filters "Name=tag:Run,Values=$RUN" \
  "Name=instance-state-name,Values=pending,running" --query 'Reservations[].Instances[].InstanceId' --output text)
[ -n "$IDS" ] || { echo "no running instance for run $RUN"; exit 0; }
if [ "$MODE" = "--graceful" ]; then
  aws ssm send-command --region "$REGION" --instance-ids $IDS --document-name AWS-RunShellScript \
    --parameters 'commands=["touch /data/DRAIN","(sleep 60; while pgrep -f \"job_airflow.py|bench.py\" >/dev/null; do sleep 10; done; bash /data/project/cloud/instance/sync.sh cases logs results validation docs cloud/results; shutdown -h now) >/dev/null 2>&1 &"]' \
    --query 'Command.CommandId' --output text
  echo "drain requested on $IDS; watch with 04_monitor.sh $RUN"
else
  aws ec2 terminate-instances --region "$REGION" --instance-ids $IDS --output table
fi
