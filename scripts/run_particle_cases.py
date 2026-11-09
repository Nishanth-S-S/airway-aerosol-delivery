#!/usr/bin/env python3
"""Phases 8-13: run particle cases on a stored airflow solution (one-way coupling).

    python scripts/run_particle_cases.py --case P03_CONT_HLT_SYM
    python scripts/run_particle_cases.py --all [--jobs 4]          # refused until P03_CONT_HLT_SYM passed QA
    python scripts/run_particle_cases.py --all --geometry n40 --waveform late

Gates: the referenced airflow case must have PASSED QA; --all also requires the
development case to have PASSED. Each run: link the airflow mesh -> airwayParcelFoam ->
extract metrics / mass balance -> PNGs -> results.csv + run_status.csv.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_particle_cases import DEV_CASE, case_matrix  # noqa: E402
from lib.common import ROOT, die, load_config, read_status, rel, run_foam, update_status  # noqa: E402
from lib.foam_case import build_particle_case  # noqa: E402
import extract_results  # noqa: E402

SOLVER = ROOT / "tools" / "openfoam" / "bin" / "airwayParcelFoam"


def ensure_solver(cfg):
    if SOLVER.exists():
        return
    print("  compiling airwayParcelFoam (one time)")
    src = ROOT / "tools" / "openfoam" / "airwayParcelFoam"
    bin_dir = "/work/tools/openfoam/bin" if cfg["openfoam"]["runner"] == "docker" else str(SOLVER.parent)
    rc = run_foam(cfg, src, f"export AIRWAY_BIN={bin_dir}; wmake", "wmake")
    if rc != 0 or not SOLVER.exists():
        die(f"could not compile the particle solver; see {rel(src / 'logs' / 'wmake.log')}")


def run_one(cfg, row, regenerate: bool) -> bool:
    cid = row.case_id
    ctype = "particle" if cid.startswith("P") else "validation"
    af = ROOT / "cases" / "airflow" / row.airflow_case
    afqa = af / "qa_report.json"
    if not afqa.exists() or json.loads(afqa.read_text()).get("status") != "PASSED":
        update_status(cid, case_type=ctype, geometry=row.geometry, waveform=row.waveform,
                      particle_size_um=row.particle_size_um, release_strategy=row.release_strategy,
                      particle_status="blocked", qa_status="pending",
                      notes=f"airflow {row.airflow_case} has not passed QA")
        print(f"[blocked] {cid}: airflow {row.airflow_case} has not passed QA "
              f"(python scripts/run_airflow_cases.py --case {row.airflow_case})")
        return False
    d = ROOT / "cases" / "particles" / cid
    if regenerate or not (d / "case_meta.json").exists():
        build_particle_case(cfg, row.particle_size_um, row.release_strategy, row.geometry, row.waveform)
    for sub in ("postProcessing", "logs"):
        shutil.rmtree(d / sub, ignore_errors=True)
    for p in d.iterdir():
        if p.is_dir() and _is_time(p.name) and p.name != "0":
            shutil.rmtree(p)
    (d / "0").mkdir(exist_ok=True)
    pm = d / "constant" / "polyMesh"
    if pm.is_symlink() or pm.exists():
        pm.unlink() if pm.is_symlink() else shutil.rmtree(pm)
    os.symlink(os.path.relpath(af / "constant" / "polyMesh", pm.parent), pm)   # reuse airflow mesh
    update_status(cid, case_type=ctype, geometry=row.geometry, waveform=row.waveform,
                  particle_size_um=row.particle_size_um, release_strategy=row.release_strategy,
                  mesh_status="PASSED", particle_status="running", qa_status="pending",
                  notes=f"started {time.strftime('%H:%M')} on airflow {row.airflow_case}")
    t0 = time.time()
    exe = "/work/tools/openfoam/bin/airwayParcelFoam" if cfg["openfoam"]["runner"] == "docker" else str(SOLVER)
    rc = run_foam(cfg, d, exe, "airwayParcelFoam")
    if rc != 0:
        update_status(cid, particle_status="FAILED", qa_status="FAILED",
                      notes=f"solver exit {rc}; see {rel(d / 'logs' / 'airwayParcelFoam.log')}")
        print(f"[FAILED] {cid}: solver exit {rc}")
        return False
    r = extract_results.extract_case(cfg, cid)
    extract_results.rebuild_results_csv()
    print(f"[{r['qa_status']}] {cid} in {(time.time() - t0) / 60:.1f} min: target delivery "
          f"{r['target_delivery_percent']:.2f} %, mass balance error {r['mass_balance_error_percent']:.2e} %"
          + (f" | {r['qa_notes']}" if r["qa_notes"] else ""))
    try:
        import plot_results
        plot_results.plot_particles(cid)
    except Exception as e:
        print(f"  (figures not produced: {e})")
    return r["qa_status"] == "PASSED"


def _is_time(n):
    try:
        float(n); return True
    except ValueError:
        return False


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--geometry"); ap.add_argument("--waveform"); ap.add_argument("--size", type=float)
    ap.add_argument("--release")
    ap.add_argument("--jobs", type=int, default=1, help="particle cases to run at the same time (serial solver each)")
    ap.add_argument("--regenerate", action="store_true")
    ap.add_argument("--skip-completed", action="store_true")
    a = ap.parse_args()
    m = case_matrix(cfg)
    if a.case:
        sel = m[m.case_id == a.case]
        if sel.empty:
            die(f"unknown case id {a.case}")
    elif a.all:
        if read_status().get(DEV_CASE, {}).get("qa_status") != "PASSED":
            die(f"Refusing --all: development case {DEV_CASE} has not passed QA.\n"
                f"  Run: python scripts/run_particle_cases.py --case {DEV_CASE}")
        sel = m
        for col, val in (("geometry", a.geometry), ("waveform", a.waveform), ("particle_size_um", a.size),
                         ("release_strategy", a.release)):
            if val is not None:
                sel = sel[sel[col] == val]
        if a.skip_completed:   # judged from each case's own results.json (the status table is only a view)
            def done(c):
                f = ROOT / "cases" / "particles" / c / "results.json"
                return f.exists() and json.loads(f.read_text()).get("qa_status") == "PASSED"
            sel = sel[[not done(c) for c in sel.case_id]]
    else:
        die("give --case <id> or --all")
    ensure_solver(cfg)
    rows = list(sel.itertuples())
    if a.jobs > 1:
        with ThreadPoolExecutor(a.jobs) as ex:
            ok = list(ex.map(lambda r: run_one(cfg, r, a.regenerate), rows))
    else:
        ok = [run_one(cfg, r, a.regenerate) for r in rows]
    print(f"\n{sum(ok)}/{len(ok)} particle case(s) passed QA")
    sys.exit(0 if all(ok) else 2)


if __name__ == "__main__":
    main()
