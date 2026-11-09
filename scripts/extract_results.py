#!/usr/bin/env python3
"""Phases 11-13: outcome metrics, particle mass accounting and results/results.csv.

    python scripts/extract_results.py --case P03_CONT_HLT_SYM
    python scripts/extract_results.py --all          # rebuild results.csv from every finished case

Definitions (all % of the measured introduced aerosol mass M_in):
  target_delivery_percent      mass whose FIRST crossing of the target-entry disc was recorded
                               (each parcel counted once; transport measure, NOT part of the balance)
  *_deposition_percent         wall deposits classified by position (lib/postproc.classify_region)
  *_outlet_escape_percent      mass leaving through each outlet
  suspended_percent            mass still airborne at the end of the simulation
  mass_balance_error_percent   100 * (M_in - deposited - escaped - suspended) / M_in
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config, read_status, update_status  # noqa: E402
from lib.postproc import classify_region, particle_outputs  # noqa: E402

RESULTS_CSV = ROOT / "results" / "results.csv"
COLUMNS = ["case_id", "particle_size_um", "release_strategy", "narrowing_percent", "waveform", "airflow_case",
           "introduced_mass", "introduced_mass_target", "introduced_mass_error_percent", "n_parcels",
           "target_delivery_percent", "target_deposition_percent", "upstream_deposition_percent",
           "constriction_deposition_percent", "comparison_branch_deposition_percent",
           "total_deposition_percent", "target_outlet_escape_percent", "comparison_outlet_escape_percent",
           "inlet_escape_percent", "suspended_percent", "target_branch_ventilation_percent",
           "comparison_branch_ventilation_percent", "peak_pressure_drop_pa", "mean_pressure_drop_pa",
           "arrival_time_mean", "arrival_time_p10", "arrival_time_median", "arrival_time_p90",
           "mass_balance_error_percent", "mesh_status", "solver_status", "qa_status", "qa_notes"]


def extract_case(cfg, case_id: str) -> dict | None:
    case = ROOT / "cases" / "particles" / case_id
    o = particle_outputs(case)
    meta = o["meta"]
    if o["massBudget"] is None or o["finalParcels"] is None:
        return None
    mb, fp = o["massBudget"], o["finalParcels"]
    M = float(mb.injected_mass.iloc[-1])
    pct = lambda x: 100.0 * float(x) / M if M > 0 else float("nan")  # noqa: E731
    dep = fp[fp.active == 0]
    sus = fp[fp.active == 1]
    reg = classify_region(dep[["x", "y", "z"]].values, cfg) if len(dep) else np.array([])
    dep_by = {r: float(dep.mass[reg == r].sum()) for r in ("upstream", "constriction", "target", "comparison")}
    esc = o["escapes"]
    esc_by = esc.groupby("boundary").mass.sum().to_dict() if esc is not None and len(esc) else {}
    cr = o["targetPlaneCrossings"]
    crossed = float(cr.mass.sum()) if cr is not None and len(cr) else 0.0
    deposited, escaped, suspended = float(dep.mass.sum()), float(sum(esc_by.values())), float(sus.mass.sum())
    balance_err = pct(M - deposited - escaped - suspended)

    af = ROOT / "cases" / "airflow" / meta["airflow_case"]
    afqa = json.loads((af / "qa_report.json").read_text()) if (af / "qa_report.json").exists() else {}
    st = read_status()
    log = (case / "logs" / "airwayParcelFoam.log")
    solver_ok = log.exists() and "\nEnd" in log.read_text(errors="ignore")
    import re
    m_end = re.search(r"^endTime\s+([\d.eE+-]+);", (case / "constant" / "particleParameters").read_text(), re.M)
    T_end = float(m_end.group(1))
    reached = float(mb.time.iloc[-1]) >= T_end - 1e-6
    target_M = meta["introduced_mass_target_kg"]
    m_err = 100 * (M - target_M) / target_M

    qa_problems = []
    if abs(balance_err) > cfg["qa"]["particle_mass_balance_percent"]:
        qa_problems.append(f"mass balance error {balance_err:.3f} % > {cfg['qa']['particle_mass_balance_percent']} %")
    if not (solver_ok and reached):
        qa_problems.append("particle solver did not finish")
    if abs(m_err) > 5.0:
        qa_problems.append(f"introduced mass {m_err:+.2f} % from target (inlet flow sampling)")
    if afqa.get("status") != "PASSED":
        qa_problems.append(f"airflow case {meta['airflow_case']} not QA-passed")

    if cr is not None and len(cr):
        w = cr.mass.values
        t = cr.time.values
        order = np.argsort(t)
        cw = np.cumsum(w[order]) / w.sum()
        q = lambda f: float(t[order][np.searchsorted(cw, f)])  # noqa: E731
        at_mean, at10, at50, at90 = float(np.average(t, weights=w)), q(0.1), q(0.5), q(0.9)
    else:
        at_mean = at10 = at50 = at90 = float("nan")

    row = {
        "case_id": case_id, "particle_size_um": meta["particle_size_um"], "release_strategy": meta["release_strategy"],
        "narrowing_percent": meta["narrowing_percent"], "waveform": meta["waveform"],
        "airflow_case": meta["airflow_case"], "introduced_mass": M, "introduced_mass_target": target_M,
        "introduced_mass_error_percent": m_err, "n_parcels": int(mb.n_injected.iloc[-1]),
        "target_delivery_percent": pct(crossed),
        "target_deposition_percent": pct(dep_by["target"]),
        "upstream_deposition_percent": pct(dep_by["upstream"]),
        "constriction_deposition_percent": pct(dep_by["constriction"]),
        "comparison_branch_deposition_percent": pct(dep_by["comparison"]),
        "total_deposition_percent": pct(deposited),
        "target_outlet_escape_percent": pct(esc_by.get("targetOutlet", 0)),
        "comparison_outlet_escape_percent": pct(esc_by.get("comparisonOutlet", 0)),
        "inlet_escape_percent": pct(esc_by.get("inlet", 0)),
        "suspended_percent": pct(suspended),
        "target_branch_ventilation_percent": afqa.get("target_branch_ventilation_percent"),
        "comparison_branch_ventilation_percent": afqa.get("comparison_branch_ventilation_percent"),
        "peak_pressure_drop_pa": afqa.get("peak_pressure_drop_Pa"),
        "mean_pressure_drop_pa": afqa.get("mean_pressure_drop_Pa"),
        "arrival_time_mean": at_mean, "arrival_time_p10": at10, "arrival_time_median": at50, "arrival_time_p90": at90,
        "mass_balance_error_percent": balance_err,
        "mesh_status": st.get(meta["airflow_case"], {}).get("mesh_status", ""),
        "solver_status": "completed" if solver_ok and reached else "FAILED",
        "qa_status": "PASSED" if not qa_problems else "FAILED",
        "qa_notes": "; ".join(qa_problems),
    }
    (case / "results.json").write_text(json.dumps(row, indent=2, default=float))
    update_status(case_id, particle_status=row["solver_status"], qa_status=row["qa_status"],
                  solver_status=st.get(meta["airflow_case"], {}).get("solver_status", ""),
                  mesh_status=row["mesh_status"],
                  notes=(f"delivery {row['target_delivery_percent']:.2f} %, balance err {balance_err:.2e} %"
                         + (" | " + row["qa_notes"] if qa_problems else "")))
    return row


def rebuild_results_csv():
    rows = []
    for f in sorted((ROOT / "cases" / "particles").glob("P[0-9][0-9]_*/results.json")):   # study cases only
        rows.append(json.loads(f.read_text()))
    df = pd.DataFrame(rows, columns=COLUMNS)
    df.to_csv(RESULTS_CSV, index=False, float_format="%.6g")
    return df


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    ids = [a.case] if a.case else [p.name for p in sorted((ROOT / "cases" / "particles").iterdir())
                                   if (p / "postProcessing" / "airwayParcels" / "massBudget.csv").exists()]
    for cid in ids:
        r = extract_case(cfg, cid)
        if r:
            print(f"[{r['qa_status']}] {cid}: target delivery {r['target_delivery_percent']:.2f} %, "
                  f"mass balance error {r['mass_balance_error_percent']:.2e} %")
    df = rebuild_results_csv()
    print(f"[ok] results/results.csv: {len(df)} row(s)")


if __name__ == "__main__":
    main()
