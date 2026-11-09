"""Minimal, dependency-free STL reader/writer (binary + ASCII, multi-solid ASCII output)."""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np


def read_stl(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (triangles[N,3,3], normals[N,3]) for a binary or single/multi-solid ASCII STL."""
    data = Path(path).read_bytes()
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + 50 * n == len(data):
            rec = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
            arr = np.frombuffer(data, dtype=rec, count=n, offset=84)
            return arr["v"].astype(float), arr["n"].astype(float)
    tris, norms = [], []
    cur, nrm = [], None
    for line in data.decode("ascii", errors="ignore").splitlines():
        t = line.split()
        if not t:
            continue
        if t[0] == "facet":
            nrm = [float(x) for x in t[2:5]]
            cur = []
        elif t[0] == "vertex":
            cur.append([float(x) for x in t[1:4]])
        elif t[0] == "endfacet":
            tris.append(cur)
            norms.append(nrm)
    return np.array(tris, float), np.array(norms, float)


def read_ascii_regions(path: str | Path) -> dict[str, np.ndarray]:
    """Read a multi-solid ASCII STL into {solid_name: triangles}."""
    regions: dict[str, list] = {}
    name, cur = None, []
    for line in Path(path).read_text().splitlines():
        t = line.split()
        if not t:
            continue
        if t[0] == "solid":
            name = t[1] if len(t) > 1 else "solid"
            regions.setdefault(name, [])
        elif t[0] == "vertex":
            cur.append([float(x) for x in t[1:4]])
            if len(cur) == 3:
                regions[name].append(cur)
                cur = []
    return {k: np.array(v) for k, v in regions.items()}


def tri_normals(tris: np.ndarray) -> np.ndarray:
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return n / np.where(ln == 0, 1, ln)


def tri_areas(tris: np.ndarray) -> np.ndarray:
    return 0.5 * np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1)


def write_ascii_regions(path: str | Path, regions: dict[str, np.ndarray], scale: float = 1.0) -> None:
    """Write {name: triangles} as one multi-solid ASCII STL (one named solid per region)."""
    with open(path, "w") as fh:
        for name, tris in regions.items():
            t = tris * scale
            nn = tri_normals(t)
            fh.write(f"solid {name}\n")
            for tri, n in zip(t, nn):
                fh.write(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n    outer loop\n")
                for v in tri:
                    fh.write(f"      vertex {v[0]:.9e} {v[1]:.9e} {v[2]:.9e}\n")
                fh.write("    endloop\n  endfacet\n")
            fh.write(f"endsolid {name}\n")


def mesh_topology(tris: np.ndarray, decimals: int = 6):
    """Weld vertices; return (points, faces, edge_use_counts)."""
    flat = np.round(tris.reshape(-1, 3), decimals)
    pts, inv = np.unique(flat, axis=0, return_inverse=True)
    faces = inv.reshape(-1, 3)
    e = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    _, counts = np.unique(e, axis=0, return_counts=True)
    return pts, faces, counts


def signed_volume(tris: np.ndarray) -> float:
    return float(np.einsum("ij,ij->i", tris[:, 0], np.cross(tris[:, 1], tris[:, 2])).sum() / 6.0)
