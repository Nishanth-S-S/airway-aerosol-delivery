#!/bin/bash
# Copy project paths from the instance to S3 (incremental). Usage: sync.sh <relative path> [...]
# Never deletes anything on S3 (no --delete): S3 keeps every file ever produced.
set -uo pipefail
source /etc/airway.env
cd /data/project || exit 1
for p in "$@"; do
  if [ -d "$p" ]; then
    aws s3 sync "$p" "s3://${BUCKET}/${RUN}/project/$p" --only-show-errors --no-progress --exclude "*/STOP_REQUEST" \
      || echo "$(date '+%F %T') SYNC ERROR $p" >> /data/project/logs/sync_errors.log
  elif [ -f "$p" ]; then
    aws s3 cp "$p" "s3://${BUCKET}/${RUN}/project/$p" --only-show-errors --no-progress \
      || echo "$(date '+%F %T') SYNC ERROR $p" >> /data/project/logs/sync_errors.log
  fi
done
