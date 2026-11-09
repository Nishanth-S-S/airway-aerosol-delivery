#!/usr/bin/env python3
"""Pretty-print the runner status JSON read from stdin (used by 04_monitor.sh)."""
import json
import sys

try:
    s = json.load(sys.stdin)
except ValueError:
    sys.exit("(no status yet - instance still booting)")
print(f"state {s.get('state')}, {s.get('elapsed_h')} h, cores busy {s.get('cores_busy')}/{s.get('cores_total')}")
print("running:", ", ".join(f"{r['job']} ({r['since_min']} min)" for r in s.get("running", [])) or "-")
print(f"done {len(s.get('done', []))}, pending {len(s.get('pending', []))}, failed {s.get('failed') or 'none'}")
