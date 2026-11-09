#!/usr/bin/env python3
"""Phase 4/6/7: generate airflow cases from base_cases/airflow (never hand-copied).

    python scripts/generate_airflow_cases.py                    # the 9 study cases + healthy_constant
    python scripts/generate_airflow_cases.py --case healthy_symmetric
    python scripts/generate_airflow_cases.py --list

Case ids: <geometry>_<waveform>  (healthy|n20|n40 x early|symmetric|late)
          healthy_constant        (Phase-4 smoke test: constant 2 L/min)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import die, load_config, rel, update_status  # noqa: E402
from lib.foam_case import build_airflow_case  # noqa: E402


def all_airflow_cases(cfg) -> dict[str, tuple[str, str]]:
    cases = {"healthy_constant": ("healthy", "constant")}
    for g in cfg["geometry"]["variants"]:
        for w in cfg["breathing"]["waveforms"]:
            cases[f"{g}_{w}"] = (g, w)
    return cases


def generate(cfg, case_id: str):
    cases = all_airflow_cases(cfg)
    if case_id not in cases:
        die(f"unknown airflow case '{case_id}'. Valid: {', '.join(cases)}")
    g, w = cases[case_id]
    d = build_airflow_case(cfg, case_id, g, w)
    update_status(case_id, case_type="airflow", geometry=g, waveform=w, mesh_status="pending",
                  solver_status="generated", particle_status="n/a", qa_status="pending",
                  notes=f"generated in {rel(d)}")
    print(f"[ok] generated {rel(d)}")
    return d


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    cases = all_airflow_cases(cfg)
    if a.list:
        print("\n".join(cases)); return
    for cid in ([a.case] if a.case else cases):
        generate(cfg, cid)


if __name__ == "__main__":
    main()
