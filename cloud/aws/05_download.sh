#!/bin/bash
# Download a run from S3 into cloud_downloads/<run>/ (NEVER into the live project folders), then verify it.
#   bash cloud/aws/05_download.sh <run>                 results, logs, QA, particle outputs, sections (small)
#   bash cloud/aws/05_download.sh <run> --with-fields   also the 150 airflow snapshots per case (large; data transfer
#                                                        beyond 100 GB/month is billed at ~$0.09/GB)
# Merge into the project afterwards with:  python3 cloud/tools/merge_cloud_results.py <run>   (copies, never overwrites)
set -euo pipefail
cd "$(dirname "$0")"
source ./config.env
RUN=${1:?run name}
DEST=../../cloud_downloads/$RUN
mkdir -p "$DEST"
EXTRA=(--exclude "*processor*" --exclude "*/quarantine/*")
if [ "${2:-}" != "--with-fields" ]; then
  EXTRA+=(--exclude "cases/airflow/*/[0-9]*" --exclude "cases/bench/*/[0-9]*")
fi
aws s3 sync "s3://$BUCKET/$RUN/project" "$DEST" --only-show-errors "${EXTRA[@]}"
aws s3 cp "s3://$BUCKET/$RUN/status.json" "$DEST/status.json" --only-show-errors || true
du -sh "$DEST"
echo "downloaded to cloud_downloads/$RUN (project folders untouched)"
