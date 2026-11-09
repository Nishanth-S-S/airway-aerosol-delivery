#!/usr/bin/env python3
"""Merge a downloaded cloud run (cloud_downloads/<run>/) into the project. Copies only; NEVER overwrites.

    python3 cloud/tools/merge_cloud_results.py <run>            # dry run: lists what would be copied / conflicts
    python3 cloud/tools/merge_cloud_results.py <run> --apply

Copies case folders (cases/airflow/*, cases/particles/*, cases/mesh/*, cases/bench/*) that do not exist in the project,
and result/validation files that do not exist. Existing project files are left untouched and reported as conflicts,
so a cloud copy can never replace a Mac result. Logs go to cloud_downloads/<run>/ only (not merged).
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
run = sys.argv[1]
apply = "--apply" in sys.argv
src = ROOT / "cloud_downloads" / run
if not src.exists():
    sys.exit(f"{src} not found - run cloud/aws/05_download.sh {run} first")
copied, conflicts = [], []
for group in ("cases/airflow", "cases/particles", "cases/mesh", "cases/bench"):
    for d in sorted((src / group).glob("*")) if (src / group).exists() else []:
        dst = ROOT / group / d.name
        if dst.exists():
            conflicts.append(str(dst.relative_to(ROOT)))
        else:
            copied.append(str(dst.relative_to(ROOT)))
            if apply:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(d, dst)
for group in ("results", "validation", "cloud/results"):
    for f in sorted((src / group).rglob("*")) if (src / group).exists() else []:
        if f.is_file():
            dst = ROOT / f.relative_to(src)
            if dst.exists():
                if dst.read_bytes() != f.read_bytes():
                    conflicts.append(str(dst.relative_to(ROOT)))
            else:
                copied.append(str(dst.relative_to(ROOT)))
                if apply:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dst)
print(f"{'copied' if apply else 'would copy'}: {len(copied)}")
for c in copied[:50]:
    print("  +", c)
print(f"conflicts (left untouched, compare by hand): {len(conflicts)}")
for c in conflicts[:50]:
    print("  !", c)
