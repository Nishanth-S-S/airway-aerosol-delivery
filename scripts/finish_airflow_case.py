#!/usr/bin/env python3
"""Finish an airflow case whose solver is still running after its coordinator was stopped (mesh-decision gate).

    python scripts/finish_airflow_case.py V_MESH_medium_T_N40_SYM --condition T_N40_SYM --wait-pid 90021

1. waits until the solver's docker client has exited (never interrupts it)
2. checks the solver log finished normally ("End", no FOAM FATAL), and the last time reached endTime
3. reconstructs the parallel data (reconstructPar -newTimes) and checks every processor time was reconstructed
   with U, p and phi, and every write time has its y = 0 section
4. only then removes processor* directories, runs the standard airflow QA and writes qa_report.json
   (the particle queue starts the case's maps only when qa_report.json says PASSED)
Writes completion_check.json with every check, pass or fail.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config, run_foam, update_status  # noqa: E402
from lib.conditions import all_conditions, cfg_for  # noqa: E402


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(ROOT / "logs" / "study_v002.log", "a") as fh:
        fh.write(line + "\n")


def times_in(d: Path):
    out = []
    for p in d.iterdir():
        try:
            out.append((float(p.name), p))
        except ValueError:
            pass
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case"); ap.add_argument("--condition", required=True); ap.add_argument("--wait-pid", type=int)
    ap.add_argument("--finished-by", default="scripts/finish_airflow_case.py (coordinator stopped at the mesh-decision gate)")
    a = ap.parse_args()
    cfg0 = load_config()
    c = [x for x in all_conditions() if x["id"] == a.condition][0]
    cfg = cfg_for(cfg0, c)
    d = ROOT / "cases" / "airflow" / a.case
    meta = json.loads((d / "case_meta.json").read_text())
    if a.wait_pid:
        while True:
            try:
                os.kill(a.wait_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(30)
    checks = {}
    logtxt = (d / "logs" / "pimpleFoam.log").read_text(errors="ignore")
    checks["solver_end_marker"] = "\nEnd" in logtxt and "Finalising parallel run" in logtxt
    checks["no_fatal_error"] = "FOAM FATAL" not in logtxt
    ptimes = times_in(d / "processor0")
    checks["processor_last_time"] = ptimes[-1][0] if ptimes else None
    checks["reached_end_time"] = bool(ptimes) and abs(ptimes[-1][0] - meta["end_time_s"]) < 1e-6
    ok = checks["solver_end_marker"] and checks["no_fatal_error"] and checks["reached_end_time"]
    if ok:
        rc = run_foam(cfg, d, "reconstructPar -newTimes", "reconstructPar")
        checks["reconstructPar_exit"] = rc
        rtimes = {round(t, 9) for t, _ in times_in(d) if t > 0}
        ptimes_set = {round(t, 9) for t, _ in ptimes if t > 0}
        checks["n_processor_times"] = len(ptimes_set)
        checks["all_times_reconstructed"] = ptimes_set <= rtimes
        missing = [t for t, p in times_in(d) if t > 0 and not all((p / f).exists() for f in ("U", "p", "phi"))]
        checks["times_missing_fields"] = missing
        mp = d / "postProcessing" / "midPlane"
        sec = {round(float(p.name), 9) for p in mp.iterdir() if (p / "yMid.vtk").exists()} if mp.exists() else set()
        checks["sections_missing"] = sorted(t for t in rtimes if t not in sec)
        ok = rc == 0 and checks["all_times_reconstructed"] and not missing and not checks["sections_missing"]
    if ok:
        for p in d.glob("processor*"):
            shutil.rmtree(p)
        import run_airflow_cases as R
        qa = R.airflow_qa(cfg, d)
        rep = json.loads((ROOT / "cases" / "mesh" / f"{meta['geometry']}_{meta['mesh_level']}" / "mesh_report.json").read_text())
        qa["mesh_cells"] = rep["cells"]
        start = (d / "logs" / "decomposePar.log").stat().st_mtime
        qa["wallclock_min"] = round((time.time() - start) / 60, 1)
        qa["finished_by"] = a.finished_by
        checks["qa_status"] = qa["status"]
        (d / "completion_check.json").write_text(json.dumps(checks, indent=2, default=float))
        (d / "qa_report.json").write_text(json.dumps(qa, indent=2))
        update_status(a.case, case_type="validation", geometry=meta["geometry"], waveform=meta["flow"], mesh_status="PASSED",
                      solver_status="completed", qa_status=qa["status"], notes=f"finished after gate; split {qa['target_branch_ventilation_percent']:.2f} %")
        log(f"airflow {qa['status']} {a.case}: finished after gate, all completion checks passed")
    else:
        (d / "completion_check.json").write_text(json.dumps(checks, indent=2, default=float))
        update_status(a.case, solver_status="INCOMPLETE", qa_status="FAILED", notes="completion checks failed: see completion_check.json")
        log(f"airflow INCOMPLETE {a.case}: completion checks failed (see completion_check.json) - NOT marked passed")
        sys.exit(2)


if __name__ == "__main__":
    main()
