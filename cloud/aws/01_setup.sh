#!/bin/bash
# One-time setup of FREE / near-free resources. Needs --yes. Creates:
#   * private, encrypted S3 bucket (public access blocked; incomplete uploads cleaned after 1 day)
#   * IAM role + instance profile: read/write ONLY this bucket (no delete permission) + SSM for an emergency shell
#   * security group with NO inbound rules (nothing can connect to the instance)
#   * AWS Budget with e-mail alerts at 50 / 80 / 100 % of BUDGET_USD (if ALERT_EMAIL is set)
# Writes cloud/aws/state.env. Running it twice is safe (existing resources are reused).
set -euo pipefail
cd "$(dirname "$0")"
source ./config.env
[ "${1:-}" = "--yes" ] || { echo "Creates the resources listed at the top of this file. Re-run with --yes."; exit 1; }
ACCT=$(aws sts get-caller-identity --query Account --output text)
ROLE=airway-cfd-ec2

if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" --create-bucket-configuration "LocationConstraint=$REGION"
fi
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration \
  '{"Rules":[{"ID":"abort-mpu","Status":"Enabled","Filter":{},"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}}]}'

if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
  aws iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
fi
aws iam put-role-policy --role-name "$ROLE" --policy-name airway-cfd-bucket --policy-document "{
  \"Version\":\"2012-10-17\",\"Statement\":[
   {\"Effect\":\"Allow\",\"Action\":[\"s3:ListBucket\"],\"Resource\":\"arn:aws:s3:::$BUCKET\"},
   {\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\"],\"Resource\":\"arn:aws:s3:::$BUCKET/*\"}]}"
if ! aws iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$ROLE"
  aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
fi

VPC=$(aws ec2 describe-vpcs --region "$REGION" --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 describe-security-groups --region "$REGION" --filters Name=group-name,Values=airway-cfd-noinbound \
     Name=vpc-id,Values="$VPC" --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --region "$REGION" --group-name airway-cfd-noinbound \
       --description "airway CFD batch: no inbound access" --vpc-id "$VPC" --query GroupId --output text)
fi

if [ -n "${ALERT_EMAIL:-}" ] && ! aws budgets describe-budget --account-id "$ACCT" --budget-name airway-cfd >/dev/null 2>&1; then
  N='[]'
  N=$(python3 - "$ALERT_EMAIL" <<'PY'
import json, sys
e = sys.argv[1]
print(json.dumps([{"Notification": {"NotificationType": t, "ComparisonOperator": "GREATER_THAN", "Threshold": th,
                   "ThresholdType": "PERCENTAGE"}, "Subscribers": [{"SubscriptionType": "EMAIL", "Address": e}]}
                  for t, th in (("ACTUAL", 50), ("ACTUAL", 80), ("ACTUAL", 100), ("FORECASTED", 100))]))
PY
)
  aws budgets create-budget --account-id "$ACCT" --budget "{\"BudgetName\":\"airway-cfd\",\"BudgetLimit\":{\"Amount\":\"$BUDGET_USD\",\"Unit\":\"USD\"},\"TimeUnit\":\"MONTHLY\",\"BudgetType\":\"COST\"}" \
    --notifications-with-subscribers "$N"
fi

cat > state.env <<EOF
ACCOUNT=$ACCT
INSTANCE_PROFILE=$ROLE
SECURITY_GROUP=$SG
VPC=$VPC
EOF
echo "setup done:"; cat state.env
