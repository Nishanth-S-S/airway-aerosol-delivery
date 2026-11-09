#!/usr/bin/env python3
"""Mesh one geometry at one level with the project's gated procedure (blockMesh, surfaceFeatureExtract,
snappyHexMesh, checkMesh quality gate) - identical to the Mac path.   python3 cloud/runner/job_mesh.py n20 medium"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.common import load_config  # noqa: E402
from lib.conditions import all_conditions, cfg_for  # noqa: E402
import mesh_geometry  # noqa: E402

geo, level = sys.argv[1], sys.argv[2]
if mesh_geometry.mesh_ready(geo, level):
    print(f"mesh {geo}/{level} already PASSED"); sys.exit(0)
c = [c for c in all_conditions() if c["geometry"] == geo][0]
sys.exit(0 if mesh_geometry.mesh_one(cfg_for(load_config(), c), geo, level) else 2)
