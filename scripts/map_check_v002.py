#!/usr/bin/env python3
"""Re-validation of the release-time response map on v002 (solver v2), against direct runs not used for the maps.

    python scripts/map_check_v002.py

Pair sets (each direct run is an independent simulation of one pulse/continuous schedule):
  protocol : P<d>_<EARLY|MID|LATE|CONT>_<geo>_<wave> on training conditions (seed 1, 20 000 parcels)
  seeds    : V_SEED<k>_* repeats (seeds 2-6)
  eval     : E_* runs of the frozen strategies, all 17 conditions incl. held-out (seed 1001)
Outcomes: target delivery (primary) and total wall deposition.
Speed-up: measured solver wall time of a map run vs a direct run, and the number of candidate schedules the
optimisation grid evaluates per (condition, size).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config  # noqa: E402
from lib.conditions import load_conditions  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PC = ROOT / "cases" / "particles"
OUT = ROOT / "results" / "response_map_v002"
GEO = {"healthy": "HLT", "n20": "N20", "n40": "N40"}
WAVE = {(2, 5): "EAR", (3, 3): "SYM", (5, 2): "LAT"}


def walltime(case: Path) -> float:
    L = case / "logs" / "airwayParcelFoam.log"
    if not L.exists():
        return float("nan")
    m = re.findall(r"ExecutionTime = ([\d.]+) s", L.read_text(errors="ignore"))
    return float(m[-1]) if m else float("nan")


def direct_values(case: Path):
    """Mass-weighted delivery/deposition with SE, straight from the direct run's parcel files."""
    from lib.response_map import parcel_table
    cfg = load_config()
    df = parcel_table(case, cfg)
    w = df.mass.values
    neff = w.sum() ** 2 / (w ** 2).sum()
    out = {}
    for name, y in (("delivery", df.crossed.values), ("deposition", (df.fate == "deposited").values)):
        p = (w * y).sum() / w.sum()
        out[name] = (100 * p, 100 * np.sqrt(p * (1 - p) / neff))
    return out


def map_values(mp, s0, s1):
    out = {}
    for name, key in (("delivery", "primary"), ("deposition", None)):
        if key:
            v, se = mp.window(np.array([s0]), np.array([s1]), key)
            out[name] = (float(v[0]), float(se[0]))
    # deposition from the parcel table directly
    sel = (mp.df.F_inject >= s0) & (mp.df.F_inject < s1)
    d = mp.df[sel]
    w = d.mass.values
    y = (d.fate == "deposited").values
    p = (w * y).sum() / w.sum()
    neff = w.sum() ** 2 / (w ** 2).sum()
    out["deposition"] = (100 * p, 100 * np.sqrt(p * (1 - p) / neff))
    return out


