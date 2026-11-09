#!/bin/bash
# Safety guard on the instance (started by bootstrap.sh, runs as root):
#   * Spot interruption notice (IMDSv2, polled every 5 s) -> /data/DRAIN: running airflow cases write their state and
#     stop (stopAt writeNow); the data are copied to S3 inside the 2-minute notice window.
#   * Time/budget cutoff at HOURS_CAP_MIN - DRAIN_MARGIN_MIN -> /data/DRAIN, wait (max 20 min) for the runner to
#     checkpoint, copy everything to S3, power off (instance-initiated shutdown = terminate). A hard `shutdown` timer set
#     at boot (bootstrap.sh) is the backstop if this script ever fails.
#   * Every 10 min: incremental copy of all case data (incl. decomposed checkpoints of running cases) to S3.
#   * Every 60 s: status + cost ledger (elapsed hours x launch Spot price; x max price = upper bound) to S3.
set -uo pipefail
source /etc/airway.env
LOG=/data/project/logs/guard.log
mkdir -p /data/project/logs
log() { echo "$(date '+%F %T') GUARD $*" | tee -a "$LOG"; }
token() { curl -s -m 2 -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300"; }
IID=$(curl -s -m 2 -H "X-aws-ec2-metadata-token: $(token)" http://169.254.169.254/latest/meta-data/instance-id)
BOOT=$(date +%s)
CUT=$(( BOOT + HOURS_CAP_MIN * 60 - DRAIN_MARGIN_MIN * 60 ))
last_sync=$BOOT
last_ledger=0
draining=0
log "started: instance $IID, cap ${HOURS_CAP_MIN} min, drain at $(date -d @"$CUT" '+%F %T'), launch price \$${LAUNCH_PRICE}/h, max \$${MAX_PRICE}/h"

finish_and_poweroff() {
  for _ in $(seq 1 120); do                       # up to 20 min for running cases to write their state
    st=$(jq -r .state /data/project/logs/cloud_status.json 2>/dev/null || echo none)
    if [ "$st" = "drained" ] || [ "$st" = "finished" ]; then break; fi
    if ! pgrep -f "cloud_runner.py|bench.py" >/dev/null; then break; fi
    sleep 10
  done
  bash /data/project/cloud/instance/sync.sh cases logs results validation docs cloud/results
  log "$1: data copied to S3; powering off"
  aws s3 cp "$LOG" "s3://${BUCKET}/${RUN}/project/logs/guard.log" --only-show-errors
  shutdown -h now
}

while true; do
  now=$(date +%s)
  code=$(curl -s -m 2 -o /tmp/ia.json -w '%{http_code}' -H "X-aws-ec2-metadata-token: $(token)" \
         http://169.254.169.254/latest/meta-data/spot/instance-action)
  if [ "$code" = "200" ] && [ $draining -eq 0 ]; then
    draining=1
    touch /data/DRAIN
    log "SPOT INTERRUPTION NOTICE $(cat /tmp/ia.json) -> drain, checkpoint, copy to S3"
    ( sleep 40; bash /data/project/cloud/instance/sync.sh cases/airflow logs ) &
  fi
  if [ "$now" -ge "$CUT" ] && [ $draining -eq 0 ]; then
    draining=1
    touch /data/DRAIN
    log "TIME/BUDGET CUTOFF reached -> drain, checkpoint, copy to S3, power off"
    finish_and_poweroff "cutoff"
  fi
  if [ $(( now - last_sync )) -ge 600 ] && [ $draining -eq 0 ]; then
    last_sync=$now
    ( bash /data/project/cloud/instance/sync.sh cases logs results validation cloud/results ) &
  fi
  if [ $(( now - last_ledger )) -ge 60 ]; then
    last_ledger=$now
    h=$(echo "scale=4; ($now - $BOOT)/3600" | bc)
    est=$(echo "scale=2; $h * $LAUNCH_PRICE" | bc)
    worst=$(echo "scale=2; $h * $MAX_PRICE" | bc)
    printf '{"instance":"%s","run":"%s","plan":"%s","boot":%s,"now":%s,"hours":%s,"est_usd_at_launch_price":%s,"worst_usd_at_max_price":%s,"draining":%s}\n' \
      "$IID" "$RUN" "$PLAN" "$BOOT" "$now" "$h" "$est" "$worst" "$draining" > /tmp/ledger.json
    aws s3 cp /tmp/ledger.json "s3://${BUCKET}/ledger/${IID}.json" --only-show-errors
    if [ -f /data/project/logs/cloud_status.json ]; then
      aws s3 cp /data/project/logs/cloud_status.json "s3://${BUCKET}/${RUN}/status.json" --only-show-errors
    fi
    aws s3 cp "$LOG" "s3://${BUCKET}/${RUN}/project/logs/guard.log" --only-show-errors
  fi
  sleep 5
done
