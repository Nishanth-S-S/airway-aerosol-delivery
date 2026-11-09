#!/usr/bin/env python3
"""Recheck of the corrected particle solver (v2) on v002 data.

    python scripts/solver_recheck.py audit        # every v002 particle case: mass, window, weights, links, plane
    python scripts/solver_recheck.py runs         # seeds, parcel-count convergence, force-model sensitivity
    python scripts/solver_recheck.py report       # tables + figures -> validation/{03,06,07}/results

Audit checks per case (recorded, never silently dropped):
  A1 introduced mass within 2 % of the target (1 ng) - equal mass across sizes/strategies
  A2 every injected parcel released inside its release window [t_start, t_end] to within one cloud time step
     (OpenFOAM spreads a step's injections over that step); largest edge deviation reported
  A3 mass weighting: sum of parcel true masses = introduced mass; mean inlet weight w ~ 1 (flux weighting unbiased)
  A4 mass balance |introduced - deposited - escaped - suspended| / introduced < 1e-3 %
  A5 the case's airflowCase is the intended v002 condition, whose STL hash matches geometry/FROZEN_v002.json
  A6 target-plane point/normal/radius identical to the configured definition
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config  # noqa: E402
from lib.foam_case import target_plane  # noqa: E402

PC = ROOT / "cases" / "particles"
AF = ROOT / "cases" / "airflow"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def audit_case(d: Path, cfg: dict, frozen: dict, tp) -> dict:
    meta = json.loads((d / "case_meta.json").read_text())
    r = json.loads((d / "results.json").read_text()) if (d / "results.json").exists() else {}
    row = {"case": d.name, "airflow": meta["airflow_case"], "size_um": meta["particle_size_um"],
           "strategy": meta["release_strategy"], "has_results": bool(r), "qa": r.get("qa_status", "not run")}
    pp = d / "postProcessing" / "airwayParcels"
    if not r or not (pp / "injections.csv").exists():
        row["problems"] = "no results or no injections.csv (solver v1?)"
        return row
    inj = pd.read_csv(pp / "injections.csv")
    M_target = meta["introduced_mass_target_kg"]
    M = inj.mass.sum()
    row["A1_mass_err_percent"] = 100 * (M - M_target) / M_target
    t0, t1 = meta["release_window"]["t_start_s"], meta["release_window"]["t_end_s"]
    dt = cfg["particles"]["tracking_dt_s"]
    # OpenFOAM spreads each step's injections over that step, so the edges are resolved to one cloud step dt
    row["A2_outside_window"] = int(((inj.time < t0 - dt - 1e-9) | (inj.time > t1 + dt + 1e-9)).sum())
    row["A2_max_edge_deviation_ms"] = 1e3 * max(0.0, t0 - inj.time.min(), inj.time.max() - t1)
    row["A2_mass_released_before_start_percent"] = 100 * inj.mass[inj.time < t0].sum() / inj.mass.sum()
    row["A3_mass_vs_results_percent"] = 100 * (M - r["introduced_mass"]) / r["introduced_mass"]
    row["A3_mean_weight"] = float(inj.weight.mean()) if "weight" in inj else float("nan")
    row["A3_n_parcels"] = int(len(inj))
    row["A4_balance_err_percent"] = r["mass_balance_error_percent"]
    ap = (d / "constant" / "airwayParcelDict").read_text()
    m = re.search(r'airflowCase\s+"([^"]+)"', ap)
    row["A5_airflow_path_ok"] = bool(m and m.group(1).endswith("/cases/airflow/" + meta["airflow_case"]))
    stl = AF / meta["airflow_case"] / "constant" / "triSurface" / "airway.stl"
    am = json.loads((AF / meta["airflow_case"] / "case_meta.json").read_text())
    key = f"geometry/{am['geometry']}/airway_patches_m_v002.stl"
    row["A5_geometry_hash_ok"] = stl.exists() and frozen["files"].get(key) == sha(stl)
    pt = np.array([float(x) for x in re.search(r"targetPlanePoint\s+\(([^)]*)\)", ap).group(1).split()])
    nv = np.array([float(x) for x in re.search(r"targetPlaneNormal\s+\(([^)]*)\)", ap).group(1).split()])
    rad = float(re.search(r"targetPlaneRadius\s+([\d.eE+-]+);", ap).group(1))
    row["A6_plane_ok"] = bool(np.allclose(pt, tp[0], atol=1e-9) and np.allclose(nv, tp[1], atol=1e-6) and abs(rad - tp[2]) < 1e-9)
    probs = []
    if abs(row["A1_mass_err_percent"]) > 2: probs.append("A1")
    if row["A2_outside_window"]: probs.append("A2")
    if abs(row["A3_mass_vs_results_percent"]) > 1e-3: probs.append("A3")
    if abs(row["A4_balance_err_percent"]) > 1e-3: probs.append("A4")
    if not (row["A5_airflow_path_ok"] and row["A5_geometry_hash_ok"]): probs.append("A5")
    if not row["A6_plane_ok"]: probs.append("A6")
    row["problems"] = ",".join(probs)
    return row


def audit(cfg):
    frozen = json.loads((ROOT / "geometry" / "FROZEN_v002.json").read_text())
    tp = target_plane(cfg)
    rows = [audit_case(d, cfg, frozen, tp) for d in sorted(PC.iterdir()) if (d / "case_meta.json").exists()]
    df = pd.DataFrame(rows)
    out = ROOT / "validation" / "03_particle_mass_conservation" / "results"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "solver_audit_v002.csv", index=False)
    ok = df[df.has_results]
    summ = {"cases_with_results": int(len(ok)), "cases_with_problems": int((ok.problems.fillna("") != "").sum()),
            "max_abs_introduced_mass_err_percent": float(ok.A1_mass_err_percent.abs().max()) if len(ok) else None,
            "parcels_outside_window": int(ok.A2_outside_window.sum()) if len(ok) else None,
            "max_window_edge_deviation_ms": float(ok.A2_max_edge_deviation_ms.max()) if len(ok) else None,
            "max_mass_released_before_window_start_percent": float(ok.A2_mass_released_before_start_percent.max()) if len(ok) else None,
            "max_abs_balance_err_percent": float(ok.A4_balance_err_percent.abs().max()) if len(ok) else None,
            "mean_inlet_weight_range": [float(ok.A3_mean_weight.min()), float(ok.A3_mean_weight.max())] if len(ok) else None,
            "all_airflow_links_ok": bool(ok.A5_airflow_path_ok.all()), "all_geometry_hashes_ok": bool(ok.A5_geometry_hash_ok.all()),
            "all_planes_ok": bool(ok.A6_plane_ok.all()),
            "problem_cases": ok[ok.problems.fillna("") != ""][["case", "problems"]].to_dict("records")}
    (out / "solver_audit_v002.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps(summ, indent=1))


# ----------------------------------------------------------------- extra runs
RUNS = {
    # (condition, size, strategy) -> representative cases
    "seeds": [("T_N20_SYM", 3, "middle"), ("T_N40_LAT", 5, "late")],
    "seed_values": [2, 3, 4, 5, 6],
    "parcels": [("T_N20_SYM", 3, "middle"), ("T_N40_LAT", 5, "late")],
    "parcel_values": [5000, 10000, 40000, 80000],
}


def runs(cfg):
    import run_study_v002 as S
    from lib.conditions import all_conditions
    conds = {c["id"]: c for c in all_conditions()}
    jobs = []
    for cid, d, strat in RUNS["seeds"]:
        for s in RUNS["seed_values"]:
            jobs.append((conds[cid], d, strat, 20000, s, f"V_SEED{s}_{cid}_P{d:02d}_{strat}"))
    for cid, d, strat in RUNS["parcels"]:
        for n in RUNS["parcel_values"]:
            jobs.append((conds[cid], d, strat, n, 7, f"V_NPAR{n}_{cid}_P{d:02d}_{strat}"))
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(int(__import__("os").environ.get("AIRWAY_PARTICLE_JOBS", "2"))) as ex:
        list(ex.map(lambda j: S.particle_job(cfg, j[0], j[0]["id"], j[1], j[2], j[3], j[4], j[5]), jobs))
    # force-model sensitivity (continuous, 100k parcels, T_N20_SYM): Cunningham off for 1 um, gravity off for 5 um
    import copy
    c = conds["T_N20_SYM"]
    k1 = copy.deepcopy(cfg); k1["particles"]["cunningham_slip"] = False
    S.particle_job(k1, c, c["id"], 1, "continuous", 100000, 1, "V_FORCE_noCunningham_T_N20_SYM_P01")
    k5 = copy.deepcopy(cfg); k5["particles"]["gravity"] = [0.0, 0.0, 0.0]
    S.particle_job(k5, c, c["id"], 5, "continuous", 100000, 1, "V_FORCE_noGravity_T_N20_SYM_P05")


def report(cfg):
    def load(name):
        f = PC / name / "results.json"
        return json.loads(f.read_text()) if f.exists() else None
    strat_short = {s: v["short"] for s, v in cfg["particles"]["release_strategies"].items()}
    geo = {"T_N20_SYM": ("N20", "SYM"), "T_N40_LAT": ("N40", "LAT")}
    rows = []
    for cid, d, strat in RUNS["seeds"]:
        base = load(f"P{d:02d}_{strat_short[strat]}_{geo[cid][0]}_{geo[cid][1]}")
        vals = [(1, base)] + [(s, load(f"V_SEED{s}_{cid}_P{d:02d}_{strat}")) for s in RUNS["seed_values"]]
        for s, r in vals:
            if r:
                rows.append({"study": "seeds", "case": f"{cid} {d} um {strat}", "seed": s, "n_parcels": r["n_parcels"],
                             "delivery": r["target_delivery_percent"], "deposition": r["total_deposition_percent"]})
    for cid, d, strat in RUNS["parcels"]:
        base = load(f"P{d:02d}_{strat_short[strat]}_{geo[cid][0]}_{geo[cid][1]}")
        vals = [(20000, base)] + [(n, load(f"V_NPAR{n}_{cid}_P{d:02d}_{strat}")) for n in RUNS["parcel_values"]]
        for n, r in vals:
            if r:
                rows.append({"study": "parcels", "case": f"{cid} {d} um {strat}", "seed": 7 if n != 20000 else 1, "n_parcels": r["n_parcels"],
                             "delivery": r["target_delivery_percent"], "deposition": r["total_deposition_percent"]})
    df = pd.DataFrame(rows)
    for st, folder in (("seeds", "07_random_seeds"), ("parcels", "06_parcel_convergence")):
        out = ROOT / "validation" / folder / "results"
        out.mkdir(parents=True, exist_ok=True)
        sub = df[df.study == st]
        sub.to_csv(out / f"{st}_v002.csv", index=False)
        summ = {}
        for case, g in sub.groupby("case"):
            p = g.delivery / 100
            summ[case] = {"n_runs": int(len(g)), "delivery_mean": float(g.delivery.mean()), "delivery_sd": float(g.delivery.std(ddof=1)),
                          "binomial_se_at_20k": float(100 * math.sqrt(p.mean() * (1 - p.mean()) / (0.75 * 20000))),
                          "values": g[["seed", "n_parcels", "delivery", "deposition"]].to_dict("records")}
        (out / f"summary_{st}_v002.json").write_text(json.dumps(summ, indent=2, default=float))
        print(st, json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "values"} for k, v in summ.items()}, indent=1, default=float))
    f = {}
    for name, ref in (("V_FORCE_noCunningham_T_N20_SYM_P01", "MAP_T_N20_SYM_P01"), ("V_FORCE_noGravity_T_N20_SYM_P05", "MAP_T_N20_SYM_P05")):
        a, b = load(name), load(ref)
        if a and b:
            f[name] = {k: [b[k], a[k], a[k] - b[k]] for k in ("target_delivery_percent", "total_deposition_percent", "suspended_percent")}
    out = ROOT / "validation" / "03_particle_mass_conservation" / "results"
    (out / "force_sensitivity_v002.json").write_text(json.dumps(f, indent=2))
    print("force", json.dumps(f, indent=1))


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["audit", "runs", "report"])
    a = ap.parse_args()
    {"audit": audit, "runs": runs, "report": report}[a.what](cfg)


if __name__ == "__main__":
    main()
