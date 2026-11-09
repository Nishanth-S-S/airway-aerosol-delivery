"""Evaluate the benchmark: equivalence tests E1-E6 (thresholds from cloud/EQUIVALENCE_CRITERIA.md, fixed before any
cloud run), scaling, concurrency, measured end-to-end time, and the recommended production configuration.

Called by `python3 cloud/bench/bench.py summary` (on the instance, or on the Mac after downloading the results).
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "cloud" / "runner"))
EQ_CASE = "C_EQ_medium_T_N40_SYM"
MAC_MED = "V_MESH_medium_T_N40_SYM"


def _load(out, name):
    f = Path(out) / f"{name}.json"
    return json.loads(f.read_text()) if f.exists() else None


def phase_model(b2):
    """Per rank count: s/step = a + b * (pressure iterations per step), fitted on the three restart segments."""
    model = {}
    for r in sorted({x["ranks"] for x in b2 if not x["case"].startswith("E5")}):
        pts = [(x["p_iters_per_step"], x["s_per_step"]) for x in b2 if x["ranks"] == r and not x["case"].startswith("E5") and "s_per_step" in x]
        if len(pts) >= 2:
            it, s = np.array(pts).T
            b, a = np.polyfit(it, s, 1)
            model[r] = {"a": float(a), "b": float(b), "points": pts}
    return model


def mac_profile():
    aud = json.loads((ROOT / "cloud/results/perf_audit.json").read_text())
    return aud, [(v["steps"], v["p_iters_per_step"]) for v in aud["medium_case"]["phases"].values()]


def e6(out):
    """Complete cloud case vs Mac verification case."""
    from foam_field import read_internal, rel_l2
    eq, mac = ROOT / "cases/airflow" / EQ_CASE, ROOT / "cases/airflow" / MAC_MED
    qe = json.loads((eq / "qa_report.json").read_text()) if (eq / "qa_report.json").exists() else None
    if not qe:
        return {"available": False}
    qm = json.loads((mac / "qa_report.json").read_text())
    res = {"available": True, "qa_status": qe["status"],
           "split_diff_pts": qe["target_branch_ventilation_percent"] - qm["target_branch_ventilation_percent"],
           "peak_dp_rel_percent": 100 * (qe["peak_pressure_drop_Pa"] - qm["peak_pressure_drop_Pa"]) / qm["peak_pressure_drop_Pa"],
           "mean_dp_rel_percent": 100 * (qe["mean_pressure_drop_Pa"] - qm["mean_pressure_drop_Pa"]) / qm["mean_pressure_drop_Pa"],
           "U_rel_l2": {t: rel_l2(read_internal(eq / t / "U"), read_internal(mac / t / "U")) for t in ("0.5", "1", "1.5")
                        if (eq / t / "U").exists()}}
    from lib.common import load_config
    from lib.response_map import kernel, parcel_table
    cfg = load_config()
    parts = []
    for d in (1, 3, 5):
        fe = ROOT / f"cases/particles/MAP_{EQ_CASE}_P{d:02d}/results.json"
        fm = ROOT / f"cases/particles/MAP_{MAC_MED}_P{d:02d}/results.json"
        if not fe.exists():
            continue
        je, jm = json.loads(fe.read_text()), json.loads(fm.read_text())
        row = {"size_um": d}
        for k, nm in (("target_delivery_percent", "delivery"), ("total_deposition_percent", "deposition")):
            se = lambda p, n: 100 * math.sqrt(max(p, 1e-9) * (1 - p) / (0.75 * n))  # noqa: E731
            tol = max(0.3, 2 * math.hypot(se(je[k] / 100, je["n_parcels"]), se(jm[k] / 100, jm["n_parcels"])))
            row[nm] = {"cloud": je[k], "mac": jm[k], "diff": je[k] - jm[k], "tol": tol, "pass": abs(je[k] - jm[k]) <= tol}
        parts.append(row)
    res["particles"] = parts
    try:
        ke = kernel(parcel_table(ROOT / f"cases/particles/MAP_{EQ_CASE}_P03", cfg), 10)
        km = kernel(parcel_table(ROOT / f"cases/particles/MAP_{MAC_MED}_P03", cfg), 10)
        z = (ke.value_percent - km.value_percent) / np.hypot(ke.se_percent, km.se_percent)
        res["kernel_bins_within_2se"] = int((z.abs() <= 2).sum())
    except Exception as e:  # maps missing
        res["kernel_error"] = str(e)
    res["pass"] = (qe["status"] == "PASSED" and abs(res["split_diff_pts"]) <= 0.05 and abs(res["peak_dp_rel_percent"]) <= 0.5
                   and abs(res["mean_dp_rel_percent"]) <= 0.5 and len(res["U_rel_l2"]) == 3
                   and all(v <= 0.02 for v in res["U_rel_l2"].values()) and len(parts) == 3
                   and all(p["delivery"]["pass"] and p["deposition"]["pass"] for p in parts)
                   and res.get("kernel_bins_within_2se", 0) >= 9)
    # measured end-to-end time
    st = _load(out, "B5_started")
    ck = json.loads((eq / "cloud_checkpoint.json").read_text()) if (eq / "cloud_checkpoint.json").exists() else {}
    f5 = ROOT / f"cases/particles/MAP_{EQ_CASE}_P05/results.json"
    if st and f5.exists():
        res["end_to_end_h"] = (f5.stat().st_mtime - st["started"]) / 3600
        res["airflow_end_to_end_h"] = ((eq / "qa_report.json").stat().st_mtime - st["started"]) / 3600
    res["solver_wall_h"] = sum(ck.get("solver_wall_s", [])) / 3600
    return res


def evaluate(out):
    out = Path(out)
    E1, E2, E3, B2, B3, B6 = (_load(out, n) for n in ("E1", "E2", "E3", "B2", "B3", "B6"))
    tests = {}
    tests["E1"] = E1 and E1["pass"]
    tests["E2"] = E2 and E2["pass"]
    tests["E3"] = E3 and E3["pass"]
    e4 = []
    if B2:
        for x in B2:
            if x["case"].startswith("seg_") and "vs_mac" in x:
                u, p = x["vs_mac"].get("U", {}).get("rel_l2", 9), x["vs_mac"].get("p", {}).get("rel_l2", 9)
                e4.append({"case": x["case"], "U": u, "p": p, "U_over_segment_change": u / x["segment_change_U"],
                           "pass": u <= 1e-4 and p <= 1e-4 and u <= 0.1 * x["segment_change_U"]})
        tests["E4"] = bool(e4) and all(r["pass"] for r in e4)
        e5 = [x for x in B2 if x["case"].startswith("E5")]
        if e5:
            from foam_field import compare_time
            c = compare_time(ROOT / "cases/bench" / e5[0]["case"], ROOT / "cases/bench/seg_1_r8", "1.02")
            e5r = {"interrupted_at": e5[0].get("interrupted_at"), "U": c.get("U", {}).get("rel_l2"), "p": c.get("p", {}).get("rel_l2"),
                   "vs_mac_U": e5[0].get("vs_mac", {}).get("U", {}).get("rel_l2")}
            e5r["pass"] = e5r["interrupted_at"] not in (None, "1.02") and (e5r["U"] or 9) <= 1e-4 and (e5r["p"] or 9) <= 1e-4
            tests["E5"] = e5r["pass"]
    E6 = e6(out)
    tests["E6"] = E6.get("pass") if E6.get("available") else None
    # ---- performance
    aud, prof = mac_profile()
    model = phase_model(B2) if B2 else {}
    mac_case_h = aud["medium_case"]["clean_model_solver_s"] / 3600
    case_h = {r: sum(n * (m["a"] + m["b"] * it) for n, it in prof) / 3600 for r, m in model.items()}
    overhead_h = 0.0
    if B2:
        dec = [x.get("decompose_s", 0) for x in B2 if x["ranks"] == 8]
        rec = [x.get("reconstruct_s", 0) for x in B2 if x["ranks"] == 8]
        # reconstruction of a full case writes 150 times (segments write 1): scale; QA ~ 1 min
        overhead_h = (np.mean(dec) + 150 * np.mean(rec) / 1.0 + 60) / 3600 if dec and rec else 0.1
    scaling = [{"ranks": r, "case_solver_h_isolated": h, "speedup_vs_1": case_h.get(1, float("nan")) / h,
                "parallel_efficiency": case_h.get(1, float("nan")) / h / r, "core_h": h * r} for r, h in sorted(case_h.items())]
    conc = []
    seg1 = {x["ranks"]: x["s_per_step"] for x in (B2 or []) if x["case"].startswith("seg_1_") and "s_per_step" in x}
    for row in B3 or []:
        R = row["R"]
        base = seg1.get(R)
        if base is None and model.get(R) is None:
            continue
        iso = base if base else (model[R]["a"] + model[R]["b"] * 14)
        slow = row["median_s_per_step"] / iso
        h_case = (case_h.get(R) or (case_h[8] * 8 / R)) * slow + overhead_h
        conc.append({"K": row["K"], "R": R, "slowdown_vs_isolated": slow, "case_h_under_load": h_case,
                     "cases_per_hour": row["K"] / h_case, "medium_eq_core_h": h_case * R, "all_finished": row["all_finished"]})
    # choose by simulated makespan of the REAL remaining case list (relative costs from cloud/tools/plan_workload.py),
    # longest-first onto K slots; ties -> fewer ranks per case
    wl = json.loads((ROOT / "cloud/results/workload.json").read_text())
    weights = sorted((w for _, w in wl["cases"]), reverse=True)
    for c in conc:
        slots = [0.0] * c["K"]
        for w in weights:
            i = slots.index(min(slots))
            slots[i] += w * (c["case_h_under_load"] - overhead_h) + overhead_h
        c["airflow_makespan_h"] = max(slots)
    best = min(conc, key=lambda c: (round(c["airflow_makespan_h"], 1), c["R"])) if conc else None
    speed = {}
    if B6 and B6.get("mac_fine_8_ranks_same_steps"):
        c8 = [x for x in B6["cloud"] if x["ranks"] == 8 and "s_per_step" in x]
        if c8:
            speed["fine_8rank_per_step_mac_over_cloud"] = B6["mac_fine_8_ranks_same_steps"]["s_per_step"] / c8[0]["s_per_step"]
        c24 = [x for x in B6["cloud"] if x["ranks"] == 24 and "s_per_step" in x]
        if c8 and c24:
            speed["fine_24_vs_8_rank_speedup"] = c8[0]["s_per_step"] / c24[0]["s_per_step"]
    if 8 in case_h:
        speed["medium_8rank_isolated_case_h_cloud"] = case_h[8]
        speed["medium_8rank_case_h_mac_clean"] = mac_case_h
        speed["medium_8rank_case_h_mac_actual"] = aud["medium_case"]["actual_solver_s"] / 3600
    if E6.get("airflow_end_to_end_h"):
        speed["measured_full_case_airflow_end_to_end_h"] = E6["airflow_end_to_end_h"]
        speed["model_vs_measured_full_case"] = (case_h.get(8, float("nan")) + overhead_h) / E6["airflow_end_to_end_h"]
    if best:
        speed["per_core_speedup_vs_mac"] = (mac_case_h * 8) / best["medium_eq_core_h"]
    res = {"tests": tests, "E4": e4, "E5": tests.get("E5") is not None and e5r, "E6": E6, "scaling": scaling,
           "concurrency": conc, "recommended": best, "speed": speed, "overhead_h_per_case": overhead_h,
           "all_equivalence_pass": all(tests.get(k) for k in ("E1", "E2", "E4", "E5", "E6"))}
    res["markdown"] = markdown(res)
    return res


def markdown(r):
    f = lambda v, n=3: "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else (f"{v:.{n}g}" if isinstance(v, float) else str(v))  # noqa: E731
    L = ["# Cloud benchmark summary", "", "## Scientific equivalence (thresholds fixed in cloud/EQUIVALENCE_CRITERIA.md)", "",
         "| Test | Result |", "|---|---|"]
    for k in ("E1", "E2", "E3", "E4", "E5", "E6"):
        v = r["tests"].get(k)
        L.append(f"| {k} | {'PASS' if v else ('not run' if v is None else 'FAIL')} |")
    L += ["", f"All required tests (E1, E2, E4, E5, E6) pass: **{r['all_equivalence_pass']}** (E3 decides only whether "
          "the Mac n40 meshes are reused).", "", "## Rank scaling (one medium case, isolated, from restart segments)", "",
          "| Ranks | Solver time per case (h) | Speed-up vs 1 rank | Efficiency | Core-hours per case |", "|---|---|---|---|---|"]
    for s in r["scaling"]:
        L.append(f"| {s['ranks']} | {f(s['case_solver_h_isolated'])} | {f(s['speedup_vs_1'])} | {f(s['parallel_efficiency'])} | {f(s['core_h'])} |")
    L += ["", "## Concurrency (K simultaneous cases x R ranks)", "",
          "| K x R | Slow-down vs isolated | Hours per case under load | Cases per hour | Simulated airflow makespan, all cases (h) |",
          "|---|---|---|---|---|"]
    for c in r["concurrency"]:
        L.append(f"| {c['K']} x {c['R']} | {f(c['slowdown_vs_isolated'])} | {f(c['case_h_under_load'])} | {f(c['cases_per_hour'])} | "
                 f"{f(c['airflow_makespan_h'])} |")
    if r["recommended"]:
        L += ["", f"Recommended: **{r['recommended']['K']} concurrent cases x {r['recommended']['R']} ranks**."]
    L += ["", "## Speed vs the Mac", ""] + [f"* {k}: {f(v)}" for k, v in r["speed"].items()]
    return "\n".join(L) + "\n"
