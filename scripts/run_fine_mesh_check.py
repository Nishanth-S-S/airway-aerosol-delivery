#!/usr/bin/env python3
"""Fine-mesh verification (validation/04_mesh_independence/CRITERIA.md decision rule, after coarse failed C2/C4b/C5/C6).

    nohup caffeinate -i python3 scripts/run_fine_mesh_check.py > logs/fine_mesh_check.out 2>&1 &

Runs ONLY the pre-specified fine level on the same condition (T_N40_SYM), then its 1/3/5 um continuous-release maps
with the same seed and parcel count as the coarse/medium maps. Restart-safe (finished steps are skipped).
Starts no other airflow case; the main airflow queue stays gated by MESH_DECISION.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import load_config  # noqa: E402
from lib.conditions import all_conditions, load_conditions  # noqa: E402
import run_study_v002 as S  # noqa: E402

AID = "V_MESH_fine_T_N40_SYM"


def main():
    cfg = load_config()
    reg = load_conditions()
    first = [c for c in all_conditions(reg) if c["id"] == "T_N40_SYM"][0]
    if not S.run_airflow_condition(cfg, first, aid=AID, level="fine", need_mesh_approval=False):
        S.log(f"fine-mesh check: airflow {AID} did not pass - maps not run")
        sys.exit(2)
    import run_particle_cases as RP
    RP.ensure_solver(cfg)
    for d in (1, 3, 5):
        S.particle_job(cfg, first, AID, d, "continuous", reg["optimization"]["map_parcels"], 1, f"MAP_{AID}_P{d:02d}")
    S.log("fine-mesh check: airflow and 1/3/5 um maps finished")


if __name__ == "__main__":
    main()
