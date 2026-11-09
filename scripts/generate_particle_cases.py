#!/usr/bin/env python3
"""Phases 8-10, 14: generate particle cases (4 sizes x 4 releases x 3 geometries x 3 waveforms).

    python scripts/generate_particle_cases.py --case P03_CONT_HLT_SYM   # development case
    python scripts/generate_particle_cases.py --all                     # all 144 case folders
    python scripts/generate_particle_cases.py --matrix-only             # just the planning table

Case id  P<dd>_<RELEASE>_<GEOM>_<WAVE>, e.g. P03_MID_N40_SYM =
         3 um, middle release (F 0.30-0.40), 40 % narrowing, symmetric breathing.

Each case REUSES airflow case <geometry>_<waveform> (no airflow is re-solved).
Equal introduced mass: every case introduces config particles.introduced_mass_kg;
parcel weighting n_p = M / (N_parcels * rho_p * pi d^3 / 6) is stored in case_meta.json
and in results/tables/particle_case_matrix.csv.
"""
from __future__ import annotations

import argparse
import itertools
import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.breathing import release_window  # noqa: E402
from lib.common import ROOT, die, load_config, read_status, rel, update_status  # noqa: E402
from lib.foam_case import build_particle_case, particle_case_id  # noqa: E402

DEV_CASE = "P03_CONT_HLT_SYM"


def case_matrix(cfg) -> pd.DataFrame:
    p = cfg["particles"]
    rows = []
    for d_um, strat, geom, wave in itertools.product(p["diameters_um"], p["release_strategies"],
                                                     cfg["geometry"]["variants"], cfg["breathing"]["waveforms"]):
        cid = particle_case_id(cfg, d_um, strat, geom, wave)
        rw = release_window(cfg, wave, strat)
        m_particle = p["density"] * math.pi * (d_um * 1e-6) ** 3 / 6
        rows.append({"case_id": cid, "particle_size_um": d_um, "release_strategy": strat,
                     "geometry": geom, "narrowing_percent": cfg["geometry"]["variants"][geom]["narrowing_percent"],
                     "waveform": wave, "airflow_case": f"{geom}_{wave}",
                     "release_F_start": rw["F_start"], "release_F_end": rw["F_end"],
                     "release_t_start_s": round(rw["t_start_s"], 5), "release_t_end_s": round(rw["t_end_s"], 5),
                     "introduced_mass_kg": p["introduced_mass_kg"], "n_parcels": p["parcels_per_case"],
                     "physical_particles_per_parcel": p["introduced_mass_kg"] / (p["parcels_per_case"] * m_particle),
                     "total_physical_particles": p["introduced_mass_kg"] / m_particle})
    return pd.DataFrame(rows)


def generate(cfg, row) -> Path:
    d = build_particle_case(cfg, row.particle_size_um, row.release_strategy, row.geometry, row.waveform)
    st = read_status().get(row.case_id, {})
    update_status(row.case_id, case_type="particle", geometry=row.geometry, waveform=row.waveform,
                  particle_size_um=row.particle_size_um, release_strategy=row.release_strategy,
                  mesh_status=st.get("mesh_status") or "from airflow", solver_status=st.get("solver_status") or "n/a",
                  particle_status="generated", qa_status="pending", notes=f"reuses airflow {row.airflow_case}")
    return d


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--matrix-only", action="store_true")
    a = ap.parse_args()
    m = case_matrix(cfg)
    out = ROOT / "results" / "tables" / "particle_case_matrix.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    m.to_csv(out, index=False)
    print(f"[ok] {rel(out)}: {len(m)} particle cases "
          f"({len(cfg['particles']['diameters_um'])} sizes x {len(cfg['particles']['release_strategies'])} releases x "
          f"{len(cfg['geometry']['variants'])} geometries x {len(cfg['breathing']['waveforms'])} waveforms), "
          f"{m.airflow_case.nunique()} airflow solutions reused")
    if a.matrix_only:
        return
    if a.case:
        sel = m[m.case_id == a.case]
        if sel.empty:
            die(f"unknown case id {a.case}; see {rel(out)}")
    elif a.all:
        sel = m
    else:
        sel = m[m.case_id == DEV_CASE]
    for row in sel.itertuples():
        d = generate(cfg, row)
    print(f"[ok] generated {len(sel)} case folder(s) under {rel(d.parent)}")


if __name__ == "__main__":
    main()
