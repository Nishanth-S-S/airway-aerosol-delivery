#!/usr/bin/env python3
"""Corrected airway geometry v002 (STL), rebuilt from the README / QA dimensions.

    python scripts/build_geometry_v002.py            # writes geometry/<healthy|n20|n40>/airway_v002.stl

Why: the approved v001 CAD (union of three cylinders) has two junction defects
(docs/GEOMETRY_QA.md):
  1. a flat annular shelf at z = 40 mm (17.6 mm2, 35 % of the parent cross-section)
     facing straight into the inhaled flow, and
  2. the daughter cylinders protrude backwards through the parent wall
     (pockets up to 0.42 mm deep at z = 37.4-38.7 mm on the +/-x sides).

v002 keeps everything else identical (8 mm x 40 mm parent, 6 mm x 60 mm daughters at
+/-30 deg, same outlet centres, same cosine narrowing 14-26 mm, min 4.8 / 3.6 mm) and
replaces the junction with a smooth transition:
  * parent = tube ending in a hemispherical dome at the bifurcation point,
  * daughters = tubes starting at the bifurcation point,
  * smooth union of the two daughters (carina blend radius k_carina, ~0.5 mm fillet as in v001),
  * smooth union of parent and daughters (junction blend radius k_junction, 1 mm),
  * target-branch narrowing r(s) = the profile measured on the v001 STL (exact reproduction),
then cut flat at the inlet and outlet planes. Surface extracted by marching cubes.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config, rel  # noqa: E402
from lib.stl_io import mesh_topology, signed_volume, tri_areas, write_ascii_regions  # noqa: E402


def smin(a, b, k):
    """Polynomial smooth minimum (blend radius ~k)."""
    if k <= 0:
        return np.minimum(a, b)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


def tube_sdf(p, a, u, s0, s1, radius_fn, offset_fn=None, e=None):
    """Distance to a tube of radius r(s) around the axis a + s u (optionally shifted by off(s) e)."""
    s = np.clip((p - a) @ u, s0, s1)
    foot = a + s[..., None] * u
    if offset_fn is not None:
        foot = foot + offset_fn(s)[..., None] * e
    return np.linalg.norm(p - foot, axis=-1) - radius_fn(s)


def narrowing_radius(cfg, key):
    """Radius r(s) of the target branch, taken from the profile MEASURED on the approved v001
    STL (geometry/<key>/target_branch_diameter_profile.csv), so the narrowing is reproduced
    exactly (it is not a pure cosine). Outside the narrowing r = daughter radius."""
    g = cfg["geometry"]
    R = g["daughter_diameter_mm"] / 2
    pr = np.loadtxt(ROOT / "geometry" / key / "target_branch_diameter_profile.csv", delimiter=",", skiprows=1)
    s_a, s_b = g["narrowing_start_mm"] - 0.5, g["narrowing_end_mm"] + 0.5
    m = (pr[:, 0] >= s_a) & (pr[:, 0] <= s_b)
    ss, rr = pr[m, 0], np.minimum(pr[m, 1] / 2, R)

    def r(s):
        return np.where((s > s_a) & (s < s_b), np.interp(s, ss, rr), R)
    return r


def _edge_point(a, b, da, db):
    """Plane crossing on edge a-b, computed in a canonical order so both neighbouring
    triangles get bit-identical points (keeps the mesh watertight)."""
    if tuple(a) > tuple(b):
        a, b, da, db = b, a, db, da
    return a + da / (da - db) * (b - a)


def clip_and_cap(tris, c, n):
    """Keep the part of a closed surface with (p - c).n <= 0 and close it with a flat cap."""
    d = (tris - c) @ n
    keep = []
    loop = []
    for t, dd in zip(tris, d):
        inside = dd <= 0
        k = inside.sum()
        if k == 3:
            keep.append(t); continue
        if k == 0:
            continue
        # rotate so the odd vertex is first
        odd = int(np.where(inside != (k == 2))[0][0]) if k in (1, 2) else 0
        idx = [odd, (odd + 1) % 3, (odd + 2) % 3]
        A, B, C = t[idx]; dA, dB, dC = dd[idx]
        pAB, pAC = _edge_point(A, B, dA, dB), _edge_point(A, C, dA, dC)
        if k == 1:          # only A inside
            keep.append(np.array([A, pAB, pAC]))
        else:               # A outside, B and C inside
            keep.append(np.array([pAB, B, C])); keep.append(np.array([pAB, C, pAC]))
        loop += [pAB, pAC]
    keep = np.array(keep)
    loop = np.unique(np.array(loop), axis=0)
    centre = loop.mean(0)
    e1 = loop[0] - centre; e1 -= (e1 @ n) * n; e1 /= np.linalg.norm(e1); e2 = np.cross(n, e1)
    ang = np.arctan2((loop - centre) @ e2, (loop - centre) @ e1)
    ring = loop[np.argsort(ang)]
    cap = np.array([[centre, ring[(i + 1) % len(ring)], ring[i]] for i in range(len(ring))])
    # cap must face outward (+n)
    if np.cross(cap[0, 1] - cap[0, 0], cap[0, 2] - cap[0, 0]) @ n < 0:
        cap = cap[:, ::-1]
    return np.concatenate([keep, cap])


def scaled_profile(cfg, shape_from, d_min_mm):
    """Narrowing with the measured shape of `shape_from` but depth scaled to minimum diameter d_min."""
    g = cfg["geometry"]
    R = g["daughter_diameter_mm"] / 2
    base = narrowing_radius(cfg, shape_from)
    s_grid = np.linspace(0, 70, 2801)
    rb = base(s_grid)
    depth = (R - rb) / max(R - rb.min(), 1e-9)                # 0..1 shape
    r_new = R - depth * (R - d_min_mm / 2)
    return lambda s: np.interp(s, s_grid, r_new)


def build(cfg, key, h, k_carina, k_junction, spec=None):
    from skimage.measure import marching_cubes
    g = cfg["geometry"]
    a = math.radians(g["branch_angle_deg"])
    bif = np.array(g["bifurcation_point_mm"], float)
    uz = np.array([0, 0, 1.0])
    uR, uL = np.array([math.sin(a), 0, math.cos(a)]), np.array([-math.sin(a), 0, math.cos(a)])
    Rp, Rd, L = g["parent_diameter_mm"] / 2, g["daughter_diameter_mm"] / 2, g["daughter_length_mm"]
    const = lambda r: (lambda s: np.full_like(s, r, dtype=float))  # noqa: E731
    off_fn, e_off = None, None
    if spec is not None:                       # held-out geometry from config/conditions.yaml
        r_target = scaled_profile(cfg, spec["shape_from"], spec["min_diameter_mm"])
        if spec.get("eccentric"):
            # lumen centre shifted toward the inner (carina-side) wall so the outer wall carries the
            # whole narrowing; minimum open area equals that of the concentric case
            e_off = -np.array([math.cos(a), 0, -math.sin(a)])
            off_fn = lambda s: Rd - r_target(s)  # noqa: E731
    else:
        v = g["variants"][key]
        r_target = narrowing_radius(cfg, key) if v["narrowing_percent"] else const(Rd)
    OR, OL = bif + L * uR, bif + L * uL

    xs = np.arange(-37, 37 + h, h); ys = np.arange(-5, 5 + h, h); zs = np.arange(-4.0, 98.0 + h, h)
    F = np.empty((len(xs), len(ys), len(zs)), np.float32)
    # extend tubes past the caps so the surface is closed far outside the cut planes
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    for k, z in enumerate(zs):
        p = np.stack([X, Y, np.full_like(X, z)], -1)
        parent = tube_sdf(p, np.array([0, 0, -5.0]), uz, 0, 5 + bif[2], const(Rp))        # capsule: dome at bif
        right = tube_sdf(p, bif, uR, 0, L + 5, r_target, off_fn, e_off)
        left = tube_sdf(p, bif, uL, 0, L + 5, const(Rd))
        u = smin(parent, smin(right, left, k_carina), k_junction)
        F[:, :, k] = u            # tubes extend beyond the caps; caps are cut exactly below
    verts, faces, _, _ = marching_cubes(F, 0.0, spacing=(h, h, h))
    verts += np.array([xs[0], ys[0], zs[0]])
    tris = verts[faces]
    if signed_volume(tris) < 0:            # outward normals
        tris = tris[:, ::-1]
    for c, n in ((np.zeros(3), -uz), (OR, uR), (OL, uL)):
        tris = clip_and_cap(tris, c, n)
    tris = tris[tri_areas(tris) > 1e-10]
    return tris


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--h", type=float, default=0.25, help="voxel size (mm); 0.25 -> ~150k triangles, shape error ~0.003 mm")
    ap.add_argument("--k-carina", type=float, default=0.5)
    ap.add_argument("--k-junction", type=float, default=1.0)
    ap.add_argument("--only", nargs="*", help="build only these keys (study variants or extra_geometries)")
    a = ap.parse_args()
    import yaml
    extra = yaml.safe_load((ROOT / "config" / "conditions.yaml").read_text()).get("extra_geometries", {})
    report = {}
    keys = list(cfg["geometry"]["variants"]) + list(extra)
    for key in (a.only or keys):
        spec = extra.get(key)
        (ROOT / "geometry" / key).mkdir(parents=True, exist_ok=True)
        tris = build(cfg, key, a.h, a.k_carina, a.k_junction, spec)
        out = ROOT / "geometry" / key / "airway_v002.stl"
        write_ascii_regions(out, {"airway": tris})
        _, _, ec = mesh_topology(tris, 5)
        report[key] = {"triangles": int(len(tris)), "watertight": bool((ec == 2).all()),
                       "open_edges": int((ec == 1).sum()), "non_manifold_edges": int((ec > 2).sum()),
                       "volume_mm3": round(signed_volume(tris), 2), "voxel_mm": a.h,
                       "k_carina_mm": a.k_carina, "k_junction_mm": a.k_junction}
        print(f"[ok] {rel(out)}: {report[key]}")
        if spec is not None:      # split boundaries for held-out geometries here
            import identify_boundaries as IB
            from lib.stl_io import write_ascii_regions as W
            lab, info = IB.split(tris, cfg["geometry"])
            W(ROOT / "geometry" / key / "airway_patches_m_v002.stl",
              {n: tris[lab == n] for n in ["inlet", "targetOutlet", "comparisonOutlet", "walls"]}, scale=cfg["geometry"]["scale_to_m"])
            prof = IB.diameter_profile(tris, cfg["geometry"], +1)
            np.savetxt(ROOT / "geometry" / key / "target_branch_diameter_profile_v002.csv", prof, delimiter=",",
                       header="s_mm,diameter_mm", comments="")
            m = (prof[:, 0] > 14) & (prof[:, 0] < 26)
            report[key]["min_equiv_diameter_mm"] = round(float(np.nanmin(prof[m, 1])), 3)
            report[key]["caps"] = {k: v["area_error_percent"] for k, v in info.items() if isinstance(v, dict) and "area_error_percent" in v}
            print(f"     {key}: min equivalent diameter {report[key]['min_equiv_diameter_mm']} mm, caps {report[key]['caps']}")
    old = ROOT / "geometry" / "geometry_v002_build.json"
    prev = json.loads(old.read_text()) if old.exists() else {}
    prev.update(report)
    old.write_text(json.dumps(prev, indent=2))


if __name__ == "__main__":
    main()
