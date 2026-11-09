#!/usr/bin/env python3
"""Orchestrates the v002 study (docs/PREREGISTRATION.md). Restart-safe: finished work is skipped.

    python scripts/run_study_v002.py airflow      # airflow queue (training, mesh check, test, verification)
    python scripts/run_study_v002.py particles    # particle queue: response maps + 144 baseline (waits for airflow)
    python scripts/run_study_v002.py status

Airflow cases: cases/airflow/<condition id>  (e.g. T_N40_SYM, H5_N20_SYM_1)
Verification:  cases/airflow/V_MESH_medium_T_N40_SYM, V_CO1_T_N40_SYM, V_OBC40_T_N40_SYM ...
Particle maps: cases/particles/MAP_<condition>_P<d>     (continuous release, map_parcels parcels)
Baseline 144:  cases/particles/P<dd>_<REL>_<GEOM>_<WAVE> (original ids, on the T_* airflow)
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config  # noqa: E402
from lib.conditions import all_conditions, cfg_for, load_conditions, wave_name  # noqa: E402
from lib.foam_case import airflow_case_dir, build_airflow_case, build_particle_case, particle_case_id  # noqa: E402

LOG = ROOT / "logs" / "study_v002.log"
HOLD = ROOT / "logs" / "HOLD_AIRFLOW"                       # create this file to pause between cases (graceful)
MESH_DECISION = ROOT / "validation" / "04_mesh_independence" / "results" / "MESH_DECISION.json"


def log(msg):
    LOG.parent.mkdir(exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as fh:
        fh.write(line + "\n")


def airflow_passed(aid):
    q = airflow_case_dir(aid) / "qa_report.json"
    return q.exists() and json.loads(q.read_text()).get("status") == "PASSED"


def wait_until_allowed(aid, need_mesh_approval):
    """Graceful pause point, checked BEFORE a case starts (never during one)."""
    announced = False
    while True:
        hold = HOLD.exists()
        approved = True
        if need_mesh_approval:
            approved = MESH_DECISION.exists() and json.loads(MESH_DECISION.read_text()).get("approved") is True
        if not hold and approved:
            return
        if not announced:
            why = "hold file present" if hold else "mesh decision not approved (" + str(MESH_DECISION.relative_to(ROOT)) + ")"
            log(f"airflow queue waiting before {aid}: {why}")
            announced = True
        time.sleep(30)


def build_condition_case(cfg, c, aid, level=None, edit=None, cfg_mod=None):
    """Generate cases/airflow/<aid> for condition c (mesh must exist). Shared by the Mac queue and the cloud runner."""
    k = cfg_for(cfg, c)
    if cfg_mod:
        cfg_mod(k)
    level = level or k["mesh"]["level"]
    build_airflow_case(k, aid, c["geometry"], wave_name(c), level)
    meta = json.loads((airflow_case_dir(aid) / "case_meta.json").read_text())
    meta.update({"condition": c["id"], "split": c.get("split"), "flow_lpm": c["flow_lpm"], "beta": [c["a"], c["b"]],
                 "geometry_version": k["geometry"]["version"]})
    (airflow_case_dir(aid) / "case_meta.json").write_text(json.dumps(meta, indent=2))
    if edit:
        edit(airflow_case_dir(aid))
    return k, level


def run_airflow_condition(cfg, c, aid=None, level=None, edit=None, cfg_mod=None, np_=8, need_mesh_approval=True):
    import mesh_geometry
    import run_airflow_cases as R
    aid = aid or c["id"]
    if airflow_passed(aid):
        return True
    wait_until_allowed(aid, need_mesh_approval)
    k0 = cfg_for(cfg, c)
    if cfg_mod:
        cfg_mod(k0)
    lvl = level or k0["mesh"]["level"]
    if not mesh_geometry.mesh_ready(c["geometry"], lvl):
        log(f"mesh {c['geometry']}/{lvl}")
        if not mesh_geometry.mesh_one(k0, c["geometry"], lvl):
            log(f"MESH FAILED {c['geometry']}/{lvl}")
            return False
    k, level = build_condition_case(cfg, c, aid, level, edit, cfg_mod)
    log(f"airflow start {aid} ({c['geometry']}, Beta({c['a']},{c['b']}), {c['flow_lpm']} L/min, mesh {level})")
    ok = R.run_airflow(k, aid, c["geometry"], wave_name(c), np_, level, plots=False)
    q = json.loads((airflow_case_dir(aid) / "qa_report.json").read_text()) if (airflow_case_dir(aid) / "qa_report.json").exists() else {}
    log(f"airflow {'PASSED' if ok else 'FAILED'} {aid}: {q.get('wallclock_min')} min, split {q.get('target_branch_ventilation_percent')}, "
        f"imbalance {q.get('mean_imbalance_percent')}")
    return ok


def outlet_split_edit(frac):
    from run_validation import STUDIES  # noqa: F401  (keeps import side effects identical)
    import re

    def edit(d):
        tbl = (d / "constant" / "inletFlowRate").read_text()
        rows = re.findall(r"\(([-\d.eE+]+)\s+([-\d.eE+]+)\)", tbl)
        (d / "constant" / "targetOutletFlowRate").write_text(
            "(\n" + "\n".join(f"    ({t} {float(q) * frac:.10g})" for t, q in rows) + "\n)\n")
        u = (d / "0.orig" / "U").read_text().replace(
            "targetOutlet     { type pressureInletOutletVelocity; value uniform (0 0 0); }",
            "targetOutlet     { type flowRateOutletVelocity; volumetricFlowRate { type tableFile; "
            "file \"<constant>/targetOutletFlowRate\"; outOfBounds clamp; } value uniform (0 0 0); }")
        (d / "0.orig" / "U").write_text(u)
        p = (d / "0.orig" / "p").read_text().replace(
            "targetOutlet     { type totalPressure; p0 uniform 0; value uniform 0; }", "targetOutlet     { type zeroGradient; }")
        (d / "0.orig" / "p").write_text(p)
    return edit


def _co1(k):
    """time-step independence: Courant 1 with 1 outer corrector"""
    k["airflow"]["max_courant"] = 1.0
    k["airflow"]["n_outer_correctors"] = 1
    k["airflow"]["n_correctors"] = 2


def airflow_specs(cfg):
    """Every v002 airflow case in queue order: dicts with aid, condition, level, edit, cfg_mod, need_mesh_approval."""
    reg = load_conditions()
    conds = {c["id"]: c for c in all_conditions(reg)}
    first = conds["T_N40_SYM"]
    S = [dict(aid="T_N40_SYM", c=first, level=None, edit=None, cfg_mod=None, need_mesh_approval=False),
         # mesh independence on the hardest training condition, before the rest
         dict(aid="V_MESH_medium_T_N40_SYM", c=first, level="medium", edit=None, cfg_mod=None, need_mesh_approval=False)]
    # every later case waits for an approved MESH_DECISION.json (validation/04_mesh_independence/CRITERIA.md)
    for c in reg["training"] + reg["test"]:
        if c["id"] != "T_N40_SYM":
            S.append(dict(aid=c["id"], c=conds[c["id"]], level=None, edit=None, cfg_mod=None, need_mesh_approval=True))
    S.append(dict(aid="V_CO1_T_N40_SYM", c=first, level=None, edit=None, cfg_mod=_co1, need_mesh_approval=True))
    # outlet-condition sensitivity: prescribed target share (healthy split ~50 %, N40 ~39 %)
    for frac in (0.30, 0.50):
        S.append(dict(aid=f"V_OBC{int(frac * 100)}_T_N40_SYM", c=first, level=None, edit=outlet_split_edit(frac),
                      cfg_mod=None, need_mesh_approval=True))
    return S


def airflow_queue(cfg):
    for s in airflow_specs(cfg):
        run_airflow_condition(cfg, s["c"], aid=s["aid"], level=s["level"], edit=s["edit"], cfg_mod=s["cfg_mod"],
                              need_mesh_approval=s["need_mesh_approval"])
    log("airflow queue finished")


# ------------------------------------------------------------------ particles
def particle_job(cfg, c, aid, d_um, strategy, n_parcels, seed, case_id):
    import extract_results
    import run_particle_cases as RP
    f = ROOT / "cases" / "particles" / case_id / "results.json"
    if f.exists() and json.loads(f.read_text()).get("solver_status") == "completed":
        return True
    k = cfg_for(cfg, c)
    build_particle_case(k, d_um, strategy, c["geometry"], wave_name(c), n_parcels=n_parcels, seed=seed,
                        case_id=case_id, airflow_id=aid)
    row = SimpleNamespace(case_id=case_id, airflow_case=aid, geometry=c["geometry"], waveform=wave_name(c),
                          particle_size_um=d_um, release_strategy=strategy)
    ok = RP.run_one(k, row, regenerate=False)
    if f.exists():
        r = json.loads(f.read_text())
        log(f"particles {r['qa_status']} {case_id}: delivery {r['target_delivery_percent']:.2f} %, n {r['n_parcels']}, "
            f"balance {r['mass_balance_error_percent']:.1e} %")
    return ok


def particle_tasks(cfg):
    reg = load_conditions()
    opt = reg["optimization"]
    tasks = []
    waves_short = {(2, 5): "EAR", (3, 3): "SYM", (5, 2): "LAT"}
    geo_short = {"healthy": "HLT", "n20": "N20", "n40": "N40"}
    for c in all_conditions(reg):
        aid = c["id"]
        for d in opt["sizes_um"]:
            tasks.append((aid, c, d, "continuous", opt["map_parcels"], 1, f"MAP_{c['id']}_P{d:02d}"))
    for c in reg["training"]:
        c = {**c, "split": "training"}
        for d in cfg["particles"]["diameters_um"]:
            for strat, spec in cfg["particles"]["release_strategies"].items():
                cid = f"P{d:02d}_{spec['short']}_{geo_short[c['geometry']]}_{waves_short[(c['a'], c['b'])]}"
                tasks.append((c["id"], c, d, strat, opt["eval_parcels"], 1, cid))
    # map for the medium-mesh check (3 um and 1 um)
    first = [c for c in all_conditions(reg) if c["id"] == "T_N40_SYM"][0]
    for d in (1, 3):
        tasks.insert(8, ("V_MESH_medium_T_N40_SYM", first, d, "continuous", opt["map_parcels"], 1, f"MAP_V_MESH_medium_T_N40_SYM_P{d:02d}"))
    return tasks


def particle_queue(cfg, jobs):
    import run_particle_cases as RP
    RP.ensure_solver(cfg)
    pending = particle_tasks(cfg)
    log(f"particle queue: {len(pending)} tasks")
    with ThreadPoolExecutor(jobs) as ex:
        futures = {}
        while pending or futures:
            ready = [t for t in pending if airflow_passed(t[0])]
            while ready and len(futures) < jobs:
                t = ready.pop(0)
                pending.remove(t)
                futures[ex.submit(particle_job, cfg, t[1], t[0], t[2], t[3], t[4], t[5], t[6])] = t
            done = [f for f in futures if f.done()]
            for f in done:
                t = futures.pop(f)
                try:
                    f.result()
                except Exception as e:  # keep the queue alive, record the error
                    log(f"particles ERROR {t[6]}: {e}")
            if not done:
                time.sleep(20)
            if pending and not futures and not any(airflow_passed(t[0]) for t in pending):
                if (ROOT / "logs" / "study_v002.log").read_text().count("airflow queue finished"):
                    log(f"particle queue: {len(pending)} tasks blocked (airflow not passed): "
                        + ", ".join(sorted({t[0] for t in pending})))
                    break
                time.sleep(60)
    log("particle queue finished")


def status():
    reg = load_conditions()
    for c in all_conditions(reg):
        maps = sum((ROOT / "cases" / "particles" / f"MAP_{c['id']}_P{d:02d}" / "results.json").exists() for d in reg["optimization"]["sizes_um"])
        print(f"{c['id']:16s} {c['split']:9s} airflow {'PASSED' if airflow_passed(c['id']) else '-':7s} maps {maps}/4")
    base = len(list((ROOT / "cases" / "particles").glob("P[0-9][0-9]_*/results.json")))
    print(f"baseline direct cases with results: {base}/144")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["airflow", "particles", "status"])
    ap.add_argument("--jobs", type=int, default=2)
    a = ap.parse_args()
    cfg = load_config()
    if cfg["geometry"]["version"] != "v002":
        sys.exit("config geometry.version must be v002 (frozen) before running the v002 study")
    if a.what == "airflow":
        airflow_queue(cfg)
    elif a.what == "particles":
        particle_queue(cfg, a.jobs)
    else:
        status()


if __name__ == "__main__":
    main()
