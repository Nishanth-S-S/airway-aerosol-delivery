#!/usr/bin/env python3
"""Phase 5: automated meshing with a hard quality gate.

    python scripts/mesh_geometry.py --geometry healthy            # mesh level from config
    python scripts/mesh_geometry.py --geometry n40 --level fine
    python scripts/mesh_geometry.py --all

Steps (logs in cases/mesh/<geometry>_<level>/logs/):
    blockMesh -> surfaceFeatureExtract -> snappyHexMesh -overwrite -> checkMesh
If checkMesh reports failed checks or exceeds config `mesh.checkmesh_limits`,
the mesh is marked FAILED in results/run_status.csv and nothing downstream may use it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, die, load_config, rel, run_foam, update_status  # noqa: E402
from lib.foam_case import build_mesh_case, mesh_case_dir  # noqa: E402

MESH_SURF_DICT = """FoamFile { version 2.0; format ascii; class dictionary; object meshSurfaces; }
functions
{
    meshCut
    {
        type surfaces; libs (sampling);
        surfaceFormat vtk;
        formatOptions { vtk { legacy true; format ascii; } }
        fields ();
        surfaces
        {
            yMid { type cuttingPlane; point (0 1e-7 0); normal (0 1 0); interpolate false; }
            walls { type patch; patches (walls); interpolate false; }
            inlet { type patch; patches (inlet); interpolate false; }
            targetOutlet { type patch; patches (targetOutlet); interpolate false; }
            comparisonOutlet { type patch; patches (comparisonOutlet); interpolate false; }
        }
    }
}
"""


def parse_checkmesh(text: str) -> dict:
    def grab(pat, cast=float, default=None):
        m = re.search(pat, text)
        return cast(m.group(1).rstrip(".")) if m else default
    r = {
        "cells": grab(r"^\s*cells:\s+(\d+)", int) if False else grab(r"\n\s*cells:\s+(\d+)", int),
        "points": grab(r"\n\s*points:\s+(\d+)", int),
        "hexahedra": grab(r"hexahedra:\s+(\d+)", int),
        "polyhedra": grab(r"polyhedra:\s+(\d+)", int),
        "max_non_orthogonality": grab(r"Mesh non-orthogonality Max:\s+([\d.eE+-]+)"),
        "avg_non_orthogonality": grab(r"Mesh non-orthogonality Max:\s+[\d.eE+-]+\s+average:\s+([\d.eE+-]+)"),
        "max_skewness": grab(r"Max skewness = ([\d.eE+-]+)"),
        "max_aspect_ratio": grab(r"Max aspect ratio = ([\d.eE+-]+)"),
        "min_volume": grab(r"Min volume = ([\d.eE+-]+)"),
        "max_volume": grab(r"Max volume = ([\d.eE+-]+)"),
        "total_volume": grab(r"Total volume = ([\d.eE+-]+)"),
        "failed_checks": grab(r"Failed (\d+) mesh checks", int, 0),
        "mesh_ok_line": "Mesh OK." in text,
        "regions_connected": "*Number of regions:" not in text,
    }
    patches = {}
    for m in re.finditer(r"^\s+(inlet|targetOutlet|comparisonOutlet|walls)\s+(\d+)\s+(\d+)\s+(ok|.*?)\s", text, re.M):
        patches[m.group(1)] = {"faces": int(m.group(2)), "points": int(m.group(3))}
    r["patches"] = patches
    return r


def mesh_one(cfg: dict, geometry: str, level: str) -> bool:
    case_id = f"mesh_{geometry}_{level}"
    print(f"\n=== Meshing {geometry} ({level}) ===")
    d = build_mesh_case(cfg, geometry, level)
    update_status(case_id, case_type="mesh", geometry=geometry, mesh_status="running", solver_status="n/a",
                  particle_status="n/a", qa_status="pending", notes=f"level={level}")
    t0 = time.time()
    steps = [("blockMesh", "blockMesh"),
             ("surfaceFeatureExtract", "surfaceFeatureExtract"),
             ("snappyHexMesh", "snappyHexMesh -overwrite"),
             ("checkMesh", "checkMesh -constant")]
    for name, cmd in steps:
        rc = run_foam(cfg, d, cmd, name)
        if rc != 0 and name != "checkMesh":
            update_status(case_id, mesh_status="FAILED", qa_status="FAILED",
                          notes=f"{name} exited with code {rc}; see {rel(d / 'logs' / (name + '.log'))}")
            print(f"[FAILED] {name} (exit {rc}) - stopping this geometry")
            return False
    text = (d / "logs" / "checkMesh.log").read_text()
    r = parse_checkmesh(text)
    lim = cfg["mesh"]["checkmesh_limits"]
    problems = []
    if r["cells"] is None:
        problems.append("checkMesh output unreadable")
    if r["failed_checks"] and not lim["allow_failed_checks"]:
        problems.append(f"checkMesh: Failed {r['failed_checks']} mesh checks")
    if r["max_non_orthogonality"] and r["max_non_orthogonality"] > lim["max_non_orthogonality"]:
        problems.append(f"non-orthogonality {r['max_non_orthogonality']:.1f} > {lim['max_non_orthogonality']}")
    if r["max_skewness"] and r["max_skewness"] > lim["max_skewness"]:
        problems.append(f"skewness {r['max_skewness']:.2f} > {lim['max_skewness']}")
    if r["min_volume"] is not None and r["min_volume"] <= lim["min_volume"]:
        problems.append(f"min cell volume {r['min_volume']:.3g} <= 0")
    for pname in ("inlet", "targetOutlet", "comparisonOutlet", "walls"):
        if r["patches"].get(pname, {}).get("faces", 0) == 0:
            problems.append(f"patch '{pname}' missing/empty")
    gc = json.loads((ROOT / "geometry" / "geometry_check.json").read_text()).get(geometry)
    stl_vol = gc["volume_mm3_stl"] * 1e-9 if gc else None
    if r["total_volume"] and stl_vol:
        r["volume_error_vs_stl_percent"] = 100 * (r["total_volume"] - stl_vol) / stl_vol
        if abs(r["volume_error_vs_stl_percent"]) > 2.0:
            problems.append(f"meshed volume differs from STL by {r['volume_error_vs_stl_percent']:.2f} %")
    r["problems"] = problems
    r["status"] = "PASSED" if not problems else "FAILED"
    r["elapsed_s"] = round(time.time() - t0, 1)
    r["geometry"], r["level"] = geometry, level
    (d / "mesh_report.json").write_text(json.dumps(r, indent=2))

    # sample y=0 cut and patches for the mesh picture (no ParaView needed)
    (d / "system" / "meshSurfaces").write_text(MESH_SURF_DICT)
    (d / "0").mkdir(exist_ok=True)
    run_foam(cfg, d, "postProcess -dict system/meshSurfaces -time 0", "meshSurfaces")
    note = (f"{r['cells']} cells, maxNonOrtho {r['max_non_orthogonality']}, maxSkew {r['max_skewness']}"
            if r["cells"] else "")
    if problems:
        note += " | " + "; ".join(problems)
    update_status(case_id, mesh_status=r["status"], qa_status=r["status"], notes=note)
    print(f"[{r['status']}] {geometry}/{level}: {note}  ({r['elapsed_s']} s)")
    try:
        import plot_results
        if geometry in cfg["geometry"]["variants"]:
            plot_results.plot_mesh(geometry, level)
    except Exception as e:  # plotting must never hide the mesh verdict
        print(f"  (mesh image not produced: {e})")
    return not problems


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geometry", choices=list(cfg["geometry"]["variants"]))
    ap.add_argument("--level", default=cfg["mesh"]["level"], choices=list(cfg["mesh"]["levels"]))
    ap.add_argument("--all", action="store_true", help="mesh all three geometries")
    a = ap.parse_args()
    if not a.geometry and not a.all:
        die("give --geometry <name> or --all")
    geoms = list(cfg["geometry"]["variants"]) if a.all else [a.geometry]
    for gname in geoms:
        from lib.common import geometry_files
        if not geometry_files(cfg, gname)["patches"].exists():
            die("geometry not prepared - run: python scripts/setup_geometry.py")
    ok = [mesh_one(cfg, g_, a.level) for g_ in geoms]
    sys.exit(0 if all(ok) else 2)


def mesh_ready(geometry: str, level: str) -> bool:
    rep = mesh_case_dir(geometry, level) / "mesh_report.json"
    return rep.exists() and json.loads(rep.read_text()).get("status") == "PASSED"


if __name__ == "__main__":
    main()
