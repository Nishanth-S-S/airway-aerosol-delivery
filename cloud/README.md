# Running the remaining v002 study on AWS (c7a.24xlarge Spot)

Nothing in this folder has created or paid for any AWS resource. Only `aws/03_launch.sh` spends money, and it
refuses to launch unless you pass an explicit dollar approval that covers the worst case and keeps the running ledger
under `BUDGET_USD`.

## What is here

| Path | Purpose |
|---|---|
| `WORKLOAD_ESTIMATE.md` | Mac performance audit + CPU-hours, wall time, storage and cost per scenario (`tools/plan_workload.py`) |
| `EQUIVALENCE_CRITERIA.md` | Pre-registered cloud-vs-Mac tests E1-E6 (fixed before any cloud run) |
| `toolchain_reference.json` | The Mac's OpenFOAM image digest, binary SHA-256s and Python versions; the cloud must match |
| `bench/bench.py`, `bench/equivalence.py` | Paid benchmark: equivalence tests, rank scaling, concurrency, full-case timing |
| `runner/cloud_runner.py` | Production scheduler (core pinning, longest-first, particle pool, gated analysis pipeline, drain) |
| `runner/job_airflow.py` | One airflow case, fresh or resumed from a checkpoint; same case setup/commands/QA as the Mac |
| `instance/bootstrap.sh`, `guard.sh`, `sync.sh` | On the instance: setup, Spot/cutoff guard, copy-to-S3 |
| `aws/00..07_*.sh` | Run from the Mac: preflight (read-only), setup, upload, launch, monitor, download, stop, teardown |
| `tools/merge_cloud_results.py` | Copy downloaded results into the project; never overwrites |

## One-time preparation (you)

1. **AWS account and CLI on the Mac.** Install the official CLI (`curl -o AWSCLIV2.pkg https://awscli.amazonaws.com/AWSCLIV2.pkg`
   then `sudo installer -pkg AWSCLIV2.pkg -target /`), then run `aws configure` yourself with an access key of an IAM user that has
   EC2, S3, IAM, SSM, Service Quotas and Budgets permissions. Default region: `eu-north-1`.
2. **Spot vCPU quota.** New accounts often have less than 96. In the Service Quotas console (region eu-north-1) request
   *"All Standard (A, C, D, H, I, M, R, T, Z) Spot Instance Requests"* = **96** (or **192** if the fine mesh is adopted and you
   want two instances in parallel). Approval can take from minutes to a day, so do this first.
3. `cp cloud/aws/config.env.example cloud/aws/config.env` and set a unique `BUCKET` name (and `ALERT_EMAIL` for budget alerts).

## Benchmark (needs your cost approval)

```bash
bash cloud/aws/00_preflight.sh                        # read-only: identity, zones, live Spot price, quotas, ledger
bash cloud/aws/01_setup.sh --yes                      # bucket, IAM role, no-inbound security group, budget alerts (free)
bash cloud/aws/02_upload.sh bench-1 benchmark         # ~5.2 GB: code, frozen inputs, Mac medium case + maps, meshes
bash cloud/aws/03_launch.sh bench-1 benchmark --hours 5 --approve-usd 8
bash cloud/aws/04_monitor.sh bench-1 --watch          # status, cost so far, guard log (Ctrl-C to leave)
bash cloud/aws/05_download.sh bench-1                 # results only, into cloud_downloads/bench-1/
python3 cloud/tools/merge_cloud_results.py bench-1 --apply
python3 cloud/bench/bench.py summary                  # E1-E6, scaling, concurrency, recommended configuration
python3 cloud/tools/plan_workload.py --bench cloud/results/benchmark/summary.json
```

The instance powers itself off when the benchmark ends (and at 4 h 35 min at the latest, hard stop at 5 h).

## Production (only after the benchmark passes AND the mesh decision is approved)

The production scripts refuse to run unless `validation/04_mesh_independence/results/MESH_DECISION.json` says
`"approved": true` with a `production_level` equal to `mesh.level` in `config/experiment.yaml`. Coarse v002 results
are never uploaded (they would otherwise be mistaken for finished cases).

```bash
bash cloud/aws/02_upload.sh prod-1 production
bash cloud/aws/03_launch.sh prod-1 production --hours 12 --approve-usd 20 \
     --runner-args "--ranks 8 --co1-ranks 16 --particle-cores 8"      # values from the benchmark summary
bash cloud/aws/04_monitor.sh prod-1 --watch
bash cloud/aws/05_download.sh prod-1                  # add --with-fields for the airflow snapshots (large)
python3 cloud/tools/merge_cloud_results.py prod-1 --apply
```

If a Spot interruption or the time cap stops a run, the data so far are on S3 (finished cases at once, running cases
as checkpoints). Nothing restarts by itself. To continue, launch the **same run name** again (a new, separately
approved `03_launch.sh`); finished cases are skipped and running cases resume from their last checkpoint.

## Safety and cost controls

* One-time Spot request with a price ceiling (`MAX_PRICE`): no automatic relaunch, no on-demand fallback.
* Hard cap: `shutdown` timer at `--hours` (instance-initiated shutdown = terminate); graceful drain 25 min earlier.
* Spot interruption notice: running cases write their state (`stopAt writeNow`) and everything is copied to S3 within
  the 2-minute window; off-schedule checkpoint times are moved to `quarantine/` before results are rebuilt.
* Ledger in S3 (updated every minute) + AWS Budgets e-mail alerts; `03_launch.sh` refuses launches that could exceed
  `BUDGET_USD`, or while another project instance is running.
* The instance role can read/write only the project bucket and cannot delete anything in it.
* No inbound network access; emergency shell through AWS Systems Manager only.
* Stop early: `bash cloud/aws/06_stop.sh <run> --graceful` (keeps everything) or `--terminate`.
* Clean up after download: `bash cloud/aws/07_teardown.sh` (lists), `--remove-infra`, `--delete-bucket <name>`.
