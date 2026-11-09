#!/bin/bash
# THE ONLY SCRIPT THAT SPENDS MONEY. Launches ONE one-time Spot instance for a run, after budget checks.
#   bash cloud/aws/03_launch.sh <run-name> benchmark  --hours 5  --approve-usd 8
#   bash cloud/aws/03_launch.sh <run-name> production --hours 24 --approve-usd 40 --runner-args "--ranks 8 --co1-ranks 16 --particle-cores 8"
# Guarantees:
#   * worst case = hours x MAX_PRICE (+ disk) must be <= --approve-usd, and ledger total + worst case <= BUDGET_USD
#   * one-time Spot request, InstanceInterruptionBehavior=terminate: NOTHING is relaunched automatically. Resuming after
#     an interruption is a new, separately approved run of this script (same run name -> continues from S3 checkpoints)
#   * the instance drains + saves at hours-25 min and is hard-stopped (shutdown -> terminate) at --hours
#   * refuses if any project instance is already pending/running
set -euo pipefail
cd "$(dirname "$0")"
source ./config.env
source ./state.env
RUN=${1:?run name}; PLAN=${2:?benchmark|production}; shift 2
HOURS=""; APPROVE=""; RUNNER_ARGS="--ranks 8 --particle-cores 8"; BENCH_FINE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --hours) HOURS=$2; shift 2;;
    --approve-usd) APPROVE=$2; shift 2;;
    --runner-args) RUNNER_ARGS=$2; shift 2;;
    --bench-fine) BENCH_FINE=1; shift;;            # benchmark also runs the full fine-mesh verification case
    *) echo "unknown option $1"; exit 1;;
  esac
done
[ -n "$HOURS" ] && [ -n "$APPROVE" ] || { echo "need --hours and --approve-usd"; exit 1; }

RUNNING=$(aws ec2 describe-instances --region "$REGION" --filters "Name=tag:Project,Values=$PROJECT_TAG" \
  "Name=instance-state-name,Values=pending,running,stopping" --query 'Reservations[].Instances[].InstanceId' --output text)
[ -z "$RUNNING" ] || { echo "refused: project instance(s) already running: $RUNNING"; exit 1; }

aws s3 ls "s3://$BUCKET/$RUN/project/scripts/" >/dev/null || { echo "refused: run $RUN not uploaded (02_upload.sh)"; exit 1; }

# cheapest zone right now
read -r AZ PRICE < <(aws ec2 describe-spot-price-history --region "$REGION" --instance-types "$INSTANCE_TYPE" \
  --product-descriptions "Linux/UNIX" --max-items 20 --query 'SpotPriceHistory[].[AvailabilityZone,SpotPrice]' --output text \
  | sort -k2 -n | head -1)
SUBNET=$(aws ec2 describe-subnets --region "$REGION" --filters "Name=vpc-id,Values=$VPC" "Name=availability-zone,Values=$AZ" \
  "Name=default-for-az,Values=true" --query 'Subnets[0].SubnetId' --output text)

python3 - "$HOURS" "$APPROVE" "$MAX_PRICE" "$PRICE" "$BUDGET_USD" "$VOLUME_GB" "$BUCKET" <<'PY'
import json, subprocess, sys
hours, approve, maxp, price, budget, vol, bucket = map(str, sys.argv[1:])
hours, approve, maxp, price, budget, vol = map(float, (hours, approve, maxp, price, budget, vol))
disk = vol * 0.0836 / 730 * hours                 # gp3 eu-north-1, $/GB-month
worst = hours * maxp + disk
expect = hours * price + disk
led = json.loads(subprocess.run([sys.executable, "ledger.py", bucket], capture_output=True, text=True).stdout or "{}")
spent = led.get("worst_usd", 0.0) + led.get("s3_usd_per_month", 0.0)
print(f"Spot now ${price:.4f}/h (ceiling ${maxp}/h), {hours} h cap: expected ${expect:.2f}, worst case ${worst:.2f}")
print(f"ledger so far (upper bound incl. 1 month S3): ${spent:.2f}; budget ${budget:.0f}")
if price > maxp:
    sys.exit("refused: current Spot price is above MAX_PRICE")
if worst > approve:
    sys.exit(f"refused: worst case ${worst:.2f} exceeds your approval ${approve:.2f}")
if spent + worst > budget:
    sys.exit(f"refused: ${spent:.2f} + ${worst:.2f} would exceed BUDGET_USD ${budget:.0f}")
PY

AMI=$(aws ssm get-parameter --region "$REGION" --name \
  /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value --output text)
IMAGE=$(python3 -c 'import json;print(json.load(open("../toolchain_reference.json"))["docker_image"])')
UD=$(mktemp)
{
  echo "#!/bin/bash"
  echo "cat > /etc/airway.env <<'ENV'"
  echo "BUCKET=$BUCKET"; echo "RUN=$RUN"; echo "PLAN=$PLAN"; echo "REGION=$REGION"; echo "IMAGE=$IMAGE"
  echo "HOURS_CAP_MIN=$(python3 -c "print(int(float('$HOURS')*60))")"; echo "DRAIN_MARGIN_MIN=25"
  echo "MAX_PRICE=$MAX_PRICE"; echo "LAUNCH_PRICE=$PRICE"; echo "RUNNER_ARGS=\"$RUNNER_ARGS\""; echo "BENCH_FINE=$BENCH_FINE"
  echo "ENV"
  tail -n +2 ../instance/bootstrap.sh
} > "$UD"

IID=$(aws ec2 run-instances --region "$REGION" --image-id "$AMI" --instance-type "$INSTANCE_TYPE" \
  --subnet-id "$SUBNET" --security-group-ids "$SECURITY_GROUP" --iam-instance-profile "Name=$INSTANCE_PROFILE" \
  --instance-market-options "{\"MarketType\":\"spot\",\"SpotOptions\":{\"MaxPrice\":\"$MAX_PRICE\",\"SpotInstanceType\":\"one-time\",\"InstanceInterruptionBehavior\":\"terminate\"}}" \
  --instance-initiated-shutdown-behavior terminate \
  --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
  --block-device-mappings "[{\"DeviceName\":\"/dev/sda1\",\"Ebs\":{\"VolumeSize\":$VOLUME_GB,\"VolumeType\":\"gp3\",\"Iops\":6000,\"Throughput\":500,\"DeleteOnTermination\":true,\"Encrypted\":true}}]" \
  --user-data "file://$UD" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Project,Value=$PROJECT_TAG},{Key=Run,Value=$RUN},{Key=Plan,Value=$PLAN}]" \
                       "ResourceType=volume,Tags=[{Key=Project,Value=$PROJECT_TAG},{Key=Run,Value=$RUN}]" \
  --query 'Instances[0].InstanceId' --output text)
echo "{\"instance\":\"$IID\",\"run\":\"$RUN\",\"plan\":\"$PLAN\",\"approved_usd\":$APPROVE,\"hours_cap\":$HOURS,\"zone\":\"$AZ\",\"launch_price\":$PRICE,\"time\":\"$(date -u +%FT%TZ)\"}" \
  | aws s3 cp - "s3://$BUCKET/approvals/$IID.json" --only-show-errors
echo "launched $IID in $AZ at \$$PRICE/h (run $RUN, plan $PLAN, cap $HOURS h). Monitor: bash cloud/aws/04_monitor.sh $RUN"
