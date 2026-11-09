#!/usr/bin/env python3
"""Freeze geometry v002 and archive all v001 simulation data (nothing is deleted).

    python scripts/freeze_and_archive.py

1. geometry/FROZEN_v002.json : SHA-256 of every v002 STL / patch file, the config, the condition
   registry and the particle-solver source, plus the decision record.
2. archive/v001/              : cases/{mesh,airflow,particles} are MOVED here, results/ is COPIED here,
                                then v001-specific generated outputs are cleared from results/.
3. config/experiment.yaml     : geometry.version -> v002.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT  # noqa: E402


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    cfgp = ROOT / "config" / "experiment.yaml"
    files = sorted(list(ROOT.glob("geometry/*/airway_v002.stl")) + list(ROOT.glob("geometry/*/airway_patches_m_v002.stl")))
    freeze = {
        "frozen_on": dt.datetime.now().isoformat(timespec="seconds"),
        "geometry_version": "v002",
        "decision": "v002 adopted as the primary geometry: v001 has a flow-facing flat shelf (35 % of the parent "
                    "area) and wall pockets at the junction (docs/GEOMETRY_QA.md). Recommended by the AI assistant; "
                    "REQUIRES SIGN-OFF by the research team (docs/DECISIONS.md, D-01).",
        "files": {str(f.relative_to(ROOT)): sha(f) for f in files},
        "config_sha256": sha(cfgp),
        "conditions_sha256": sha(ROOT / "config" / "conditions.yaml"),
        "solver_source_sha256": sha(ROOT / "tools" / "openfoam" / "airwayParcelFoam" / "airwayParcelFoam.C"),
    }
    (ROOT / "geometry" / "FROZEN_v002.json").write_text(json.dumps(freeze, indent=2))
    print(f"[ok] geometry/FROZEN_v002.json ({len(files)} files hashed)")

    arch = ROOT / "archive" / "v001"
    arch.mkdir(parents=True, exist_ok=True)
    for sub in ("mesh", "airflow", "particles"):
        src = ROOT / "cases" / sub
        if src.exists() and any(src.iterdir()):
            dst = arch / "cases" / sub
            if dst.exists():
                sys.exit(f"{dst} already exists - refusing to overwrite an archive")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            src.mkdir()
            print(f"[ok] moved cases/{sub} -> archive/v001/cases/{sub}")
    if not (arch / "results").exists():
        shutil.copytree(ROOT / "results", arch / "results")
        print("[ok] copied results/ -> archive/v001/results")
    for f in ("results.csv", "run_status.csv", "report.html", "summary_report.html"):
        (ROOT / "results" / f).unlink(missing_ok=True)
    shutil.rmtree(ROOT / "results" / "visualizations", ignore_errors=True)
    shutil.rmtree(ROOT / "results" / "figures" / "analysis", ignore_errors=True)
    for f in (ROOT / "results" / "tables").glob("analysis_*"):
        f.unlink()
    (arch / "README.md").write_text(
        "# v001 dataset (archived)\n\nAll simulations run on the approved Onshape geometry v001 "
        "(junction shelf + pockets, see docs/GEOMETRY_QA.md): 9 airflow solutions, 144 particle cases, meshes, "
        "validation 01-03, reports. Coarse mesh, max Courant 3. Kept unchanged for comparison; "
        "never mixed with v002 results. Paths inside case files still refer to cases/... (pre-archive).\n")
    s = cfgp.read_text()
    s = re.sub(r"^(  version:\s*)v001", r"\g<1>v002", s, count=1, flags=re.M)
    cfgp.write_text(s)
    print("[ok] config geometry.version -> v002")


if __name__ == "__main__":
    main()
