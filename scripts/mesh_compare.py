#!/usr/bin/env python3
"""Coarse vs medium (vs fine) mesh comparison against validation/04_mesh_independence/CRITERIA.md.

    python scripts/mesh_compare.py                                  # T_N40_SYM coarse vs V_MESH_medium_T_N40_SYM
    python scripts/mesh_compare.py --fine V_MESH_fine_T_N40_SYM     # adds the fine level if it exists
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config  # noqa: E402
from lib.postproc import airflow_timeseries  # noqa: E402
from lib.response_map import kernel, parcel_table  # noqa: E402
from lib.vtk_io import read_vtk_polydata  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = ROOT / "validation" / "04_mesh_independence" / "results"
AF = ROOT / "cases" / "airflow"
PC = ROOT / "cases" / "particles"


def snapshot(aid, t_want=1.0):
    base = AF / aid / "postProcessing" / "midPlane"
    times = sorted((float(p.name), p) for p in base.iterdir() if (p / "yMid.vtk").exists())
    t, p = min(times, key=lambda x: abs(x[0] - t_want))
    v = read_vtk_polydata(p / "yMid.vtk")
    cen = np.array([v["points"][q].mean(0) for q in v["polys"]]) * 1e3
    return t, cen[:, [0, 2]], v["cell_data"]["U"]


def sample(cen, U, pts):
    from scipy.interpolate import griddata
    return np.stack([griddata(cen, U[:, k], pts, method="linear") for k in range(3)], 1)


def l2rel(a, b):
    m = np.isfinite(a).all(1) & np.isfinite(b).all(1)
    ma, mb = np.linalg.norm(a[m], axis=1), np.linalg.norm(b[m], axis=1)
    return float(np.sqrt(np.mean((ma - mb) ** 2)) / np.sqrt(np.mean(mb ** 2))), int(m.sum())


def se_pct(p, n_eff):
    return 100 * math.sqrt(max(p * (1 - p), 0) / max(n_eff, 1))


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--coarse", default="T_N40_SYM")
    ap.add_argument("--medium", default="V_MESH_medium_T_N40_SYM")
    ap.add_argument("--fine", default=None)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    levels = [("coarse", a.coarse), ("medium", a.medium)] + ([("fine", a.fine)] if a.fine else [])
    res = {"criteria_file": "validation/04_mesh_independence/CRITERIA.md", "levels": {}}

    # ---------------- airflow
    for lab, aid in levels:
        q = json.loads((AF / aid / "qa_report.json").read_text())
        res["levels"][lab] = {"case": aid, "cells": q.get("mesh_cells"), "qa": q["status"],
                              "imbalance_percent": q["mean_imbalance_percent"],
                              "target_split_percent": q["target_branch_ventilation_percent"],
                              "peak_dp_Pa": q["peak_pressure_drop_Pa"], "mean_dp_Pa": q["mean_pressure_drop_Pa"],
                              "wallclock_min": q.get("wallclock_min")}
    C, M = res["levels"]["coarse"], res["levels"]["medium"]
    chk = {}
    chk["C1"] = {"pass": C["imbalance_percent"] < 0.5 and M["imbalance_percent"] < 0.5,
                 "value": [C["imbalance_percent"], M["imbalance_percent"]]}
    d_split = C["target_split_percent"] - M["target_split_percent"]
    chk["C2"] = {"pass": abs(d_split) <= 0.5, "value": d_split, "unit": "pts"}
    r_peak = (C["peak_dp_Pa"] - M["peak_dp_Pa"]) / M["peak_dp_Pa"] * 100
    r_mean = (C["mean_dp_Pa"] - M["mean_dp_Pa"]) / M["mean_dp_Pa"] * 100
    chk["C3"] = {"pass": abs(r_peak) <= 5 and abs(r_mean) <= 5, "value": {"peak_rel_percent": r_peak, "mean_rel_percent": r_mean}}

    # velocity fields
    tc, cc, uc = snapshot(a.coarse)
    tm, cm, um = snapshot(a.medium)
    g = cfg["geometry"]
    ang = math.radians(g["branch_angle_deg"])
    bif = np.array([g["bifurcation_point_mm"][0], g["bifurcation_point_mm"][2]])
    u_ax = np.array([math.sin(ang), math.cos(ang)]); e1 = np.array([math.cos(ang), -math.sin(ang)])
    gx, gz = np.meshgrid(np.arange(-34, 34, 0.2), np.arange(0, 94, 0.2))
    P = np.c_[gx.ravel(), gz.ravel()]
    from scipy.spatial import cKDTree
    inside = (cKDTree(cc).query(P)[0] < 0.35) & (cKDTree(cm).query(P)[0] < 0.25)
    junc = inside & (np.abs(P[:, 0]) < 6) & (P[:, 1] > 34) & (P[:, 1] < 50)
    s = (P - bif) @ u_ax; nn = (P - bif) @ e1
    jet = inside & (s > 10) & (s < 40) & (np.abs(nn) < 3.2)
    Uc_j, Um_j = sample(cc, uc, P[junc]), sample(cm, um, P[junc])
    Uc_n, Um_n = sample(cc, uc, P[jet]), sample(cm, um, P[jet])
    l2j, nj = l2rel(Uc_j, Um_j)
    l2n, nn_ = l2rel(Uc_n, Um_n)
    vmax_c, vmax_m = np.nanmax(np.linalg.norm(Uc_n, axis=1)), np.nanmax(np.linalg.norm(Um_n, axis=1))
    chk["C4a"] = {"pass": l2j <= 0.10, "value": l2j, "n_points": nj, "snapshot_t": [tc, tm]}
    chk["C4b"] = {"pass": l2n <= 0.10 and abs(vmax_c - vmax_m) / vmax_m <= 0.05, "value": {"l2_rel": l2n, "jet_max_coarse": vmax_c,
                  "jet_max_medium": vmax_m, "jet_max_rel_percent": 100 * (vmax_c - vmax_m) / vmax_m}, "n_points": nn_}

    # ---------------- particles
    prow = []
    for d in (1, 3, 5):
        rc, rm = PC / f"MAP_{a.coarse}_P{d:02d}" / "results.json", PC / f"MAP_{a.medium}_P{d:02d}" / "results.json"
        if not (rc.exists() and rm.exists()):
            prow.append({"size_um": d, "available": False}); continue
        jc, jm = json.loads(rc.read_text()), json.loads(rm.read_text())
        row = {"size_um": d, "available": True}
        for key, name in (("target_delivery_percent", "delivery"), ("total_deposition_percent", "deposition"),
                          ("upstream_deposition_percent", "upstream_dep"), ("constriction_deposition_percent", "constriction_dep"),
                          ("target_deposition_percent", "target_dep"), ("suspended_percent", "suspended")):
            sec, sem = se_pct(jc[key] / 100, 0.75 * jc["n_parcels"]), se_pct(jm[key] / 100, 0.75 * jm["n_parcels"])
            row[f"{name}_coarse"], row[f"{name}_medium"] = jc[key], jm[key]
            row[f"{name}_diff"] = jc[key] - jm[key]
            row[f"{name}_tol"] = max(1.0, 2 * math.hypot(sec, sem))
        prow.append(row)
    P_ = pd.DataFrame(prow)
    av = P_[P_.available == True]  # noqa: E712
    chk["C5"] = {"pass": bool(len(av) == 3 and (av.delivery_diff.abs() <= av.delivery_tol).all()),
                 "value": av[["size_um", "delivery_coarse", "delivery_medium", "delivery_diff", "delivery_tol"]].to_dict("records")}
    chk["C6"] = {"pass": bool(len(av) == 3 and (av.deposition_diff.abs() <= av.deposition_tol).all()),
                 "value": av[["size_um", "deposition_coarse", "deposition_medium", "deposition_diff", "deposition_tol"]].to_dict("records")}
    # kernel C7 (3 um)
    try:
        kc = kernel(parcel_table(PC / f"MAP_{a.coarse}_P03", cfg), 10)
        km = kernel(parcel_table(PC / f"MAP_{a.medium}_P03", cfg), 10)
        z = (kc.value_percent - km.value_percent) / np.hypot(kc.se_percent, km.se_percent)
        chk["C7"] = {"pass": int((z.abs() <= 2).sum()) >= 9, "value": {"bins_within_2se": int((z.abs() <= 2).sum()),
                     "coarse": kc.value_percent.round(2).tolist(), "medium": km.value_percent.round(2).tolist()}, "gating": False}
    except Exception as e:
        chk["C7"] = {"pass": None, "error": str(e), "gating": False}
    P_.to_csv(OUT / "mesh_particles.csv", index=False)
    gating = ["C1", "C2", "C3", "C4a", "C4b", "C5", "C6"]
    res["checks"] = chk
    res["coarse_adequate"] = all(chk[k]["pass"] for k in gating)
    (OUT / "summary.json").write_text(json.dumps(res, indent=2, default=float))

    # ---------------- figures
    fig, axs = plt.subplots(1, 3, figsize=(16, 5))
    for ax, (lab, aid) in zip(axs[:2], levels[:2]):
        t_, cen, U = snapshot(aid)
        from matplotlib.collections import PolyCollection
        v = read_vtk_polydata(sorted((AF / aid / "postProcessing" / "midPlane").glob(f"{t_:g}/yMid.vtk"))[0]) if False else None
        sc = ax.scatter(cen[:, 0], cen[:, 1], c=np.linalg.norm(U, axis=1), s=1.5, cmap="turbo", vmin=0, vmax=max(vmax_c, vmax_m))
        ax.set_xlim(-6, 24); ax.set_ylim(34, 75); ax.set_aspect("equal")
        ax.set_title(f"{lab}: |U| at t = {t_:.2f} s ({res['levels'][lab]['cells']:,} cells)"); ax.set_xlabel("x (mm)"); ax.set_ylabel("z (mm)")
    fig.colorbar(sc, ax=axs[:2], shrink=0.7, label="|U| (m/s)")
    ax = axs[2]
    ts_c, ts_m = airflow_timeseries(AF / a.coarse), airflow_timeseries(AF / a.medium)
    ax.plot(ts_c.time, ts_c.dp_Pa, label="coarse Δp"); ax.plot(ts_m.time, ts_m.dp_Pa, "--", label="medium Δp")
    ax2 = ax.twinx()
    ax2.plot(ts_c.time, 100 * ts_c.Q_target / ts_c.Q_out_total.where(ts_c.Q_out_total > 1e-8), color="#e76f51", lw=0.8, label="coarse split")
    ax2.plot(ts_m.time, 100 * ts_m.Q_target / ts_m.Q_out_total.where(ts_m.Q_out_total > 1e-8), "--", color="#264653", lw=0.8, label="medium split")
    ax2.set_ylim(30, 50); ax2.set_ylabel("target branch share of outflow (%)")
    ax.set_xlim(0, 2); ax.set_xlabel("time (s)"); ax.set_ylabel("pressure drop (Pa)"); ax.legend(loc="upper left", fontsize=8); ax2.legend(loc="upper right", fontsize=8)
    ax.set_title("Pressure drop and flow split")
    fig.savefig(OUT / "mesh_fields.png", dpi=130, bbox_inches="tight"); plt.close(fig)
    # criteria table (markdown)
    L = ["| # | Criterion | Measured (coarse vs medium) | Threshold | Result |", "|---|---|---|---|---|"]
    L.append(f"| C1 | Airflow conservation | imbalance {C['imbalance_percent']:.1e} % / {M['imbalance_percent']:.1e} % | < 0.5 % each | {'PASS' if chk['C1']['pass'] else 'FAIL'} |")
    L.append(f"| C2 | Target-branch flow fraction | {C['target_split_percent']:.2f} vs {M['target_split_percent']:.2f} % (Δ {d_split:+.2f} pts) | ≤ 0.5 pts | {'PASS' if chk['C2']['pass'] else 'FAIL'} |")
    L.append(f"| C3 | Pressure drop | peak {C['peak_dp_Pa']:.3f} vs {M['peak_dp_Pa']:.3f} Pa ({r_peak:+.1f} %); mean {C['mean_dp_Pa']:.3f} vs {M['mean_dp_Pa']:.3f} Pa ({r_mean:+.1f} %) | ≤ 5 % each | {'PASS' if chk['C3']['pass'] else 'FAIL'} |")
    L.append(f"| C4a | Velocity near junction (L2 of \\|U\\|, t≈{tc:.2f} s) | {100 * l2j:.1f} % ({nj} points) | ≤ 10 % | {'PASS' if chk['C4a']['pass'] else 'FAIL'} |")
    L.append(f"| C4b | Velocity in narrowing/jet | L2 {100 * l2n:.1f} %; jet max {vmax_c:.3f} vs {vmax_m:.3f} m/s ({100 * (vmax_c - vmax_m) / vmax_m:+.1f} %) | ≤ 10 %; ≤ 5 % | {'PASS' if chk['C4b']['pass'] else 'FAIL'} |")
    for _, r in av.iterrows():
        L.append(f"| C5 | Target delivery, {r.size_um:g} µm | {r.delivery_coarse:.2f} vs {r.delivery_medium:.2f} % (Δ {r.delivery_diff:+.2f} pts) | ≤ {r.delivery_tol:.2f} pts | {'PASS' if abs(r.delivery_diff) <= r.delivery_tol else 'FAIL'} |")
    for _, r in av.iterrows():
        L.append(f"| C6 | Total deposition, {r.size_um:g} µm | {r.deposition_coarse:.2f} vs {r.deposition_medium:.2f} % (Δ {r.deposition_diff:+.2f} pts) | ≤ {r.deposition_tol:.2f} pts | {'PASS' if abs(r.deposition_diff) <= r.deposition_tol else 'FAIL'} |")
    if chk["C7"].get("pass") is not None:
        L.append(f"| C7 | Release-time kernel, 3 µm (not gating) | {chk['C7']['value']['bins_within_2se']}/10 bins within 2 SE | ≥ 9/10 | {'PASS' if chk['C7']['pass'] else 'FAIL'} |")
    missing = P_[P_.available != True].size_um.tolist()  # noqa: E712
    if missing:
        L.append(f"| C5/C6 | sizes not yet available | {missing} | — | INCOMPLETE |")
    (OUT / "criteria_table.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    print("\ncoarse adequate (C1-C6 all pass):", res["coarse_adequate"])


if __name__ == "__main__":
    main()
