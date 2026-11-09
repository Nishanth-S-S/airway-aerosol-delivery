#!/usr/bin/env python3
"""Cost ledger: sum of what every project instance has cost so far (written by the instance guard every minute).

    python3 cloud/aws/ledger.py <bucket>            -> prints JSON {instances, est_usd, worst_usd}
The ledger survives Spot terminations (it lives in S3). `worst_usd` (elapsed hours x max Spot price) is the bound
used by 03_launch.sh; storage and transfer are added from the bucket size.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

bucket = sys.argv[1]
with tempfile.TemporaryDirectory() as td:
    subprocess.run(["aws", "s3", "sync", f"s3://{bucket}/ledger", td, "--only-show-errors"], check=False)
    rows = []
    for f in Path(td).glob("*.json"):
        try:
            rows.append(json.loads(f.read_text()))
        except ValueError:
            pass
inst = [r for r in rows if "instance" in r]
size = subprocess.run(["aws", "s3", "ls", f"s3://{bucket}", "--recursive", "--summarize"], capture_output=True, text=True).stdout
gb = 0.0
for ln in size.splitlines():
    if "Total Size" in ln:
        gb = float(ln.split(":")[1]) / 1e9
out = {"instances": [{k: r.get(k) for k in ("instance", "run", "plan", "hours", "est_usd_at_launch_price", "worst_usd_at_max_price")}
                     for r in inst],
       "est_usd": round(sum(r.get("est_usd_at_launch_price", 0) for r in inst), 2),
       "worst_usd": round(sum(r.get("worst_usd_at_max_price", 0) for r in inst), 2),
       "s3_GB": round(gb, 1), "s3_usd_per_month": round(gb * 0.023, 2)}
print(json.dumps(out, indent=1))
