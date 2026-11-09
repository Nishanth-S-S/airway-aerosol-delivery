#!/bin/bash
# READ-ONLY checks before spending anything: identity, instance availability per zone, live Spot prices,
# vCPU quotas, running project instances, bucket, AMI. Creates nothing, costs nothing.
set -euo pipefail
cd "$(dirname "$0")"
source ./config.env
echo "== identity";              aws sts get-caller-identity --output table
echo "== $INSTANCE_TYPE offered in zones of $REGION"
aws ec2 describe-instance-type-offerings --region "$REGION" --location-type availability-zone \
  --filters "Name=instance-type,Values=$INSTANCE_TYPE" --query 'InstanceTypeOfferings[].Location' --output text
echo "== live Spot price (Linux), last hour, per zone"
aws ec2 describe-spot-price-history --region "$REGION" --instance-types "$INSTANCE_TYPE" \
  --product-descriptions "Linux/UNIX" --start-time "$(date -u -v-1H +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u -d '-1 hour' +%Y-%m-%dT%H:%M:%S)" \
  --query 'SpotPriceHistory[].[AvailabilityZone,SpotPrice,Timestamp]' --output table
echo "== vCPU quotas (need >= 96 for one $INSTANCE_TYPE)"
for q in L-34B43A08 L-1216C47A; do
  aws service-quotas get-service-quota --region "$REGION" --service-code ec2 --quota-code "$q" \
    --query 'Quota.[QuotaName,Value]' --output text || echo "  (could not read quota $q)"
done
echo "== running/pending project instances (must be none before a launch)"
aws ec2 describe-instances --region "$REGION" --filters "Name=tag:Project,Values=$PROJECT_TAG" \
  "Name=instance-state-name,Values=pending,running,stopping" \
  --query 'Reservations[].Instances[].[InstanceId,State.Name,LaunchTime,Tags[?Key==`Run`].Value|[0]]' --output table
echo "== bucket";                 aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null && echo "exists: $BUCKET" || echo "not created yet: $BUCKET"
echo "== Ubuntu 24.04 AMI";       aws ssm get-parameter --region "$REGION" \
  --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value --output text
echo "== spend recorded so far (ledger)"
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then python3 ledger.py "$BUCKET"; else echo "  none (no bucket yet)"; fi
