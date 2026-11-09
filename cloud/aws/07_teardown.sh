#!/bin/bash
# After the project: list (default) or remove what is left.
#   bash cloud/aws/07_teardown.sh                    list instances, volumes, bucket size, IAM, security group, budget
#   bash cloud/aws/07_teardown.sh --remove-infra     remove IAM role/profile, security group, budget (free items)
#   bash cloud/aws/07_teardown.sh --delete-bucket <bucket-name-typed-again>
#        permanently deletes ALL cloud copies of the results - only after you have downloaded and checked them
set -euo pipefail
cd "$(dirname "$0")"
source ./config.env
source ./state.env 2>/dev/null || true
echo "== instances";  aws ec2 describe-instances --region "$REGION" --filters "Name=tag:Project,Values=$PROJECT_TAG" \
  --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output table
echo "== volumes";    aws ec2 describe-volumes --region "$REGION" --filters "Name=tag:Project,Values=$PROJECT_TAG" \
  --query 'Volumes[].[VolumeId,State,Size]' --output table
echo "== bucket";     aws s3 ls "s3://$BUCKET" --recursive --summarize | tail -2 || true
case "${1:-}" in
  --remove-infra)
    aws iam remove-role-from-instance-profile --instance-profile-name airway-cfd-ec2 --role-name airway-cfd-ec2 || true
    aws iam delete-instance-profile --instance-profile-name airway-cfd-ec2 || true
    aws iam delete-role-policy --role-name airway-cfd-ec2 --policy-name airway-cfd-bucket || true
    aws iam detach-role-policy --role-name airway-cfd-ec2 --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore || true
    aws iam delete-role --role-name airway-cfd-ec2 || true
    [ -n "${SECURITY_GROUP:-}" ] && aws ec2 delete-security-group --region "$REGION" --group-id "$SECURITY_GROUP" || true
    [ -n "${ACCOUNT:-}" ] && aws budgets delete-budget --account-id "$ACCOUNT" --budget-name airway-cfd || true
    echo "infrastructure removed (bucket kept)";;
  --delete-bucket)
    [ "${2:-}" = "$BUCKET" ] || { echo "type the bucket name again to confirm: --delete-bucket $BUCKET"; exit 1; }
    aws s3 rb "s3://$BUCKET" --force;;
esac
