#!/usr/bin/env python3
"""Geometry QA: compare the approved v001 STL with the corrected v002 STL.

    python scripts/geometry_qa.py

Checks: flat faces facing the flow, wall protruding outside the parent radius below the
junction, cross-sections at y = 0 and x = 0, narrowing profile, volume.
Writes results/figures/geometry_qa/*.png and geometry/geometry_qa.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, geometry_files, load_config  # noqa: E402
from lib.stl_io import read_stl, signed_volume, tri_areas, tri_normals  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

OUT = ROOT / "results" / "figures" / "geometry_qa"


def section(tris, axis, value=1e-4):
    f = tris[:, :, axis] - value
    m = (f.min(1) < 0) & (f.max(1) > 0)
    segs = []
    for t, ff in zip(tris[m], f[m]):
        pts = [t[i] + ff[i] / (ff[i] - ff[j]) * (t[j] - t[i]) for i, j in ((0, 1), (1, 2), (2, 0)) if (ff[i] < 0) != (ff[j] < 0)]
        if len(pts) == 2:
            segs.append(np.array(pts))
    return segs


def metrics(tris, cfg):
    n, A, c = tri_normals(tris), tri_areas(tris), tris.mean(1)
    caps = (np.abs(c[:, 2]) < 1e-6) | (c[:, 2] > 85)
    # wall area facing the oncoming parent flow head-on (normal within 25 deg of +z) in the junction zone
    facing = (n[:, 2] > np.cos(np.radians(25))) & (c[:, 2] > 30) & (c[:, 2] < 46) & ~caps
    r = np.hypot(tris.reshape(-1, 3)[:, 0], tris.reshape(-1, 3)[:, 1])
    z = tris.reshape(-1, 3)[:, 2]
    below = z < 40 - 1e-6
    return {"flat_flow_facing_area_mm2": round(float(A[facing].sum()), 3),
            "max_radius_below_junction_mm": round(float(r[below].max()), 3),
            "parent_area_mm2": round(np.pi * (cfg["geometry"]["parent_diameter_mm"] / 2) ** 2, 3),
            "volume_mm3": round(signed_volume(tris), 2)}


def main():
    cfg = load_config()
    OUT.mkdir(parents=True, exist_ok=True)
    rep = {}
    data = {}
    for key in cfg["geometry"]["variants"]:
        for ver in ("v001", "v002"):
            f = geometry_files(cfg, key, ver)["source"]
            if f.exists():
                t, _ = read_stl(f)
                data[(key, ver)] = t
                rep.setdefault(key, {})[ver] = metrics(t, cfg)
    (ROOT / "geometry" / "geometry_qa.json").write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep, indent=1))

    # junction close-up: y = 0 and x = 0 sections, v001 vs v002
    fig, axs = plt.subplots(1, 4, figsize=(17, 6.2))
    for ax, (axis, lab, horiz) in zip(axs[:2], [(1, "section y = 0 (x-z plane)", 0), (0, "section x = 0 (y-z plane)", 1)]):
        for ver, col, lw in (("v001", "#c62828", 2.2), ("v002", "#1565c0", 1.4)):
            if ("healthy", ver) in data:
                segs = [s[:, [horiz, 2]] for s in section(data[("healthy", ver)], axis)]
                ax.add_collection(LineCollection(segs, colors=col, linewidths=lw, label=ver))
        ax.set_xlim(-7, 7); ax.set_ylim(32, 50); ax.set_aspect("equal"); ax.grid(alpha=.3)
        ax.set_xlabel("x (mm)" if horiz == 0 else "y (mm)"); ax.set_ylabel("z (mm)"); ax.set_title(f"Healthy junction, {lab}")
        ax.plot([], [], color="#c62828", lw=2.2, label="v001 (approved)"); ax.plot([], [], color="#1565c0", lw=1.4, label="v002 (corrected)")
        ax.legend(loc="lower left", fontsize=8)
        ax.annotate("flat shelf\n(faces the flow)", xy=(3.6 if horiz == 0 else 3.5, 40), xytext=(4.2, 34.5), fontsize=8,
                    color="#c62828", arrowprops=dict(arrowstyle="->", color="#c62828"))
    axs[0].annotate("pocket outside\nparent wall", xy=(4.35, 38.0), xytext=(4.3, 42.5), fontsize=8, color="#c62828",
                    arrowprops=dict(arrowstyle="->", color="#c62828"))
    # cross-section area along z through the junction
    ax = axs[2]
    for ver, col in (("v001", "#c62828"), ("v002", "#1565c0")):
        t = data.get(("healthy", ver))
        if t is None:
            continue
        zz = np.arange(30, 48, 0.25); area = []
        gx, gy = np.meshgrid(np.arange(-7, 7, 0.05), np.arange(-5, 5, 0.05))
        P = np.c_[gx.ravel(), gy.ravel()]
        for z0 in zz:
            segs = np.array(section(t, 2, z0 + 1e-4))[:, :, :2]   # (S,2,2) in x-y; offset avoids vertex rows
            a, b = segs[:, 0], segs[:, 1]
            # ray towards +x: count crossings (even-odd rule)
            cond = (a[:, 1][None] > P[:, 1:2]) != (b[:, 1][None] > P[:, 1:2])
            xint = a[:, 0][None] + (P[:, 1:2] - a[:, 1][None]) * (b[:, 0] - a[:, 0])[None] / (b[:, 1] - a[:, 1] + 1e-30)[None]
            inside = ((cond & (P[:, 0:1] < xint)).sum(1) % 2) == 1
            area.append(inside.sum() * 0.05 ** 2)
        ax.plot(zz, area, color=col, lw=2, label=ver)
    ax.axhline(np.pi * 16, color="grey", ls=":", lw=1, label="parent area (8 mm)")
    ax.axhline(2 * np.pi * 9, color="grey", ls="--", lw=1, label="2 daughters (6 mm)")
    ax.set_xlabel("z (mm)"); ax.set_ylabel("lumen cross-section area at height z (mm²)")
    ax.set_title("Area through the junction\n(v001 drops abruptly at z = 40)"); ax.legend(fontsize=8); ax.grid(alpha=.3)
    # narrowing profile check
    ax = axs[3]
    for key, ls in (("n20", "-"), ("n40", "--")):
        for ver, col in (("v001", "#c62828"), ("v002", "#1565c0")):
            f = ROOT / "geometry" / key / f"target_branch_diameter_profile{'' if ver == 'v001' else '_v002'}.csv"
            if f.exists():
                pr = np.loadtxt(f, delimiter=",", skiprows=1)
                ax.plot(pr[:, 0], pr[:, 1], ls, color=col, lw=1.6, label=f"{key} {ver}")
    ax.set_xlim(5, 40); ax.set_xlabel("s along target branch (mm)"); ax.set_ylabel("diameter (mm)")
    ax.set_title("Narrowing profile (must be unchanged)"); ax.legend(fontsize=8); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(OUT / "junction_v001_vs_v002.png", dpi=130); plt.close(fig)
    print("[png] results/figures/geometry_qa/junction_v001_vs_v002.png")


if __name__ == "__main__":
    main()
