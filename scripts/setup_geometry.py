#!/usr/bin/env python3
"""Phase 1-3: unpack the Onshape ZIP, preserve originals, organise the three
approved geometries, check they are CFD-usable, and split boundary patches.

    python scripts/setup_geometry.py [--zip path/to/package.zip]

Result:
    input/original_package/       untouched copy of every file in the ZIP (read-only)
    input/original_package/MANIFEST.sha256
    geometry/<healthy|n20|n40>/airway.stl        original STL (mm), byte-identical copy
    geometry/<healthy|n20|n40>/airway.step       original STEP, byte-identical copy
    geometry/<...>/airway_patches_m.stl          named patches, metres (used by OpenFOAM)
    geometry/geometry_check.json                 watertightness / volume / bbox checks
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, die, load_config, rel  # noqa: E402
from lib.stl_io import mesh_topology, read_stl, signed_volume, tri_areas, write_ascii_regions  # noqa: E402


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", default=str(ROOT / cfg["project"]["geometry_zip"]))
    args = ap.parse_args()
    zpath = Path(args.zip)
    if not zpath.exists():
        die(f"Geometry ZIP not found: {zpath}\n  Put the Onshape package at {cfg['project']['geometry_zip']} "
            f"or pass --zip <path>.")

    variants = cfg["geometry"]["variants"]
    expected = ["README.txt", "QA_report.json", cfg["geometry"]["comparison_step"]]
    for v in variants.values():
        expected += [v["source_stem"] + ".stl", v["source_stem"] + ".step"]

    # ---------------------------------------------------------------- unpack
    orig = ROOT / "input" / "original_package"
    orig.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as zf:
        names = {Path(n).name: n for n in zf.namelist() if not n.endswith("/")}
        missing = [e for e in expected if e not in names]
        if missing:
            die("The ZIP is missing expected file(s):\n  - " + "\n  - ".join(missing) +
                f"\nFound: {sorted(names)}")
        for base, member in names.items():
            dst = orig / base
            if dst.exists():
                dst.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            with zf.open(member) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
            dst.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # read-only: preserve originals
    manifest = {n: sha256(orig / n) for n in sorted(names)}
    (orig / "MANIFEST.sha256").write_text("".join(f"{h}  {n}\n" for n, h in manifest.items()))
    print(f"[ok] all {len(expected)} expected files found; originals preserved in {rel(orig)} (read-only)")

    qa = json.loads((orig / "QA_report.json").read_text())

    # ---------------------------------------------------------------- organise + check
    report = {}
    for key, v in variants.items():
        gdir = ROOT / "geometry" / key
        gdir.mkdir(parents=True, exist_ok=True)
        for ext in ("stl", "step"):
            src = orig / f"{v['source_stem']}.{ext}"
            dst = gdir / f"airway.{ext}"
            if dst.exists():
                dst.chmod(0o644)
            shutil.copyfile(src, dst)
            assert sha256(dst) == manifest[src.name], f"copy mismatch {dst}"
        raw, _ = read_stl(gdir / "airway.stl")
        _, _, raw_counts = mesh_topology(raw)
        # Cleaning: the Open CASCADE export contains collapsed (zero-area) triangles at the
        # junction saddle points; they create 2 open + 2 non-manifold edges. Removing them is
        # lossless (zero area => zero geometry change). Originals stay untouched.
        degenerate = tri_areas(raw) < 1e-12
        tris = raw[~degenerate]
        write_ascii_regions(gdir / "airway_clean.stl", {"airway": tris})
        pts, faces, edge_counts = mesh_topology(tris)
        vol = signed_volume(tris)
        q = qa[v["source_stem"]]
        bb = q["bounding_box_mm"]
        chk = {
            "source": v["source_stem"],
            "narrowing_percent": v["narrowing_percent"],
            "n_triangles_original": int(len(raw)),
            "original_open_edges": int((raw_counts == 1).sum()),
            "original_non_manifold_edges": int((raw_counts > 2).sum()),
            "degenerate_triangles_removed": int(degenerate.sum()),
            "n_triangles": int(len(tris)),
            "n_vertices": int(len(pts)),
            "watertight": bool((edge_counts == 2).all()),
            "open_edges": int((edge_counts == 1).sum()),
            "non_manifold_edges": int((edge_counts > 2).sum()),
            "outward_normals": bool(vol > 0),
            "volume_mm3_stl": round(abs(vol), 3),
            "volume_mm3_qa": q["volume_mm3"],
            "volume_error_percent": round(100 * (abs(vol) - q["volume_mm3"]) / q["volume_mm3"], 3),
            "bbox_mm_stl": [list(map(lambda x: round(float(x), 4), tris.reshape(-1, 3).min(0))),
                            list(map(lambda x: round(float(x), 4), tris.reshape(-1, 3).max(0)))],
            "bbox_mm_qa": [[bb["xmin"], bb["ymin"], bb["zmin"]], [bb["xmax"], bb["ymax"], bb["zmax"]]],
            "qa_min_diameter_mm": q["target_min_diameter_mm"],
        }
        bbox_err = max(abs(a - b) for lo_hi in zip(chk["bbox_mm_stl"], chk["bbox_mm_qa"])
                       for a, b in zip(*lo_hi))
        chk["bbox_max_error_mm"] = round(bbox_err, 4)
        chk["cfd_usable"] = bool(chk["watertight"] and chk["non_manifold_edges"] == 0 and
                                 abs(chk["volume_error_percent"]) < 1.0 and bbox_err < 0.05)
        report[key] = chk
        flag = "ok" if chk["cfd_usable"] else "PROBLEM"
        print(f"[{flag}] {key:8s} <- {v['source_stem']}.stl : {chk['n_triangles']} triangles, "
              f"removed {chk['degenerate_triangles_removed']} zero-area tris -> watertight={chk['watertight']}, volume err {chk['volume_error_percent']:+.2f}% vs QA, "
              f"bbox err {bbox_err:.3f} mm")
    (ROOT / "geometry" / "geometry_check.json").write_text(json.dumps(report, indent=2))
    if not all(r["cfd_usable"] for r in report.values()):
        die("At least one STL failed the CFD-usability checks; see geometry/geometry_check.json")

    # ---------------------------------------------------------------- boundary patches
    import identify_boundaries  # noqa: E402
    identify_boundaries.main([])


if __name__ == "__main__":
    main()