def main():
    import optimize as O
    from lib.response_map import add_penetration, parcel_table
    cfg = load_config()
    reg = load_conditions()
    OUT.mkdir(parents=True, exist_ok=True)
    rels = {"EARLY": (0.1, 0.2), "MID": (0.3, 0.4), "LATE": (0.5, 0.6), "CONT": (0.0, 1.0 + 1e-9)}
    maps = {}

    def get_map(cond, d):
        k = (cond, d)
        if k not in maps:
            dd = PC / f"MAP_{cond}_P{d:02d}"
            if not (dd / "results.json").exists():
                maps[k] = None
            else:
                m = O.Map(dd, cfg)
                m.df = add_penetration(parcel_table(dd, cfg), dd, cfg=cfg)
                maps[k] = m
        return maps[k]

    rows = []
    # protocol + seeds
    for c in reg["training"]:
        tag = f"{GEO[c['geometry']]}_{WAVE[(c['a'], c['b'])]}"
        for d in reg["optimization"]["sizes_um"]:
            mp = get_map(c["id"], d)
            if mp is None:
                continue
            for rk, (s0, s1) in rels.items():
                case = PC / f"P{d:02d}_{rk}_{tag}"
                if (case / "results.json").exists():
                    rows.append(("protocol", c["id"], d, rk, s0, s1, case))
    for case in sorted(PC.glob("V_SEED*")):
        m = re.match(r"V_SEED(\d+)_(T_\w+?)_P(\d\d)_(\w+)$", case.name)
        if m and (case / "results.json").exists():
            s0, s1 = {"middle": (0.3, 0.4), "late": (0.5, 0.6), "early": (0.1, 0.2)}[m.group(4)]
            rows.append(("seeds", m.group(2), int(m.group(3)), m.group(4), s0, s1, case))
    for case in sorted(PC.glob("E_*")):
        m = re.match(r"E_(.+)_P(\d\d)_(CONT|S(\d{4}))$", case.name)
        if m and (case / "results.json").exists():
            if m.group(3) == "CONT":
                s0, s1 = 0.0, 1.0 + 1e-9
            else:
                s0 = int(m.group(4)) / 1000
                s1 = s0 + reg["optimization"]["window_width"]
            rows.append(("eval", m.group(1), int(m.group(2)), m.group(3), s0, s1, case))
    recs = []
    for setname, cond, d, label, s0, s1, case in rows:
        mp = get_map(cond, d)
        if mp is None:
            continue
        mv = map_values(mp, s0, s1)
        dv = direct_values(case)
        for oc in ("delivery", "deposition"):
            (pm, sm), (pd_, sd) = mv[oc], dv[oc]
            recs.append({"set": setname, "condition": cond, "size_um": d, "schedule": label, "s0": s0, "s1": s1, "outcome": oc,
                         "map": pm, "map_se": sm, "direct": pd_, "direct_se": sd, "abs_err": pd_ - pm,
                         "rel_err_percent": 100 * (pd_ - pm) / pd_ if pd_ > 1 else np.nan,
                         "z": (pd_ - pm) / np.hypot(sm, sd), "direct_case": case.name,
                         "t_direct_s": walltime(case), "t_map_s": walltime(PC / f"MAP_{cond}_P{d:02d}")})
    R = pd.DataFrame(recs)
    R.to_csv(OUT / "map_vs_direct.csv", index=False)
    summ = {}
    for (st, oc), g in R.groupby(["set", "outcome"]):
        summ[f"{st}|{oc}"] = {"n": int(len(g)), "mean_abs_err_pts": float(g.abs_err.abs().mean()), "mean_signed_err_pts": float(g.abs_err.mean()),
                              "rms_err_pts": float(np.sqrt((g.abs_err ** 2).mean())), "max_abs_err_pts": float(g.abs_err.abs().max()),
                              "mean_rel_err_percent": float(g.rel_err_percent.abs().mean()), "mean_z": float(g.z.mean()), "sd_z": float(g.z.std()),
                              "frac_abs_z_le_2": float((g.z.abs() <= 2).mean()),
                              "mean_z_se": float(g.z.std() / np.sqrt(len(g))) if len(g) > 1 else None}
    # computational cost
    tm = R.drop_duplicates(["condition", "size_um"]).t_map_s.dropna()
    td = R.drop_duplicates("direct_case").t_direct_s.dropna()
    opt = reg["optimization"]
    n_grid = int(round((opt["s_max"] - opt["window_width"] - opt["s_min"]) / opt["s_step"])) + 1
    summ["cost"] = {"map_run_wall_s_median": float(tm.median()), "direct_run_wall_s_median": float(td.median()),
                    "grid_candidates_per_condition_size": n_grid,
                    "speedup_vs_direct_grid": float(n_grid * td.median() / tm.median()),
                    "note": "direct runs use 20 000 parcels, maps 100 000; a map window of width 0.1 holds ~10 000 parcels, "
                            "so per-candidate Monte Carlo precision of the map is ~1.4x worse than one direct run"}
    (OUT / "summary.json").write_text(json.dumps(summ, indent=2, default=float))
    print(json.dumps(summ, indent=1, default=float))
    fig, axs = plt.subplots(1, 2, figsize=(12, 5))
    for ax, oc in zip(axs, ("delivery", "deposition")):
        for st, col in (("protocol", "#264653"), ("seeds", "#e9c46a"), ("eval", "#e76f51")):
            g = R[(R.set == st) & (R.outcome == oc)]
            if len(g):
                ax.errorbar(g["map"], g["direct"], xerr=2 * g["map_se"], yerr=2 * g["direct_se"], fmt="o", ms=3.5, color=col, alpha=0.8,
                            elinewidth=0.6, label=f"{st} (n={len(g)})")
        lo, hi = R[R.outcome == oc][["map", "direct"]].min().min() - 1, R[R.outcome == oc][["map", "direct"]].max().max() + 1
        ax.plot([lo, hi], [lo, hi], "k--", lw=1); ax.grid(alpha=.3); ax.legend(fontsize=8)
        ax.set_xlabel("response-map prediction (%)"); ax.set_ylabel("direct simulation (%)")
        ax.set_title(f"v002 {oc}: map vs independent direct runs (±2 SE)")
    fig.tight_layout(); fig.savefig(OUT / "map_vs_direct_v002.png", dpi=130); plt.close(fig)


if __name__ == "__main__":
    main()
