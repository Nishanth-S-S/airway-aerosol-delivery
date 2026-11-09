#!/usr/bin/env python3
"""Performance audit of the Mac runs + workload / time / cost estimate for the cloud run.

    python3 cloud/tools/plan_workload.py                      # prior estimate (Mac data only)
    python3 cloud/tools/plan_workload.py --bench cloud/results/benchmark/summary.json   # after the paid benchmark

Everything is computed from logs already on disk; nothing is run.
Writes cloud/results/perf_audit.json and cloud/WORKLOAD_ESTIMATE.md.

Cost model (per airflow case), fitted on the medium-mesh verification run:
    wall seconds per time step = a + b * (pressure-solver iterations in that step)
fitted on the CLEAN final phase (nothing else running). Step and iteration counts per phase are properties of the
mesh / time-step control, not of the machine, so they transfer to any computer; only a and b change.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "cloud" / "results"
AF = ROOT / "cases" / "airflow"
PC = ROOT / "cases" / "particles"

# ---------------------------------------------------------------- log parsing


def phases(case: Path, width=0.5):
    t = (case / "logs" / "pimpleFoam.log").read_text(errors="ignore")
    agg = collections.OrderedDict()
    prev = None
    for blk in t.split("\nTime = ")[1:]:
        T = float(blk.split("\n", 1)[0])
        k = round(T / width) * width
        p = sum(int(x) for x in re.findall(r"Solving for p, .*No Iterations (\d+)", blk))
        m = re.search(r"ExecutionTime = ([\d.]+) s\s+ClockTime = ([\d.]+) s", blk)
        a = agg.setdefault(k, {"steps": 0, "p_iters": 0, "exec_s": 0.0})
        a["steps"] += 1
        a["p_iters"] += p
        if m:
            e = float(m.group(1))
            if prev is not None:
                a["exec_s"] += e - prev
            prev = e
    return agg


def cells_of(case: Path):
    meta = json.loads((case / "case_meta.json").read_text())
    rep = ROOT / "cases" / "mesh" / f"{meta['geometry']}_{meta['mesh_level']}" / "mesh_report.json"
    return json.loads(rep.read_text())["cells"]


def walltime(case: Path, log="airwayParcelFoam"):
    L = case / "logs" / f"{log}.log"
    if not L.exists():
        return None
    m = re.findall(r"ExecutionTime = ([\d.]+) s", L.read_text(errors="ignore"))
    return float(m[-1]) if m else None


def du_mb(p: Path):
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 2**20


# ---------------------------------------------------------------- audit


def audit():
    med = AF / "V_MESH_medium_T_N40_SYM"
    ph = phases(med)
    # clean phase: last phase (t > 2.75 s) ran with no particle jobs and no throttling events
    last = list(ph.values())[-1]
    s_per_step_clean = last["exec_s"] / last["steps"]
    iters_last = last["p_iters"] / last["steps"]
    # split a + b*iters using the ratio fitted on two early phases (same machine state, different iteration counts)
    p05, p10 = ph[0.5], ph[1.0]
    b = (p05["exec_s"] / p05["steps"] - p10["exec_s"] / p10["steps"]) / (p05["p_iters"] / p05["steps"] - p10["p_iters"] / p10["steps"])
    a = p10["exec_s"] / p10["steps"] - b * p10["p_iters"] / p10["steps"]
    ratio = a / b                                      # machine-independent split (iteration-equivalents per step)
    b_clean = s_per_step_clean / (ratio + iters_last)
    clean_total = sum(v["steps"] * (ratio + v["p_iters"] / v["steps"]) * b_clean for v in ph.values())
    actual_total = sum(v["exec_s"] for v in ph.values())
    cells = cells_of(med)
    archive = {}
    for d in sorted(glob.glob(str(ROOT / "archive/v001/cases/airflow/*"))) + [str(AF / "T_N40_SYM")]:
        L = Path(d) / "logs" / "pimpleFoam.log"
        if not L.exists():
            continue
        t = L.read_text(errors="ignore")
        ex = re.findall(r"ExecutionTime = ([\d.]+) s", t)
        archive[Path(d).name] = {"steps": t.count("\nTime = "), "exec_s": float(ex[-1]) if ex else None}
    fine = AF / "V_MESH_fine_T_N40_SYM"
    fine_ph = phases(fine) if (fine / "logs" / "pimpleFoam.log").exists() else {}
    rec = re.findall(r"ExecutionTime = ([\d.]+) s", (med / "logs" / "reconstructPar.log").read_text(errors="ignore"))
    rec_s = (med / "logs" / "reconstructPar.log").stat().st_mtime - (med / "logs" / "pimpleFoam.log").stat().st_mtime
    res = {
        "machine": "MacBook Pro, Intel i9-9880H (8 cores / 16 threads), Docker Desktop VM 16 vCPU / 8 GB, bind-mounted project",
        "solver_parallel": "pimpleFoam runs in parallel: mpirun -np 8 (scotch decomposition), one Docker container per command; "
                           "airwayParcelFoam (particles) runs serially (1 process)",
        "medium_case": {"cells": cells, "steps": sum(v["steps"] for v in ph.values()),
                        "phases": {f"{k:.1f}": {"steps": v["steps"], "p_iters_per_step": round(v["p_iters"] / v["steps"], 1),
                                                "exec_s": round(v["exec_s"]), "s_per_step": round(v["exec_s"] / v["steps"], 3)}
                                   for k, v in ph.items()},
                        "actual_solver_s": round(actual_total), "clean_model_solver_s": round(clean_total),
                        "slowdown_from_machine_state": round(actual_total / clean_total, 2),
                        "model": {"iteration_equivalents_per_step_overhead": round(ratio, 2), "clean_s_per_iteration": b_clean,
                                  "clean_us_per_cell_iteration_8ranks": 1e6 * b_clean / cells},
                        "reconstructPar_wall_s": round(rec_s), "size_MB": round(du_mb(med)),
                        "write_times": 150, "write_format": "binary"},
        "fine_case_so_far": {k: v for k, v in (("phases", {f"{k:.1f}": v for k, v in fine_ph.items()}),)} if fine_ph else None,
        "mac_runtime_spread_identical_work": archive,
        "particle_runs_s": {"map_100k_medium": walltime(PC / "MAP_V_MESH_medium_T_N40_SYM_P03"),
                            "map_100k_coarse": walltime(PC / "MAP_T_N40_SYM_P03"),
                            "direct_20k_coarse": walltime(PC / "P03_MID_N40_SYM")},
        "sizes_MB": {"particle_map": round(du_mb(PC / "MAP_V_MESH_medium_T_N40_SYM_P03")),
                     "particle_direct": round(du_mb(PC / "P03_MID_N40_SYM"))},
    }
    return res


# ---------------------------------------------------------------- workload

GEO = {"healthy": 0.85, "n20": 0.88, "n30": 0.94, "n40": 1.0, "asym40": 1.0}   # step-count ratios measured on v001 coarse


def flow_factor(q, share_flowing):
    """Cost of the flowing (Courant-limited) phase scales with peak velocity ~ Q; the low-flow phase does not."""
    return share_flowing * q / 2.0 + (1 - share_flowing)


def measured_fine_factor(aud):
    """Fine-case solver time so far (Mac, running alone) / clean medium-case model time up to the same simulated time."""
    fine = AF / "V_MESH_fine_T_N40_SYM" / "logs" / "pimpleFoam.log"
    if not fine.exists():
        return None
    t = fine.read_text(errors="ignore")
    ex = re.findall(r"ExecutionTime = ([\d.]+) s", t)
    tm = re.findall(r"\nTime = ([\d.eE+-]+)", t)
    if not ex or not tm:
        return None
    T, E = float(tm[-1]), float(ex[-1])
    m = aud["medium_case"]
    over, b = m["model"]["iteration_equivalents_per_step_overhead"], m["model"]["clean_s_per_iteration"]
    cum = 0.0
    for k, v in m["phases"].items():                 # bins of width 0.5 centred on k (first bin 0-0.25)
        lo, hi = max(float(k) - 0.25, 0.0), float(k) + 0.25
        cost = v["steps"] * (over + v["p_iters_per_step"]) * b
        if T >= hi:
            cum += cost
        elif T > lo:
            cum += cost * (T - lo) / (hi - lo)
    return {"fine_sim_time_s": T, "fine_exec_s": E, "medium_clean_to_same_time_s": cum, "ratio": E / cum}


def workload(aud, bench=None, fine_factor=(4.0, 5.0, 6.5), speedup=(1.3, 2.0, 2.8), price=0.9273, mesh="medium"):
    mf = measured_fine_factor(aud)
    if mf:
        r = mf["ratio"]
        fine_factor = (0.8 * r, r, 1.25 * r)
    import yaml
    reg = yaml.safe_load((ROOT / "config" / "conditions.yaml").read_text())
    m = aud["medium_case"]
    ph = m["phases"]
    model = m["model"]
    cost = {k: v["steps"] * (model["iteration_equivalents_per_step_overhead"] + v["p_iters_per_step"]) for k, v in ph.items()}
    share_flowing = sum(c for k, c in cost.items() if float(k) <= 1.5) / sum(cost.values())
    cases = []
    for c in reg["training"] + reg["test"]:
        g = c["geometry"]
        cases.append((c["id"], GEO[g] * flow_factor(c["flow_lpm"], share_flowing)))
    cases.append(("V_CO1_T_N40_SYM", share_flowing * 3 * 0.8 + (1 - share_flowing)))   # Courant 1: 3x steps, 1 outer
    cases += [("V_OBC30_T_N40_SYM", 1.0), ("V_OBC50_T_N40_SYM", 1.0)]
    mac_core_h_per_eq = m["clean_model_solver_s"] * 8 / 3600
    eq_total = sum(x for _, x in cases)
    out = {"share_of_cost_in_flowing_phase": share_flowing, "cases": cases, "medium_equivalents": eq_total,
           "mac_core_h_per_medium_eq_clean": mac_core_h_per_eq, "fine_factor_measured": mf, "fine_factor_used": fine_factor}
    rows = []
    for meshname, ff in (("medium", (1, 1, 1)), ("fine", fine_factor)):
        for lab, i in (("optimistic", 0), ("central", 1), ("pessimistic", 2)):
            s = speedup[2 - i] if bench is None else bench["per_core_speedup_vs_mac"]
            f = ff[i] if meshname == "fine" else 1
            core_h = eq_total * f * mac_core_h_per_eq / s
            co1 = dict(cases)["V_CO1_T_N40_SYM"] * f * mac_core_h_per_eq / s
            ranks_co1 = 8 if meshname == "medium" else 24
            eff = 0.85
            crit_h = co1 / (ranks_co1 * eff)
            # particles: maps + baseline + recheck + evaluation, measured Mac serial times, larger mesh ~ cells ratio^0.5
            mp = aud["particle_runs_s"]["map_100k_medium"] or 306
            dr = (aud["particle_runs_s"]["direct_20k_coarse"] or 176) * 1.2
            pf = 1.0 if meshname == "medium" else 1.45
            part_core_h = (77 * mp + (144 + 20 + 153) * dr) * pf / 3600 / s
            wall_h = max((core_h + part_core_h) / (96 * 0.9), crit_h) + 1.0     # + 1 h for setup, meshing, gates, analysis
            gb = 20 * (m["size_MB"] / 1024) * (1 if meshname == "medium" else 2.1) + 25
            rows.append({"mesh": meshname, "scenario": lab, "airflow_core_h": core_h, "particle_core_h": part_core_h,
                         "critical_path_case_h": crit_h, "wall_h_one_instance": wall_h,
                         "compute_usd": wall_h * price, "storage_GB": gb})
    out["rows"] = rows
    return out


def write_md(aud, wl, path):
    m = aud["medium_case"]
    L = ["# Workload estimate for the cloud run (generated by cloud/tools/plan_workload.py)", "",
         "## 1. Performance audit of the Mac runs (from existing logs)", "",
         f"* {aud['machine']}.", f"* {aud['solver_parallel']}.",
         f"* Medium verification case: {m['cells']:,} cells, {m['steps']:,} time steps, solver CPU time "
         f"{m['actual_solver_s'] / 3600:.1f} h. A clean machine would have needed about {m['clean_model_solver_s'] / 3600:.1f} h "
         f"(model fitted on the final phase, when nothing else was running): the run was **{m['slowdown_from_machine_state']}x slower "
         "than necessary** because particle jobs shared the 8 physical cores and the laptop throttled.",
         "* The same 3-second airflow problem on the coarse mesh took between "
         f"{min(v['exec_s'] for v in aud['mac_runtime_spread_identical_work'].values() if v['exec_s'] and v['steps'] > 5000):.0f} s and "
         f"{max(v['exec_s'] for v in aud['mac_runtime_spread_identical_work'].values() if v['exec_s']):.0f} s for nearly identical work "
         "(v001 cases): machine state, not physics, dominates Mac run time.",
         f"* Pressure solver: {min(v['p_iters_per_step'] for v in m['phases'].values())}-"
         f"{max(v['p_iters_per_step'] for v in m['phases'].values())} GAMG iterations per step; the low-flow phases need ~3x more "
         "iterations per step. This is numerics (fixed tolerances), identical on any machine, and is NOT relaxed.",
         f"* Reconstruction: ~{m['reconstructPar_wall_s'] / 60:.0f} min per medium case (<2 % of a clean run). "
         f"Disk: {m['size_MB'] / 1024:.1f} GB per medium case (150 binary write times needed by the particle solver); "
         "about 0.05 MB/s average write rate - not a bottleneck.",
         "* Airflow reuse is already correct: the 144 baseline particle cases reuse the 9 training airflow solutions; "
         "the medium verification run doubles as the production T_N40_SYM case if the medium mesh is adopted.",
         "* Particle runs are serial (1 core each): map (100k parcels) "
         f"{aud['particle_runs_s']['map_100k_medium']:.0f} s, direct run (20k) {aud['particle_runs_s']['direct_20k_coarse']:.0f} s. "
         "Evaluation and recheck stages ran only 2 jobs at a time (now configurable, default unchanged).", "",
         "## 2. Remaining workload", "",
         f"Airflow cases still needed on the production mesh: {len(wl['cases'])} "
         f"(= {wl['medium_equivalents']:.1f} medium-N40-equivalents; flowing phase = {100 * wl['share_of_cost_in_flowing_phase']:.0f} % of cost).",
         "Particle runs: 77 response maps, 144 baseline, ~20 recheck, <=153 evaluation runs (all reuse airflow).", "",
         "| Mesh | Scenario | Airflow core-h | Particle core-h | Longest single case (h) | Wall time, one c7a.24xlarge (h) | Compute $ (Spot) | Storage GB |",
         "|---|---|---|---|---|---|---|---|"]
    for r in wl["rows"]:
        L.append(f"| {r['mesh']} | {r['scenario']} | {r['airflow_core_h']:.0f} | {r['particle_core_h']:.0f} | "
                 f"{r['critical_path_case_h']:.1f} | {r['wall_h_one_instance']:.1f} | {r['compute_usd']:.0f} | {r['storage_GB']:.0f} |")
    mf = wl.get("fine_factor_measured")
    ff = wl["fine_factor_used"]
    L += ["", "Pre-benchmark assumptions (replaced by measured values after the benchmark): c7a per-core speed 1.3-2.8x the "
          f"Mac (central 2.0x); fine mesh costs {ff[0]:.1f}-{ff[2]:.1f}x a medium case (central {ff[1]:.1f}x"
          + (f", measured from the Mac fine run so far: {mf['fine_exec_s'] / 3600:.1f} h to t = {mf['fine_sim_time_s']:.3f} s vs "
             f"{mf['medium_clean_to_same_time_s'] / 3600:.2f} h for a clean medium case; early-phase ratio, may change later in the cycle"
             if mf else "") + "); 90 % core utilisation; 85 % MPI efficiency for the longest case.", ""]
    path.write_text("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench")
    ap.add_argument("--price", type=float, default=0.9273)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    aud = audit()
    (OUT / "perf_audit.json").write_text(json.dumps(aud, indent=2, default=float))
    bench = json.loads(Path(a.bench).read_text()) if a.bench else None
    wl = workload(aud, bench, price=a.price)
    (OUT / "workload.json").write_text(json.dumps(wl, indent=2, default=float))
    write_md(aud, wl, ROOT / "cloud" / "WORKLOAD_ESTIMATE.md")
    print((ROOT / "cloud" / "WORKLOAD_ESTIMATE.md").read_text())


if __name__ == "__main__":
    main()
