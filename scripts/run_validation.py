#!/usr/bin/env python3
"""Phase 15: verification & validation framework.  NOTHING here is "validated" until run
and reviewed.  Each study writes validation/<study>/results/summary.json + a PNG.

    python scripts/run_validation.py --list
    python scripts/run_validation.py tube                       # 01 straight-tube analytical verification
    python scripts/run_validation.py conservation               # 02 airflow conservation (all airflow cases)
    python scripts/run_validation.py mass                       # 03 particle mass conservation (all particle cases)
    python scripts/run_validation.py tracer                     # 03b numerical-deposition floor (0.1 um tracers)
    python scripts/run_validation.py mesh   --levels coarse medium fine [--geometry n40 --waveform symmetric]
    python scripts/run_validation.py timestep --co 0.5 1 3 5 [--particle-dt 0.002 0.001 0.0005]
    python scripts/run_validation.py parcels --parcels 2500 5000 10000 20000 40000
    python scripts/run_validation.py seeds  --seeds 1 2 3 4 5
    python scripts/run_validation.py benchmark --data validation/08_experimental_benchmark/data/<file>.csv
    python scripts/run_validation.py outletbc --splits 0.4 0.5 0.6

Variant cases are named val_* so they never enter results/results.csv.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, die, load_config, rel  # noqa: E402
from lib.foam_case import (airflow_case_dir, build_airflow_case, build_particle_case, mesh_case_dir,  # noqa: E402
                           target_plane)
from lib.stl_io import write_ascii_regions  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

VAL = ROOT / "validation"
STUDIES = {
    "tube": "01_straight_tube_analytical",
    "conservation": "02_airflow_conservation",
    "mass": "03_particle_mass_conservation",
    "tracer": "03_particle_mass_conservation",
    "mesh": "04_mesh_independence",
    "timestep": "05_timestep_independence",
    "parcels": "06_parcel_convergence",
    "seeds": "07_random_seeds",
    "benchmark": "08_experimental_benchmark",
    "outletbc": "09_outlet_bc_sensitivity",
}


def out_dir(study):
    d = VAL / STUDIES[study] / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(study, name, obj):
    f = out_dir(study) / name
    f.write_text(json.dumps(obj, indent=2, default=float))
    print(f"[ok] {rel(f)}")


# ---------------------------------------------------------------- shared runners
def run_airflow_variant(cfg, case_id, geometry, flow, level=None, n_procs=None, edit=None):
    import run_airflow_cases as R
    build_airflow_case(cfg, case_id, geometry, flow, level)
    if edit:
        edit(airflow_case_dir(case_id))
    ok = R.run_airflow(cfg, case_id, geometry, flow, n_procs or cfg["openfoam"]["n_procs"], level, plots=False)
    qa = json.loads((airflow_case_dir(case_id) / "qa_report.json").read_text()) if ok or \
        (airflow_case_dir(case_id) / "qa_report.json").exists() else {"status": "FAILED"}
    return ok, qa


def run_particle_variant(cfg, case_id, airflow_id, geometry, wave, d_um=3, strategy="continuous",
                         n_parcels=None, seed=None, edit=None):
    import run_particle_cases as RP
    build_particle_case(cfg, d_um, strategy, geometry, wave, n_parcels=n_parcels, seed=seed,
                        case_id=case_id, airflow_id=airflow_id)
    if edit:
        edit(ROOT / "cases" / "particles" / case_id)
    row = SimpleNamespace(case_id=case_id, airflow_case=airflow_id, geometry=geometry, waveform=wave,
                          particle_size_um=d_um, release_strategy=strategy)
    RP.ensure_solver(cfg)
    RP.run_one(cfg, row, regenerate=False)
    f = ROOT / "cases" / "particles" / case_id / "results.json"
    return json.loads(f.read_text()) if f.exists() else None


def set_param(case_dir: Path, file: str, key: str, value):
    p = case_dir / file
    s = p.read_text()
    s2, n = re.subn(rf"^({re.escape(key)}\s+)[^;]*;", rf"\g<1>{value};", s, flags=re.M)
    if n == 0:
        raise KeyError(f"{key} not found in {p}")
    p.write_text(s2)


# ---------------------------------------------------------------- 01 tube
def study_tube(a, cfg):
    """Poiseuille flow + Pich (1972) gravitational deposition in a horizontal straight tube."""
    D, L = 6.0, 60.0                       # mm
    Q_lpm = a.tube_flow
    geom = "validation_tube"
    gdir = ROOT / "geometry" / geom
    gdir.mkdir(parents=True, exist_ok=True)
    n_th, n_z = 96, 120
    th = np.linspace(0, 2 * np.pi, n_th + 1)
    z = np.linspace(0, L, n_z + 1)
    R = D / 2
    ring = lambda zz: np.stack([R * np.cos(th), R * np.sin(th), np.full_like(th, zz)], 1)  # noqa: E731
    walls = []
    for k in range(n_z):
        a0, a1 = ring(z[k]), ring(z[k + 1])
        for j in range(n_th):
            walls += [[a0[j], a0[j + 1], a1[j + 1]], [a0[j], a1[j + 1], a1[j]]]
    c0, c1 = np.array([0, 0, 0.0]), np.array([0, 0, L])
    inlet = [[c0, ring(0)[j + 1], ring(0)[j]] for j in range(n_th)]
    out = [[c1, ring(L)[j], ring(L)[j + 1]] for j in range(n_th)]
    out_t = [t for t in out if np.mean([v[0] for v in t]) >= 0]
    out_c = [t for t in out if np.mean([v[0] for v in t]) < 0]
    write_ascii_regions(gdir / "airway_patches_m.stl",
                        {"inlet": np.array(inlet), "targetOutlet": np.array(out_t),
                         "comparisonOutlet": np.array(out_c), "walls": np.array(walls)}, scale=1e-3)
    c = copy.deepcopy(cfg)
    c["geometry"]["parent_diameter_mm"] = D
    c["breathing"]["constant_flow_case"] = {"flow_L_per_min": Q_lpm, "end_time_s": a.tube_time}
    c["mesh"]["levels"][a.level]["boundary_layers"] = 0
    import mesh_geometry
    if not mesh_geometry.mesh_ready(geom, a.level):
        mesh_geometry.mesh_one(c, geom, a.level)
    case_id = f"val_tube_{a.level}"

    def no_target_plane(d):   # the Y-airway target-entry plane does not intersect the straight tube
        f = d / "system" / "functions"
        t = f.read_text()
        i, j = t.index("// ---- flow through the target-entry plane"), t.index("// ---- symmetry-plane")
        f.write_text(t[:i] + t[j:])
    ok, qa = run_airflow_variant(c, case_id, geom, "constant", a.level, edit=no_target_plane)
    from lib.postproc import airflow_timeseries
    from lib.vtk_io import read_vtk_polydata
    ts = airflow_timeseries(airflow_case_dir(case_id))
    steady = ts[ts.time > 0.6 * ts.time.max()]
    mu, nu = c["air"]["dynamic_viscosity"], c["air"]["kinematic_viscosity"]
    Q = steady.Q_in.mean()
    dp_exact = 128 * mu * (L * 1e-3) * Q / (math.pi * (D * 1e-3) ** 4)
    dp_cfd = float(steady.dp_Pa.mean())
    times = sorted((airflow_case_dir(case_id) / "postProcessing" / "midPlane").glob("*/yMid.vtk"),
                   key=lambda p: float(p.parent.name))
    v = read_vtk_polydata(times[-1])
    pts = v["points"]
    cen = np.array([pts[p].mean(0) for p in v["polys"]]) * 1e3
    uz = v["cell_data"]["U"][:, 2]
    sel = (cen[:, 2] > 0.4 * L) & (cen[:, 2] < 0.6 * L)
    r_ = np.abs(cen[sel, 0])
    U_mean = Q / (math.pi * (D * 1e-3) ** 2 / 4)
    res = {"Q_L_min": Q * 6e4, "Re": U_mean * D * 1e-3 / nu, "dp_exact_Pa": dp_exact, "dp_cfd_Pa": dp_cfd,
           "dp_error_percent": 100 * (dp_cfd - dp_exact) / dp_exact,
           "u_centre_exact": 2 * U_mean, "u_centre_cfd": float(uz[sel][r_ < 0.5].mean()),
           "airflow_qa": qa.get("status")}
    res["u_centre_error_percent"] = 100 * (res["u_centre_cfd"] - res["u_centre_exact"]) / res["u_centre_exact"]
    rr = np.linspace(0, R, 50)
    fig, axs = plt.subplots(1, 2, figsize=(11, 4))
    axs[0].plot(r_, uz[sel], ".", ms=3, label="CFD (cells, mid-length)")
    axs[0].plot(rr, 2 * U_mean * (1 - (rr / R) ** 2), "k-", label="Poiseuille")
    axs[0].set_xlabel("r (mm)"); axs[0].set_ylabel("u_z (m/s)"); axs[0].legend(); axs[0].grid(alpha=.3)
    axs[0].set_title(f"Velocity profile, Re={res['Re']:.0f}")
    axs[1].bar(["analytical", "CFD"], [dp_exact, dp_cfd], color=["#999", "#2a9d8f"])
    axs[1].set_ylabel("pressure drop (Pa)")
    axs[1].set_title(f"Δp error {res['dp_error_percent']:+.2f} %")

    if not a.no_particles:   # Pich (1972) sedimentation in a horizontal tube, Poiseuille flow
        d_um = a.tube_particle_um
        t_inj0, t_inj1 = 0.3 * a.tube_time, 0.45 * a.tube_time
        def edit(pd_):
            set_param(pd_, "constant/particleParameters", "SOI", t_inj0)
            set_param(pd_, "constant/particleParameters", "duration", t_inj1 - t_inj0)
            v_aero = c["particles"]["introduced_mass_kg"] / c["particles"]["density"]
            set_param(pd_, "constant/particleParameters", "concentration", v_aero / (Q * (t_inj1 - t_inj0)))
            set_param(pd_, "constant/particleParameters", "endTime", a.tube_time)
            set_param(pd_, "constant/particleParameters", "gravity", "(-9.81 0 0)")
            set_param(pd_, "constant/airwayParcelDict", "inletRadius", D / 2e3)
        pr = run_particle_variant(c, f"val_tube_pich_{d_um:g}um", case_id, geom, "symmetric", d_um=d_um,
                                  n_parcels=a.parcels or 5000, edit=edit)
        if pr:
            meta = json.loads((ROOT / "cases" / "particles" / f"val_tube_pich_{d_um:g}um" / "case_meta.json").read_text())
            tau = c["particles"]["density"] * (d_um * 1e-6) ** 2 * meta["cunningham_Cc"] / (18 * mu)
            vs = tau * 9.81
            eps = 0.75 * (L * 1e-3) * vs / (D * 1e-3 * U_mean)
            e3 = eps ** (1 / 3)
            pich = (2 / math.pi) * (2 * eps * math.sqrt(1 - e3 ** 2) - e3 * math.sqrt(1 - e3 ** 2) + math.asin(e3)) \
                if e3 < 1 else 1.0
            res.update({"pich_particle_um": d_um, "pich_epsilon": eps, "pich_deposition_percent": 100 * pich,
                        "cfd_deposition_percent": pr["total_deposition_percent"],
                        "cfd_mass_balance_error_percent": pr["mass_balance_error_percent"]})
    fig.tight_layout(); fig.savefig(out_dir("tube") / "tube_verification.png", dpi=130); plt.close(fig)
    save("tube", "summary.json", res)


# ---------------------------------------------------------------- 02 / 03 scans
def study_conservation(a, cfg):
    rows = []
    for f in sorted((ROOT / "cases" / "airflow").glob("*/qa_report.json")):
        q = json.loads(f.read_text())
        rows.append({"case": f.parent.name, "status": q.get("status"),
                     "imbalance_percent": q.get("mean_imbalance_percent"),
                     "inspired_volume_mL": q.get("inspired_volume_mL"),
                     "target_split_percent": q.get("target_branch_ventilation_percent")})
    df = pd.DataFrame(rows)
    df.to_csv(out_dir("conservation") / "airflow_conservation.csv", index=False)
    print(df.to_string(index=False))
    save("conservation", "summary.json", {"n_cases": len(df), "all_passed": bool((df.status == "PASSED").all()),
                                          "max_imbalance_percent": float(df.imbalance_percent.max()) if len(df) else None,
                                          "criterion_percent": cfg["qa"]["airflow_mass_imbalance_percent"]})


def study_mass(a, cfg):
    rows = [json.loads(f.read_text()) for f in sorted((ROOT / "cases" / "particles").glob("*/results.json"))]
    df = pd.DataFrame(rows)
    if df.empty:
        die("no finished particle cases yet")
    df[["case_id", "introduced_mass", "mass_balance_error_percent", "qa_status"]].to_csv(
        out_dir("mass") / "mass_balance.csv", index=False)
    print(df[["case_id", "mass_balance_error_percent", "qa_status"]].to_string(index=False))
    save("mass", "summary.json", {"n_cases": len(df), "max_abs_error_percent": float(df.mass_balance_error_percent.abs().max()),
                                  "criterion_percent": cfg["qa"]["particle_mass_balance_percent"]})


def study_tracer(a, cfg):
    """Near-zero-inertia tracers should not deposit; whatever deposits is numerical (interpolation/mesh)."""
    g, w = a.geometry, a.waveform
    r = run_particle_variant(cfg, f"val_tracer_{g}_{w}", f"{g}_{w}", g, w, d_um=0.1, n_parcels=a.parcels)
    save("tracer", "tracer_summary.json", {"airflow": f"{g}_{w}", "diameter_um": 0.1, **(r or {})})


# ---------------------------------------------------------------- 04 mesh
def study_mesh(a, cfg):
    rows = []
    for lvl in a.levels:
        c = copy.deepcopy(cfg); c["mesh"]["level"] = lvl
        aid = f"val_mesh_{a.geometry}_{a.waveform}_{lvl}"
        ok, qa = run_airflow_variant(c, aid, a.geometry, a.waveform, lvl)
        rep = json.loads((mesh_case_dir(a.geometry, lvl) / "mesh_report.json").read_text())
        row = {"level": lvl, "cells": rep["cells"], "h_mm": 1e3 * (rep["total_volume"] / rep["cells"]) ** (1 / 3),
               "airflow_qa": qa.get("status"), "peak_dp_Pa": qa.get("peak_pressure_drop_Pa"),
               "target_split_percent": qa.get("target_branch_ventilation_percent")}
        if ok and not a.no_particles:
            pr = run_particle_variant(c, f"val_mesh_P03_{a.geometry}_{a.waveform}_{lvl}", aid, a.geometry, a.waveform,
                                      n_parcels=a.parcels)
            if pr:
                row.update({"target_delivery_percent": pr["target_delivery_percent"],
                            "total_deposition_percent": pr["total_deposition_percent"]})
        rows.append(row)
    df = pd.DataFrame(rows).sort_values("h_mm")
    df.to_csv(out_dir("mesh") / "mesh_study.csv", index=False)
    res = {"table": df.to_dict("records")}
    if len(df) >= 3:   # Roache GCI with the three finest levels
        f1, f2, f3 = df.iloc[0], df.iloc[1], df.iloc[2]
        for q in ("peak_dp_Pa", "target_split_percent", "target_delivery_percent"):
            if q in df and df[q].notna().iloc[:3].all():
                r21, r32 = f2.h_mm / f1.h_mm, f3.h_mm / f2.h_mm
                e21, e32 = f2[q] - f1[q], f3[q] - f2[q]
                try:
                    p = abs(math.log(abs(e32 / e21))) / math.log(r21) if e21 and e32 else float("nan")
                    gci = 1.25 * abs(e21 / f1[q]) / (r21 ** p - 1) * 100
                except (ValueError, ZeroDivisionError):
                    p, gci = float("nan"), float("nan")
                res[f"GCI_fine_{q}_percent"] = gci
                res[f"observed_order_{q}"] = p
    fig, axs = plt.subplots(1, 3, figsize=(13, 3.8))
    for ax, q in zip(axs, ("peak_dp_Pa", "target_split_percent", "target_delivery_percent")):
        if q in df:
            ax.plot(df.cells, df[q], "o-"); ax.set_xscale("log"); ax.set_xlabel("cells"); ax.set_title(q); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(out_dir("mesh") / "mesh_study.png", dpi=130); plt.close(fig)
    save("mesh", "summary.json", res)


# ---------------------------------------------------------------- 05 time step
def study_timestep(a, cfg):
    rows = []
    for co in a.co:
        c = copy.deepcopy(cfg); c["airflow"]["max_courant"] = co
        c["airflow"]["n_outer_correctors"] = 1 if co <= 1 else max(2, c["airflow"]["n_outer_correctors"])
        aid = f"val_dt_co{co:g}_{a.geometry}_{a.waveform}"
        ok, qa = run_airflow_variant(c, aid, a.geometry, a.waveform)
        row = {"kind": "airflow", "max_courant": co, "airflow_qa": qa.get("status"), "peak_dp_Pa": qa.get("peak_pressure_drop_Pa"),
               "target_split_percent": qa.get("target_branch_ventilation_percent"), "wallclock_min": qa.get("wallclock_min")}
        if ok and not a.no_particles:
            pr = run_particle_variant(c, f"val_dt_P03_co{co:g}_{a.geometry}_{a.waveform}", aid, a.geometry, a.waveform,
                                      n_parcels=a.parcels)
            row["target_delivery_percent"] = pr and pr["target_delivery_percent"]
        rows.append(row)
    for pdt in a.particle_dt or []:
        c = copy.deepcopy(cfg); c["particles"]["tracking_dt_s"] = pdt
        pr = run_particle_variant(c, f"val_pdt_{pdt:g}_{a.geometry}_{a.waveform}", f"{a.geometry}_{a.waveform}",
                                  a.geometry, a.waveform, n_parcels=a.parcels)
        rows.append({"kind": "particle_dt", "particle_dt_s": pdt,
                     "target_delivery_percent": pr and pr["target_delivery_percent"],
                     "total_deposition_percent": pr and pr["total_deposition_percent"]})
    df = pd.DataFrame(rows); df.to_csv(out_dir("timestep") / "timestep_study.csv", index=False)
    print(df.to_string(index=False))
    save("timestep", "summary.json", {"table": df.to_dict("records")})


# ---------------------------------------------------------------- 06 / 07 parcels & seeds
def study_parcels(a, cfg):
    rows = []
    for n in a.parcels_list:
        pr = run_particle_variant(cfg, f"val_parcels_{n}_{a.geometry}_{a.waveform}", f"{a.geometry}_{a.waveform}",
                                  a.geometry, a.waveform, n_parcels=n)
        rows.append({"n_parcels": n, **{k: pr[k] for k in ("target_delivery_percent", "total_deposition_percent",
                                                           "mass_balance_error_percent")}} if pr else {"n_parcels": n})
    df = pd.DataFrame(rows); df.to_csv(out_dir("parcels") / "parcel_convergence.csv", index=False)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(df.n_parcels, df.target_delivery_percent, "o-"); ax.set_xscale("log")
    ax.set_xlabel("parcels per case"); ax.set_ylabel("target delivery (%)"); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(out_dir("parcels") / "parcel_convergence.png", dpi=130); plt.close(fig)
    save("parcels", "summary.json", {"table": df.to_dict("records")})


def study_seeds(a, cfg):
    rows = []
    for s in a.seeds:
        pr = run_particle_variant(cfg, f"val_seed_{s}_{a.geometry}_{a.waveform}", f"{a.geometry}_{a.waveform}",
                                  a.geometry, a.waveform, n_parcels=a.parcels, seed=s)
        if pr:
            rows.append({"seed": s, "target_delivery_percent": pr["target_delivery_percent"],
                         "total_deposition_percent": pr["total_deposition_percent"]})
    df = pd.DataFrame(rows); df.to_csv(out_dir("seeds") / "seeds.csv", index=False)
    m, sd = df.target_delivery_percent.mean(), df.target_delivery_percent.std(ddof=1)
    save("seeds", "summary.json", {"n": len(df), "mean_target_delivery": m, "sd": sd,
                                   "ci95_halfwidth": 1.96 * sd / math.sqrt(len(df)) if len(df) > 1 else None,
                                   "table": df.to_dict("records")})


# ---------------------------------------------------------------- 08 benchmark
def study_benchmark(a, cfg):
    """Compare CFD deposition with an experimental data set YOU supply (no data is bundled)."""
    if not a.data:
        die("supply --data <csv> with columns: label, stokes_number or particle_size_um, measured_deposition_percent, "
            "[measured_uncertainty_percent], cfd_case_id   (see validation/08_experimental_benchmark/README.md)")
    exp = pd.read_csv(a.data)
    res = pd.read_csv(ROOT / "results" / "results.csv")
    m = exp.merge(res, left_on="cfd_case_id", right_on="case_id", how="left")
    m["cfd_deposition_percent"] = m["total_deposition_percent"]
    m["difference_points"] = m.cfd_deposition_percent - m.measured_deposition_percent
    m.to_csv(out_dir("benchmark") / "comparison.csv", index=False)
    print(m[["label", "measured_deposition_percent", "cfd_deposition_percent", "difference_points"]].to_string(index=False))
    save("benchmark", "summary.json", {"n_points": len(m), "mean_abs_difference_points": float(m.difference_points.abs().mean())})


# ---------------------------------------------------------------- 09 outlet BC
def study_outletbc(a, cfg):
    rows = []
    for frac in a.splits:
        aid = f"val_obc_split{int(round(frac * 100))}_{a.geometry}_{a.waveform}"

        def edit(d, frac=frac):
            # target outlet: prescribed outflow = frac * Q_in(t); comparison outlet keeps p = 0
            tbl = (d / "constant" / "inletFlowRate").read_text()
            rows_ = re.findall(r"\(([-\d.eE+]+)\s+([-\d.eE+]+)\)", tbl)
            (d / "constant" / "targetOutletFlowRate").write_text(
                "(\n" + "\n".join(f"    ({t} {float(q) * frac:.10g})" for t, q in rows_) + "\n)\n")
            u = (d / "0.orig" / "U").read_text().replace(
                "targetOutlet     { type pressureInletOutletVelocity; value uniform (0 0 0); }",
                "targetOutlet     { type flowRateOutletVelocity; volumetricFlowRate { type tableFile; "
                "file \"<constant>/targetOutletFlowRate\"; outOfBounds clamp; } value uniform (0 0 0); }")
            (d / "0.orig" / "U").write_text(u)
            p = (d / "0.orig" / "p").read_text().replace(
                "targetOutlet     { type totalPressure; p0 uniform 0; value uniform 0; }",
                "targetOutlet     { type zeroGradient; }")
            (d / "0.orig" / "p").write_text(p)
        ok, qa = run_airflow_variant(cfg, aid, a.geometry, a.waveform, edit=edit)
        row = {"target_split_imposed": frac, "airflow_qa": qa.get("status"),
               "target_split_percent": qa.get("target_branch_ventilation_percent"), "peak_dp_Pa": qa.get("peak_pressure_drop_Pa")}
        if ok and not a.no_particles:
            pr = run_particle_variant(cfg, f"val_obc_P03_split{int(round(frac * 100))}_{a.geometry}_{a.waveform}", aid,
                                      a.geometry, a.waveform, n_parcels=a.parcels)
            row["target_delivery_percent"] = pr and pr["target_delivery_percent"]
        rows.append(row)
    base = json.loads((airflow_case_dir(f"{a.geometry}_{a.waveform}") / "qa_report.json").read_text()) \
        if (airflow_case_dir(f"{a.geometry}_{a.waveform}") / "qa_report.json").exists() else {}
    rows.append({"target_split_imposed": "equal pressure (baseline)", "target_split_percent": base.get("target_branch_ventilation_percent"),
                 "peak_dp_Pa": base.get("peak_pressure_drop_Pa")})
    df = pd.DataFrame(rows); df.to_csv(out_dir("outletbc") / "outlet_bc_sensitivity.csv", index=False)
    print(df.to_string(index=False))
    save("outletbc", "summary.json", {"table": df.to_dict("records")})


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("study", nargs="?", choices=list(STUDIES))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--geometry", default="healthy"); ap.add_argument("--waveform", default="symmetric")
    ap.add_argument("--level", default=cfg["mesh"]["level"])
    ap.add_argument("--levels", nargs="+", default=["coarse", "medium", "fine"])
    ap.add_argument("--co", nargs="+", type=float, default=[0.5, 1, 3, 5])
    ap.add_argument("--particle-dt", nargs="+", type=float)
    ap.add_argument("--parcels", type=int, default=None, help="parcels for particle runs in mesh/dt/seed/tracer studies")
    ap.add_argument("--parcels-list", nargs="+", type=int, default=[2500, 5000, 10000, 20000, 40000])
    ap.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    ap.add_argument("--splits", nargs="+", type=float, default=[0.4, 0.5, 0.6])
    ap.add_argument("--data")
    ap.add_argument("--np", type=int, help="MPI ranks for airflow variants")
    ap.add_argument("--no-particles", action="store_true")
    ap.add_argument("--tube-flow", type=float, default=0.2, help="L/min (low flow -> strong settling signal)")
    ap.add_argument("--tube-time", type=float, default=1.5)
    ap.add_argument("--tube-particle-um", type=float, default=10.0)
    a = ap.parse_args()
    if a.list or not a.study:
        for k, v in STUDIES.items():
            print(f"{k:13s} -> validation/{v}")
        return
    if a.np:
        cfg["openfoam"]["n_procs"] = a.np
    globals()[f"study_{a.study}"](a, cfg)


if __name__ == "__main__":
    main()
