#!/usr/bin/env python3
"""SHA-256 manifest of the files uploaded for a run: python3 cloud/tools/manifest.py <run> <path> [...]"""
import hashlib, json, sys, time
from pathlib import Path
run, paths = sys.argv[1], sys.argv[2:]
skip = ("processor", ".pyc", "config.env", "state.env", "results/benchmark")
files = {}
for p in paths:
    for f in ([Path(p)] if Path(p).is_file() else sorted(Path(p).rglob("*"))):
        s = str(f)
        if f.is_file() and not any(k in s for k in skip):
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            files[s] = h.hexdigest()
out = Path("cloud/results") / f"upload_manifest_{run}.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"run": run, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "n_files": len(files),
                           "bytes": sum(Path(f).stat().st_size for f in files), "sha256": files}, indent=1))
print(f"manifest: {len(files)} files, {sum(Path(f).stat().st_size for f in files) / 1e9:.2f} GB -> {out}")
