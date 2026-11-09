#!/usr/bin/env python3
"""Continuous-release response maps (seed 1, map_parcels) on one airflow case, sizes given, run in parallel.

    python3 cloud/runner/job_maps.py C_EQ_medium_T_N40_SYM --condition T_N40_SYM --sizes 1 3 5 [--case-prefix MAP_]
Same particle_job() as the Mac queue (scripts/run_study_v002.py)."""
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.common import load_config  # noqa: E402
from lib.conditions import all_conditions, load_conditions  # noqa: E402
import run_study_v002 as S  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("aid"); ap.add_argument("--condition", required=True)
ap.add_argument("--sizes", type=int, nargs="+", default=[1, 3, 5]); ap.add_argument("--case-id", default=None)
a = ap.parse_args()
cfg = load_config(); reg = load_conditions()
c = [x for x in all_conditions(reg) if x["id"] == a.condition][0]
import run_particle_cases as RP  # noqa: E402
RP.ensure_solver(cfg)
with ThreadPoolExecutor(len(a.sizes)) as ex:
    ok = list(ex.map(lambda d: S.particle_job(cfg, c, a.aid, d, "continuous", reg["optimization"]["map_parcels"], 1,
                                              (a.case_id or f"MAP_{a.aid}_P{{d:02d}}").format(d=d)), a.sizes))
sys.exit(0 if all(ok) else 2)
