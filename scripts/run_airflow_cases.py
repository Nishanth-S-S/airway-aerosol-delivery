#!/usr/bin/env python3
"""Phases 4, 6, 7: run airflow cases (pimpleFoam) with automatic QA and plots.

    python scripts/run_airflow_cases.py --case healthy_constant
    python scripts/run_airflow_cases.py --case healthy_symmetric
    python scripts/run_airflow_cases.py --all            # refused until healthy_symmetric passed QA
    python scripts/run_airflow_cases.py --case n40_late --np 12 --regenerate

For each case:  mesh (reused / created, must have PASSED checkMesh) -> copy mesh ->
decomposePar -> mpirun pimpleFoam -> reconstructPar -> QA (flow conservation,
both outlets carry outflow, solver finished) -> PNG figures -> results/run_status.csv
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_airflow_cases import all_airflow_cases, generate  # noqa: E402
from lib.common import ROOT, die, load_config, read_status, rel, run_foam, update_status  # noqa: E402
from lib.foam_case import airflow_case_dir, mesh_case_dir  # noqa: E402
from lib.postproc import airflow_timeseries  # noqa: E402
import mesh_geometry  # noqa: E402

BASELINE = "healthy_symmetric"


def airflow_qa(cfg, case_dir: Path) -> dict:
    ts = airflow_timeseries(case_dir)
    if ts is None or ts.empty:
        return {"status": "FAILED", "problems": ["no flow-rate output found"]}
    T = cfg["breathing"]["inhalation_duration_s"]
    meta = json.loads((case_dir / "case_meta.json").read_text())
    if meta["flow"] == "constant":
        win = ts[ts.time > 0.5 * ts.time.max()]
    else:
        win = ts[(ts.time > 0.05 * T) & (ts.time < 0.95 * T)]
    q_in = win.Q_in.mean()
    imbalance = 100 * (win.Q_in - win.Q_out_total).abs().mean() / q_in
    split = 100 * win.Q_target.mean() / win.Q_out_total.mean()
    lim = cfg["qa"]["airflow_mass_imbalance_percent"]
    problems = []
    if imbalance > lim:
        problems.append(f"flow imbalance {imbalance:.3f} % > {lim} %")
    if (win.Q_target <= 0).mean() > 0.05 or (win.Q_comparison <= 0).mean() > 0.05:
        problems.append("an outlet does not carry outflow during inhalation")
    log = (case_dir / "logs" / "pimpleFoam.log").read_text(errors="ignore")
    finished = "\nEnd" in log or "End\n" in log
    if not finished:
        problems.append("solver did not reach endTime")
    end_t = ts.time.max()
    if end_t < meta["end_time_s"] - 1e-3:
        problems.append(f"output stops at t={end_t:.3f} s < endTime {meta['end_time_s']}")
    vol_in = float((ts.Q_in.values[1:] * (ts.time.diff().values[1:])).sum())
    return {"status": "PASSED" if not problems else "FAILED", "problems": problems,
            "mean_inlet_flow_L_min": q_in * 6e4, "mean_imbalance_percent": imbalance,
            "target_branch_ventilation_percent": split,
            "comparison_branch_ventilation_percent": 100 - split,
            "inspired_volume_mL": vol_in * 1e6,
            # constant case: exclude the 10 ms start-up acceleration from the peak
            "peak_pressure_drop_Pa": float((win if meta["flow"] == "constant" else ts[ts.time <= T + 1e-9]).dp_Pa.max()),
            "mean_pressure_drop_Pa": float(win.dp_Pa.mean()),
            "end_time_reached_s": float(end_t)}


def run_case(cfg, case_id: str, n_procs: int, regenerate: bool) -> bool:
    cases = all_airflow_cases(cfg)
    if case_id not in cases:
        die(f"unknown case {case_id}; valid: {', '.join(cases)}")
    geometry, flow = cases[case_id]
    if regenerate or not (airflow_case_dir(case_id) / "case_meta.json").exists():
        generate(cfg, case_id)
    return run_airflow(cfg, case_id, geometry, flow, n_procs)


def prepare_fresh(case_id: str, geometry: str, flow: str, n_procs: int, level: str) -> dict:
    """Fresh start of a generated case: copy the PASSED mesh + initial conditions, set the MPI size.
    Shared by run_airflow (Mac) and cloud/runner/job_airflow.py (cloud), so both run identical case setup."""
    d = airflow_case_dir(case_id)
    mesh_rep = json.loads((mesh_case_dir(geometry, level) / "mesh_report.json").read_text())
    for p in list(d.glob("processor*")) + [p for p in d.iterdir() if p.is_dir() and _is_time(p.name)]:
        shutil.rmtree(p)
    for sub in ("postProcessing", "logs", "VTK"):
        shutil.rmtree(d / sub, ignore_errors=True)
    shutil.rmtree(d / "constant" / "polyMesh", ignore_errors=True)
    shutil.copytree(mesh_case_dir(geometry, level) / "constant" / "polyMesh", d / "constant" / "polyMesh")
    shutil.copytree(d / "0.orig", d / "0")
    # write the requested MPI size into caseParameters
    cp = d / "system" / "caseParameters"
    cp.write_text("\n".join(f"nProcs   {n_procs};" if ln.startswith("nProcs") else ln
                            for ln in cp.read_text().splitlines()) + "\n")
    update_status(case_id, case_type="validation" if case_id.startswith("val_") else "airflow",
                  geometry=geometry, waveform=flow, mesh_status="PASSED",
                  solver_status="running", qa_status="pending",
                  notes=f"mesh {mesh_rep['cells']} cells; started {time.strftime('%H:%M')}")
    return mesh_rep


def run_airflow(cfg, case_id: str, geometry: str, flow: str, n_procs: int, level: str | None = None,
                plots: bool = True) -> bool:
    """Run an already generated airflow case directory cases/airflow/<case_id> (also used by validation/)."""
    level = level or cfg["mesh"]["level"]
    d = airflow_case_dir(case_id)
    print(f"\n=== Airflow case {case_id} ({geometry}, {flow}) ===")
    if not mesh_geometry.mesh_ready(geometry, level):
        print(f"  mesh {geometry}/{level} not available or not PASSED - meshing now")
        if not mesh_geometry.mesh_one(cfg, geometry, level):
            update_status(case_id, mesh_status="FAILED", solver_status="not run", qa_status="FAILED",
                          notes="mesh failed quality gate - airflow NOT run")
            return False
    mesh_rep = prepare_fresh(case_id, geometry, flow, n_procs, level)
    t0 = time.time()
    steps = [("decomposePar", "decomposePar -force"),
             ("pimpleFoam", f"mpirun -np {n_procs} --oversubscribe pimpleFoam -parallel"),
             ("reconstructPar", "reconstructPar -newTimes")]
    if n_procs <= 1:
        steps = [("pimpleFoam", "pimpleFoam")]
    for name, cmd in steps:
        rc = run_foam(cfg, d, cmd, name)
        if rc != 0:
            update_status(case_id, solver_status="FAILED", qa_status="FAILED",
                          notes=f"{name} exit {rc}; see {rel(d / 'logs' / (name + '.log'))}")
            print(f"[FAILED] {name} exit {rc}")
            return False
    for p in d.glob("processor*"):
        shutil.rmtree(p)
    elapsed = time.time() - t0
    qa = airflow_qa(cfg, d)
    qa["wallclock_min"] = round(elapsed / 60, 1)
    qa["mesh_cells"] = mesh_rep["cells"]
    (d / "qa_report.json").write_text(json.dumps(qa, indent=2))
    note = (f"{qa['wallclock_min']} min; imbalance {qa.get('mean_imbalance_percent', float('nan')):.2e} %; "
            f"target branch {qa.get('target_branch_ventilation_percent', float('nan')):.1f} % of flow; "
            f"peak dp {qa.get('peak_pressure_drop_Pa', float('nan')):.2f} Pa")
    if qa["problems"]:
        note += " | " + "; ".join(qa["problems"])
    update_status(case_id, solver_status="completed", qa_status=qa["status"], notes=note)
    print(f"[{qa['status']}] {case_id}: {note}")
    if plots:
        try:
            import plot_results
            plot_results.plot_airflow(case_id)
        except Exception as e:
            print(f"  (figures not produced: {e})")
    return qa["status"] == "PASSED"


def _is_time(name: str) -> bool:
    try:
        float(name)
        return True
    except ValueError:
        return False


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case")
    ap.add_argument("--all", action="store_true", help="run the 9 study airflow cases")
    ap.add_argument("--np", type=int, default=cfg["openfoam"]["n_procs"])
    ap.add_argument("--regenerate", action="store_true", help="rebuild the case from base_cases first")
    ap.add_argument("--skip-completed", action="store_true", help="with --all: skip cases already PASSED")
    a = ap.parse_args()
    if a.all:
        st = read_status().get(BASELINE, {})
        if st.get("qa_status") != "PASSED":
            die(f"Refusing --all: the baseline '{BASELINE}' has not passed QA yet "
                f"(status: {st.get('qa_status', 'not run')}).\n  Run: python scripts/run_airflow_cases.py --case {BASELINE}")
        ids = [c for c in all_airflow_cases(cfg) if c != "healthy_constant"]
        if a.skip_completed:
            done = read_status()
            ids = [c for c in ids if done.get(c, {}).get("qa_status") != "PASSED"]
        ok = [run_case(cfg, c, a.np, a.regenerate) for c in ids]
    elif a.case:
        ok = [run_case(cfg, a.case, a.np, a.regenerate)]
    else:
        die("give --case <id> or --all  (ids: python scripts/generate_airflow_cases.py --list)")
    sys.exit(0 if all(ok) else 2)


if __name__ == "__main__":
    main()
