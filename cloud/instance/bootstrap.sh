#!/bin/bash
# EC2 user-data (rendered by cloud/aws/03_launch.sh, which prepends the /etc/airway.env block). Runs once as root.
# 1. hard stop timer (backstop for the cost cap)   2. toolchain: Docker + the pinned OpenFOAM image, AWS CLI,
# Python env with the Mac's exact package versions   3. restore the project (and any checkpoints) from S3
# 4. start the guard   5. run the plan (benchmark | production)   6. copy everything to S3, power off (= terminate)
exec > /var/log/airway-bootstrap.log 2>&1
set -euxo pipefail
source /etc/airway.env
shutdown -h +"${HOURS_CAP_MIN}" "airway: hard time cap reached" || true      # backstop; guard drains earlier

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q docker.io jq bc unzip curl bzip2 sysstat
systemctl enable --now docker
curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscli.zip
unzip -q /tmp/awscli.zip -d /tmp && /tmp/aws/install
aws configure set default.region "$REGION"
aws configure set default.s3.max_concurrent_requests 32

# Python environment identical to the Mac's (cloud/toolchain_reference.json)
curl -sSL https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C /usr/local bin/micromamba
export MAMBA_ROOT_PREFIX=/opt/mamba
/usr/local/bin/micromamba create -y -q -n airway -c conda-forge \
  python=3.10.11 numpy=1.26.4 pandas=2.2.3 scipy=1.10.0 matplotlib=3.7.1 pyyaml=6.0.1
PY=/opt/mamba/envs/airway/bin/python3

docker pull "$IMAGE"

# project (+ checkpoints / finished cases of an earlier instance of the same run)
mkdir -p /data/project
aws s3 sync "s3://${BUCKET}/${RUN}/project" /data/project --only-show-errors --no-progress
mkdir -p /data/project/logs
chmod +x /data/project/cloud/instance/*.sh /data/project/tools/openfoam/bin/*     # S3 does not keep permissions
rm -f /data/DRAIN
nohup bash /data/project/cloud/instance/guard.sh >/dev/null 2>&1 &

cd /data/project
export AIRWAY_DOCKER_IMAGE="$IMAGE" AIRWAY_DRAIN_FILE=/data/DRAIN BENCH_FINE="${BENCH_FINE:-0}"
set +e
if [ "$PLAN" = "benchmark" ]; then
  "$PY" cloud/bench/bench.py all > logs/bench.out 2>&1
  rc=$?
else
  "$PY" cloud/bench/bench.py e1 > logs/preflight_e1.out 2>&1 && \
  "$PY" cloud/runner/cloud_runner.py ${RUNNER_ARGS} > logs/cloud_runner.out 2>&1
  rc=$?
fi
set -e
echo "{\"plan\":\"$PLAN\",\"exit\":$rc,\"time\":\"$(date '+%F %T')\"}" > logs/plan_exit.json
bash cloud/instance/sync.sh cases logs results validation docs cloud/results
aws s3 cp /var/log/airway-bootstrap.log "s3://${BUCKET}/${RUN}/project/logs/bootstrap.log" --only-show-errors
shutdown -h now
