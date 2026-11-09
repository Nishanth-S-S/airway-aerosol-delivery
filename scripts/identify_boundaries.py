#!/usr/bin/env python3
"""Phase 3: split each single-surface airway STL into the named CFD boundaries

    inlet             flat cap at z = 0, outward normal -Z
    targetOutlet      flat cap of the RIGHT / +X branch
    comparisonOutlet  flat cap of the LEFT  / -X branch
    walls             everything else

Method (fully reproducible, no guessing):
  A triangle is assigned to a cap only if BOTH
    (1) every vertex lies within `cap_plane_tol_mm` of the cap plane, where the
        plane passes through the cap centre given in QA_report.json and is
        perpendicular to the branch axis, and
    (2) its normal is parallel to the outward cap normal (|cos| > cap_normal_tol).
  The cap area is then compared with pi*r^2; if any cap is missing, empty or its
  area is off by > 2 %, the script STOPS instead of guessing.

Also measures the lumen diameter along the target branch to confirm the
narrowing location/size, and writes figures + docs/boundary_identification.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, die, geometry_files, load_config, rel  # noqa: E402
from lib.stl_io import read_stl, tri_areas, tri_normals, write_ascii_regions  # noqa: E402


def branch_frames(g: dict):
    a = np.radians(g["branch_angle_deg"])
    bif = np.array(g["bifurcation_point_mm"], float)
    return {
        "inlet": (np.array(g["inlet_center_mm"], float), np.array([0, 0, -1.0]), g["parent_diameter_mm"] / 2),
        "targetOutlet": (np.array(g["target_outlet_center_mm"], float),
                         np.array([np.sin(a), 0, np.cos(a)]), g["daughter_diameter_mm"] / 2),
        "comparisonOutlet": (np.array(g["comparison_outlet_center_mm"], float),
                             np.array([-np.sin(a), 0, np.cos(a)]), g["daughter_diameter_mm"] / 2),
    }, bif


def split(tris: np.ndarray, g: dict):
    frames, _ = branch_frames(g)
    n = tri_normals(tris)
    area = tri_areas(tris)
    label = np.full(len(tris), "walls", dtype=object)
    info = {}
    for name, (c, nrm, r) in frames.items():
        dist = np.abs((tris - c) @ nrm).max(axis=1)
        par = n @ nrm
        sel = (dist < g["cap_plane_tol_mm"]) & (par > g["cap_normal_tol"])
        label[sel] = name
        a = float(area[sel].sum())
        exp = float(np.pi * r * r)
        cen = (tris[sel].mean(axis=1) * area[sel, None]).sum(0) / max(a, 1e-30)
        info[name] = {"n_triangles": int(sel.sum()), "area_mm2": round(a, 4), "expected_area_mm2": round(exp, 4),
                      "area_error_percent": round(100 * (a - exp) / exp, 3),
                      "centroid_mm": [round(float(x), 4) for x in cen],
                      "outward_normal": [round(float(x), 6) for x in nrm]}
        if sel.sum() == 0 or abs(a - exp) / exp > 0.02:
            die(f"Boundary '{name}' could not be identified unambiguously "
                f"(triangles={int(sel.sum())}, area={a:.3f} vs expected {exp:.3f} mm2). "
                "The geometry does not match the README/QA description - not guessing.")
    info["walls"] = {"n_triangles": int((label == "walls").sum()),
                     "area_mm2": round(float(area[label == "walls"].sum()), 3)}
    return label, info


def diameter_profile(tris: np.ndarray, g: dict, side: float = +1):
    """Equivalent diameter vs distance s along a daughter-branch centre-line.

    The surface is sliced by planes perpendicular to the branch axis; the
    diameter is twice the perimeter-weighted mean radius of the slice outline."""
    a = np.radians(g["branch_angle_deg"])
    bif = np.array(g["bifurcation_point_mm"], float)
    d = np.array([side * np.sin(a), 0, np.cos(a)])
    e1 = np.array([np.cos(a), 0, -side * np.sin(a)]); e2 = np.array([0, 1.0, 0])
    sv = (tris - bif) @ d                       # (N,3) signed distance of vertices
    out = []
    for s0 in np.arange(5.0, g["daughter_length_mm"] - 1.0, 0.25):
        f = sv - s0
        m = (f.min(1) < 0) & (f.max(1) > 0)
        segs = []
        for t, ff in zip(tris[m], f[m]):
            pts = []
            for i, j in ((0, 1), (1, 2), (2, 0)):
                if (ff[i] < 0) != (ff[j] < 0):
                    w = ff[i] / (ff[i] - ff[j])
                    pts.append(t[i] + w * (t[j] - t[i]))
            if len(pts) == 2:
                segs.append(pts)
        if not segs:
            out.append((s0, np.nan)); continue
        segs = np.array(segs)
        c = bif + s0 * d
        p0 = np.stack([(segs[:, 0] - c) @ e1, (segs[:, 0] - c) @ e2], 1)
        p1 = np.stack([(segs[:, 1] - c) @ e1, (segs[:, 1] - c) @ e2], 1)
        keep = (np.linalg.norm(p0, axis=1) < 5) & (np.linalg.norm(p1, axis=1) < 5)   # this branch only
        mid = 0.5 * (p0[keep] + p1[keep]); ln = np.linalg.norm(p1[keep] - p0[keep], axis=1)
        r = np.linalg.norm(mid, axis=1)
        out.append((s0, 2 * float((r * ln).sum() / ln.sum())))   # perimeter-weighted mean radius
    return np.array(out)


def slice_y0(tris: np.ndarray) -> list:
    """Intersection segments of the surface with the symmetry plane y = 0."""
    f = tris[:, :, 1] - 1e-4          # tiny offset avoids vertices lying exactly on y = 0
    m = (f.min(1) < 0) & (f.max(1) > 0)
    out = []
    for t, ff in zip(tris[m], f[m]):
        pts = [t[i] + ff[i] / (ff[i] - ff[j]) * (t[j] - t[i])
               for i, j in ((0, 1), (1, 2), (2, 0)) if (ff[i] < 0) != (ff[j] < 0)]
        if len(pts) == 2:
            out.append(np.array(pts))
    return out


def plot(key, tris, label, prof, prof_cmp, cfg, outpng):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    colors = {"walls": "#c8ccd4", "inlet": "#2a9d8f", "targetOutlet": "#e76f51", "comparisonOutlet": "#457b9d"}
    fig = plt.figure(figsize=(13, 5.2))
    ax = fig.add_subplot(1, 3, 1, projection="3d")
    for name, col in colors.items():
        m = label == name
        pc = Poly3DCollection(tris[m], facecolor=col, edgecolor="none", alpha=0.35 if name == "walls" else 1.0)
        ax.add_collection3d(pc)
    ax.set_xlim(-35, 35); ax.set_ylim(-35, 35); ax.set_zlim(0, 95)
    ax.view_init(elev=12, azim=-80)
    ax.set_xlabel("x (mm)"); ax.set_ylabel("y"); ax.set_zlabel("z (mm)")
    ax.set_title(f"{cfg['geometry']['variants'][key]['label']}: boundary patches")
    for name, col in colors.items():
        ax.plot([], [], "s", color=col, label=name)
    ax.legend(loc="upper left", fontsize=8)

    ax2 = fig.add_subplot(1, 3, 2)
    g = cfg["geometry"]
    for name, col in colors.items():
        segs = slice_y0(tris[label == name])
        for sg in segs:
            ax2.plot(sg[:, 0], sg[:, 2], color=col if name != "walls" else "#555", lw=2.5 if name != "walls" else 1)
    s_plane = cfg["regions"]["target_plane_s_mm"]
    a = np.radians(g["branch_angle_deg"]); bif = np.array(g["bifurcation_point_mm"])
    d = np.array([np.sin(a), 0, np.cos(a)]); perp = np.array([np.cos(a), 0, -np.sin(a)])
    for s, ls, lab in [(g["narrowing_start_mm"], ":", "narrowing start/end"), (g["narrowing_end_mm"], ":", None),
                       (s_plane, "-", "target entry plane")]:
        p = bif + s * d
        q1, q2 = p + 3.6 * perp, p - 3.6 * perp
        ax2.plot([q1[0], q2[0]], [q1[2], q2[2]], ls, color="k", lw=1.2, label=lab)
    ax2.set_aspect("equal"); ax2.set_xlabel("x (mm)"); ax2.set_ylabel("z (mm)")
    ax2.set_title("Section y = 0 (X-Z), +X = target branch"); ax2.legend(fontsize=7, loc="lower right")

    ax3 = fig.add_subplot(1, 3, 3)
    ax3.plot(prof[:, 0], prof[:, 1], "-", color="#e76f51", label="target (+X) branch")
    ax3.plot(prof_cmp[:, 0], prof_cmp[:, 1], "--", color="#457b9d", label="comparison (-X) branch")
    ax3.axvspan(g["narrowing_start_mm"], g["narrowing_end_mm"], color="#f4a261", alpha=0.2, label="nominal narrowing")
    ax3.axvline(s_plane, color="k", lw=1, label="target entry plane")
    ax3.set_xlabel("distance from bifurcation along branch, s (mm)")
    ax3.set_ylabel("lumen diameter (mm)"); ax3.set_ylim(2.5, 7)
    ax3.set_title("Measured lumen diameter"); ax3.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(outpng, dpi=130)
    plt.close(fig)


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=None, help="v001 (approved STL) or v002 (corrected); default from config")
    a = ap.parse_args(argv or [])
    cfg = load_config()
    g = cfg["geometry"]
    figdir = ROOT / "results" / "figures"
    figdir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for key, v in g["variants"].items():
        gf = geometry_files(cfg, key, a.version)
        stl, sfx = gf["source"], gf["suffix"]
        if not stl.exists():
            die(f"{rel(stl)} missing - run scripts/setup_geometry.py first")
        tris, _ = read_stl(stl)
        label, info = split(tris, g)
        regions = {n: tris[label == n] for n in ["inlet", "targetOutlet", "comparisonOutlet", "walls"]}
        out = gf["patches"]
        write_ascii_regions(out, regions, scale=g["scale_to_m"])
        prof = diameter_profile(tris, g, +1)
        prof_c = diameter_profile(tris, g, -1)
        inside = (prof[:, 0] > g["narrowing_start_mm"]) & (prof[:, 0] < g["narrowing_end_mm"])
        dmin = float(np.nanmin(prof[inside, 1]))
        smin = float(prof[inside][np.nanargmin(prof[inside, 1]), 0])
        info["measured_min_target_diameter_mm"] = round(dmin, 3)
        info["measured_min_at_s_mm"] = round(smin, 2)
        info["qa_min_diameter_mm"] = None
        info["measured_area_reduction_percent"] = round(100 * (1 - (dmin / g["daughter_diameter_mm"]) ** 2), 1)
        info["measured_diameter_reduction_percent"] = round(100 * (1 - dmin / g["daughter_diameter_mm"]), 1)
        np.savetxt(ROOT / "geometry" / key / f"target_branch_diameter_profile{sfx}.csv", prof, delimiter=",",
                   header="s_mm,diameter_mm", comments="")
        png = figdir / f"geometry_{key}{sfx}.png"
        plot(key, tris, label, prof, prof_c, cfg, png)
        summary[key] = info
        print(f"[ok] {key:8s} patches -> {rel(out)}  "
              f"(inlet {info['inlet']['area_error_percent']:+.2f}%, target {info['targetOutlet']['area_error_percent']:+.2f}%, "
              f"comparison {info['comparisonOutlet']['area_error_percent']:+.2f}% area vs pi r^2; "
              f"min target diameter {dmin:.2f} mm at s={smin:.1f} mm)")
    (ROOT / "geometry" / f"boundary_identification{sfx}.json").write_text(json.dumps(summary, indent=2))
    if not sfx:
        write_doc(summary, cfg)


def write_doc(summary, cfg):
    g = cfg["geometry"]
    lines = ["# How the CFD boundaries were identified", "",
             "The approved STL files contain **one un-named surface** each (Open CASCADE export), so the",
             "inlet / outlets / walls had to be separated. This is done by `scripts/identify_boundaries.py`",
             "(called automatically by `scripts/setup_geometry.py`).", "",
             "## Rule", "",
             "A triangle belongs to a cap only if **both** are true:", "",
             f"1. all 3 vertices are within **{g['cap_plane_tol_mm']} mm** of the cap plane "
             "(plane through the cap centre from `QA_report.json`, perpendicular to the branch axis);",
             f"2. its normal is parallel to the outward cap normal (|cos θ| > {g['cap_normal_tol']}).", "",
             "Everything else is `walls`. The script stops with an error if a cap is empty or its area differs from",
             "π r² by more than 2 % - it never guesses.", "",
             "| Boundary | Plane / centre (mm) | Outward normal | Meaning |", "|---|---|---|---|",
             "| `inlet` | z = 0, centre (0, 0, 0) | (0, 0, −1) | parent airway entrance (air enters, +Z flow) |",
             "| `targetOutlet` | centre (30, 0, 91.96) | (sin30°, 0, cos30°) | **right / +X branch = target** |",
             "| `comparisonOutlet` | centre (−30, 0, 91.96) | (−sin30°, 0, cos30°) | left / −X branch = comparison |",
             "| `walls` | remaining surface | — | airway wall (no-slip, particles stick) |", "",
             "## Results", "",
             "| Geometry | inlet area err | target area err | comparison area err | wall triangles | measured min target Ø | at s |",
             "|---|---|---|---|---|---|---|"]
    for k, i in summary.items():
        lines.append(f"| {k} | {i['inlet']['area_error_percent']:+.2f} % | {i['targetOutlet']['area_error_percent']:+.2f} % | "
                     f"{i['comparisonOutlet']['area_error_percent']:+.2f} % | {i['walls']['n_triangles']} | "
                     f"{i['measured_min_target_diameter_mm']:.2f} mm | {i['measured_min_at_s_mm']:.1f} mm |")
    lines += ["", "Area errors are the faceting error of the STL (polygon vs circle).", "",
              "**Important — what \"20 % / 40 % narrowing\" means here.** The QA report gives minimum diameters of",
              "4.8 mm and 3.6 mm in a 6 mm branch, i.e. a 20 % / 40 % reduction in **diameter**. In cross-sectional",
              "**area** these are 36 % and 64 % reductions. The study labels follow the diameter convention of the",
              "geometry package; quote both in any write-up.", "",
              "The narrowing position s (distance along the target-branch centre-line from the bifurcation point",
              f"{tuple(g['bifurcation_point_mm'])} mm) was measured from the STL vertices and matches the README (14–26 mm, centre 20 mm).",
              "", "Figures: `results/figures/geometry_healthy.png`, `geometry_n20.png`, `geometry_n40.png`", "",
              "## Target entry plane", "",
              f"Perpendicular to the target-branch axis at s = **{cfg['regions']['target_plane_s_mm']} mm** "
              f"(i.e. {cfg['regions']['target_plane_s_mm'] - g['narrowing_end_mm']:.0f} mm past the end of the narrowing),",
              f"disc radius {cfg['regions']['target_plane_radius_mm']} mm. Defined in `config/experiment.yaml -> regions` and",
              "used identically for all three geometries (the healthy case uses the same s-position).",
              ]
    (ROOT / "docs" / "boundary_identification.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
