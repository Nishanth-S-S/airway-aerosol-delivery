"""Minimal reader for OpenFOAM volScalarField / volVectorField internal fields (binary or ascii, uncompressed).

Used only by the equivalence tests to compare complete 3-D fields cell by cell between two runs on the same mesh.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np


def read_internal(path: Path) -> np.ndarray:
    raw = Path(path).read_bytes()
    head = raw[:4000].decode("latin-1")
    binary = re.search(r"format\s+binary", head) is not None
    vector = "volVectorField" in head
    i = raw.index(b"internalField")
    j = raw.index(b";", i) if raw[i:i + 200].find(b"uniform") >= 0 and raw[i:i + 200].find(b"nonuniform") < 0 else None
    if j is not None:                                   # uniform value
        txt = raw[i:j].decode("latin-1")
        vals = [float(x) for x in re.findall(r"[-+0-9.eE]+", txt.split("uniform", 1)[1])]
        return np.array(vals)
    m = re.compile(rb"nonuniform\s+List<(scalar|vector)>\s+(\d+)\s*\(").search(raw, i)
    n = int(m.group(2))
    start = m.end()
    ncomp = 3 if m.group(1) == b"vector" else 1
    if binary:
        arr = np.frombuffer(raw, dtype="<f8", count=n * ncomp, offset=start)
    else:
        end = raw.index(b")\n;", start) if ncomp == 1 else raw.index(b"\n)\n", start)
        arr = np.array(re.findall(rb"[-+0-9.eE]+", raw[start:end]), dtype=float)
    assert arr.size == n * ncomp, (path, arr.size, n * ncomp, vector)
    return arr.reshape(n, ncomp) if ncomp == 3 else arr


def rel_l2(a: np.ndarray, b: np.ndarray) -> float:
    """||a - b|| / ||b|| over all cells (vectors: Euclidean over components)."""
    return float(np.linalg.norm(a - b) / np.linalg.norm(b))


def compare_time(case_a: Path, case_b: Path, time_name: str) -> dict:
    out = {}
    for f in ("U", "p", "phi"):
        pa, pb = Path(case_a) / time_name / f, Path(case_b) / time_name / f
        if pa.exists() and pb.exists():
            try:
                a, b = read_internal(pa), read_internal(pb)
                out[f] = {"n": int(len(a)), "rel_l2": rel_l2(a, b), "max_abs_diff": float(np.abs(a - b).max()),
                          "bitwise_identical": bool(np.array_equal(a, b))}
            except Exception as e:  # phi is a surfaceScalarField: same layout, read the same way
                out[f] = {"error": str(e)}
    return out
