#!/usr/bin/env python3
"""Post-mesh-decision analysis pipeline (runs after MESH_DECISION.json is approved). Restart-safe; halts at gates.

    python scripts/analysis_pipeline.py

Stages (each waits for its prerequisites; a failed gate stops the pipeline and is logged):
  S1  training airflow (9) + training maps (36) + 144 baseline cases exist
  G1  solver audit (A1-A6) passes for every v002 particle case                -> else HALT
  S2  solver recheck runs (seeds, parcel counts, force model)
  G2  response map unbiased on protocol pulses: |mean z| <= 3 x SE(mean z) and >= 90 % of |z| <= 2  -> else HALT
  S3  optimisation: select + FREEZE strategies from training maps only (before any held-out evaluation run)
  S4  held-out airflow (8) + held-out maps; verification airflow (Courant 1, outlet split) + their 3 um maps
  S5  evaluation runs of frozen A/B/C (fresh seed) on all 17 conditions
  S6  reports: audit, recheck, map check, optimisation, baseline analysis, verification summaries
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config  # noqa: E402
from lib.conditions import all_conditions, load_conditions  # noqa: E402

LOG = ROOT / "logs" / "study_v002.log"
PC = ROOT / "cases" / "particles"
AF = ROOT / "cases" / "airflow"
STATE = ROOT / "logs" / "analysis_pipeline_state.json"


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} PIPELINE {msg}"
    print(line, flush=True)
    with open(LOG, "a") as fh:
        fh.write(line + "\n")


def state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def mark(stage, **kw):
    s = state(); s[stage] = {"done": time.strftime("%Y-%m-%d %H:%M:%S"), **kw}; STATE.write_text(json.dumps(s, indent=2))


def passed(aid):
    q = AF / aid / "qa_report.json"
    return q.exists() and json.loads(q.read_text()).get("status") == "PASSED"


def has(case):
    return (PC / case / "results.json").exists()


def wait_for(desc, fn, every=120):
    t0 = time.time()
    while not fn():
        if time.time() - t0 > 60 and int(time.time() - t0) % 3600 < every:
            log(f"waiting: {desc}")
        time.sleep(every)


def py(*args):
    r = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)
    (ROOT / "logs" / f"pipeline_{Path(args[0]).stem}_{args[1] if len(args) > 1 else ''}.out").write_text(r.stdout + r.stderr)
    return r.returncode, r.stdout


def halt(msg):
    log(f"HALT: {msg}")
    sys.exit(3)


def main():
    cfg = load_config()
    reg = load_conditions()
    sizes = reg["optimization"]["sizes_um"]
    train = [c["id"] for c in reg["training"]]
    test = [c["id"] for c in reg["test"]]
    st = state()

    # S1
    wait_for("training airflow", lambda: all(passed(c) for c in train))
    wait_for("training maps", lambda: all(has(f"MAP_{c}_P{d:02d}") for c in train for d in sizes))
    wait_for("144 baseline", lambda: len(list(PC.glob("P[0-9][0-9]_*/results.json"))) >= 144)
    # G1
    if "G1" not in st:
        rc, out = py("scripts/solver_recheck.py", "audit")
        a = json.loads((ROOT / "validation" / "03_particle_mass_conservation" / "results" / "solver_audit_v002.json").read_text())
        if a["cases_with_problems"] or not (a["all_airflow_links_ok"] and a["all_geometry_hashes_ok"] and a["all_planes_ok"]):
            halt(f"solver audit found problems: {a['problem_cases'][:10]}")
        mark("G1", cases=a["cases_with_results"])
        log(f"G1 passed: solver audit clean on {a['cases_with_results']} cases")
    # S2
    if "S2" not in state():
        rc, _ = py("scripts/solver_recheck.py", "runs")
        rc2, _ = py("scripts/solver_recheck.py", "report")
        mark("S2", rc=rc, rc_report=rc2)
        log("S2 solver recheck runs finished")
    # G2
    if "G2" not in state():
        py("scripts/map_check_v002.py")
        s = json.loads((ROOT / "results" / "response_map_v002" / "summary.json").read_text())["protocol|delivery"]
        ok = abs(s["mean_z"]) <= 3 * s["mean_z_se"] and s["frac_abs_z_le_2"] >= 0.9
        mark("G2", ok=ok, mean_z=s["mean_z"], mean_z_se=s["mean_z_se"], frac=s["frac_abs_z_le_2"], n=s["n"])
        if not ok:
            halt(f"response map biased on protocol pulses (mean z {s['mean_z']:.2f} +/- {s['mean_z_se']:.2f}, "
                 f"|z|<=2 in {100 * s['frac_abs_z_le_2']:.0f} %) - optimisation via the map not justified")
        log(f"G2 passed: map unbiased on {s['n']} protocol pulses (mean z {s['mean_z']:.2f} +/- {s['mean_z_se']:.2f})")
    # S3 freeze (training only; held-out evaluation runs do not exist yet)
    if not (ROOT / "results" / "optimization" / "frozen_strategies.json").exists():
        if any(PC.glob("E_*")):
            halt("evaluation runs exist before strategies were frozen")
        rc, out = py("scripts/optimize.py", "select")
        if rc != 0:
            halt(f"selection failed: {out[-500:]}")
        log("S3 strategies selected from training maps and FROZEN")
    # S4
    wait_for("held-out airflow", lambda: all(passed(c) for c in test), every=300)
    wait_for("held-out maps", lambda: all(has(f"MAP_{c}_P{d:02d}") for c in test for d in sizes), every=300)
    # S5
    if "S5" not in state():
        rc, _ = py("scripts/optimize.py", "evaluate")
        mark("S5", rc=rc)
        log("S5 evaluation runs finished")
    # verification airflow particle runs (3 um continuous) once those airflows pass
    if "S4v" not in state():
        import run_study_v002 as S
        first = [c for c in all_conditions(reg) if c["id"] == "T_N40_SYM"][0]
        wait_for("verification airflow", lambda: all(passed(a) for a in ("V_CO1_T_N40_SYM", "V_OBC30_T_N40_SYM", "V_OBC50_T_N40_SYM")), every=300)
        import os
        from concurrent.futures import ThreadPoolExecutor
        vjobs = [(aid, d) for aid in ("V_CO1_T_N40_SYM", "V_OBC30_T_N40_SYM", "V_OBC50_T_N40_SYM") for d in (1, 3, 5)]
        with ThreadPoolExecutor(int(os.environ.get("AIRWAY_PARTICLE_JOBS", "1"))) as ex:
            list(ex.map(lambda j: S.particle_job(cfg, first, j[0], j[1], "continuous", reg["optimization"]["map_parcels"], 1,
                                                 f"MAP_{j[0]}_P{j[1]:02d}"), vjobs))
        mark("S4v")
    # S6
    for args in (("scripts/solver_recheck.py", "audit"), ("scripts/map_check_v002.py",), ("scripts/optimize.py", "report"),
                 ("scripts/extract_results.py", "--all"), ("scripts/analyze_results.py",)):
        py(*args)
    mark("S6")
    log("S6 reports regenerated - analysis pipeline complete")


if __name__ == "__main__":
    main()
