#!/usr/bin/env python3
"""Data that GitHub cannot hold (~6.5 GB): frozen geometry, the n40 medium/fine meshes, the Mac's medium verification
case (reference fields for the equivalence tests), its 1/3/5 um maps, and the fine-mesh case with its 8-processor
state at t = 0.52 s (the desktop resumes from it). Packed as tar parts of <= 1.9 GB with a SHA-256 manifest.

On the Mac:      python3 local/bundle.py make /Volumes/USB/airway_bundle        (USB drive, network share, ...)
On the desktop:  python3 local/bundle.py unpack /path/to/airway_bundle          (from the project folder)

Coarse-mesh v002 cases and archive/ are deliberately NOT included (coarse results are exploratory only, and a case
folder counts as "done" for the production scheduler).
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATHS = ["geometry", "cases/mesh/n40_medium", "cases/mesh/n40_fine", "cases/airflow/V_MESH_medium_T_N40_SYM",
         "cases/airflow/V_MESH_fine_T_N40_SYM", "cases/particles/MAP_V_MESH_medium_T_N40_SYM_P01",
         "cases/particles/MAP_V_MESH_medium_T_N40_SYM_P03", "cases/particles/MAP_V_MESH_medium_T_N40_SYM_P05"]
PART = 1_900_000_000


def sha(f: Path) -> str:
    h = hashlib.sha256()
    with open(f, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Parts(io.RawIOBase):
    """Write-only stream split into numbered files."""
    def __init__(self, dest: Path):
        self.dest, self.i, self.n, self.fh = dest, 0, 0, None
        self._open()

    def _open(self):
        if self.fh:
            self.fh.close()
        self.i += 1
        self.fh, self.n = open(self.dest / f"airway_data.tar.part{self.i:02d}", "wb"), 0

    def writable(self):
        return True

    def write(self, b):
        b = memoryview(b)
        done = 0
        while done < len(b):
            if self.n >= PART:
                self._open()
            k = min(len(b) - done, PART - self.n)
            self.fh.write(b[done:done + k])
            self.n += k
            done += k
        return len(b)

    def close(self):
        if self.fh:
            self.fh.close()
        super().close()


def make(dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.glob("airway_data.tar.part*")):
        sys.exit(f"{dest} already holds a bundle - choose an empty folder")
    fine = ROOT / "cases/airflow/V_MESH_fine_T_N40_SYM"
    for i in range(8):
        if not (fine / f"processor{i}" / "0.52" / "U_0").exists():
            sys.exit(f"fine-mesh state at 0.52 s incomplete in processor{i} - not bundling")
    files = {}
    for p in PATHS:
        for f in sorted((ROOT / p).rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                files[str(f.relative_to(ROOT))] = sha(f)
    man = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "paths": PATHS, "n_files": len(files),
           "bytes": sum((ROOT / f).stat().st_size for f in files), "sha256": files}
    (dest / "MANIFEST.json").write_text(json.dumps(man, indent=1))
    print(f"{len(files)} files, {man['bytes'] / 1e9:.2f} GB -> {dest}")
    out = Parts(dest)
    with tarfile.open(fileobj=out, mode="w|") as tar:
        for f in files:
            tar.add(ROOT / f, arcname=f, recursive=False)
    out.close()
    man["n_parts"] = out.i
    (dest / "MANIFEST.json").write_text(json.dumps(man, indent=1))
    print(f"wrote {out.i} part(s) + MANIFEST.json")


def unpack(src: Path):
    # parts may sit in sub-folders (e.g. several Google Drive zip downloads extracted side by side); duplicates such
    # as "airway_data.tar.part01 (1)" are ignored
    import re
    found = {}
    for f in src.rglob("airway_data.tar.part*"):
        m = re.fullmatch(r"airway_data\.tar\.part(\d+)", f.name)
        if m:
            found.setdefault(int(m.group(1)), f)
    mans = sorted(src.rglob("MANIFEST.json"))
    if not mans:
        sys.exit(f"refused: no MANIFEST.json under {src}")
    man = json.loads(mans[0].read_text())
    n = man.get("n_parts", max(found) if found else 0)
    missing = [i for i in range(1, n + 1) if i not in found]
    if not found or missing:
        sys.exit(f"refused: bundle incomplete under {src} - missing part(s) {missing or 'all'} of {n}")
    parts = [found[i] for i in range(1, n + 1)]
    # re-runnable: files already present with the right content are skipped; a file that differs (e.g. cut off by an
    # interrupted earlier unpack) is moved to unpack_quarantine/<time>/, never deleted, and extracted again
    skip, moved = set(), 0
    qdir = ROOT / "unpack_quarantine" / time.strftime("%Y%m%d_%H%M%S")
    for f, h in man["sha256"].items():
        if (ROOT / f).exists():
            if sha(ROOT / f) == h:
                skip.add(f)
            else:
                (qdir / f).parent.mkdir(parents=True, exist_ok=True)
                (ROOT / f).rename(qdir / f)
                moved += 1
    if skip or moved:
        print(f"{len(skip)} files already in place (skipped); {moved} differing files moved to {qdir.relative_to(ROOT)}")

    class Cat(io.RawIOBase):
        def __init__(self):
            self.q, self.fh = list(parts), None

        def readable(self):
            return True

        def readinto(self, b):
            while True:
                if self.fh is None:
                    if not self.q:
                        return 0
                    self.fh = open(self.q.pop(0), "rb")
                n = self.fh.readinto(b)
                if n:
                    return n
                self.fh.close()
                self.fh = None
    with tarfile.open(fileobj=io.BufferedReader(Cat(), 1 << 20), mode="r|") as tar:
        for m in tar:
            if m.name.startswith("/") or ".." in Path(m.name).parts or m.name not in man["sha256"]:
                sys.exit(f"refused: unexpected entry {m.name}")
            if m.name not in skip:
                tar.extract(m, ROOT)
    bad = [f for f, h in man["sha256"].items() if not (ROOT / f).exists() or sha(ROOT / f) != h]
    print(f"unpacked {man['n_files']} files; SHA-256 check: {'ALL OK' if not bad else f'{len(bad)} MISMATCHES e.g. {bad[:3]}'}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("make", "unpack"):
        sys.exit(__doc__)
    (make if sys.argv[1] == "make" else unpack)(Path(sys.argv[2]).expanduser().resolve())
