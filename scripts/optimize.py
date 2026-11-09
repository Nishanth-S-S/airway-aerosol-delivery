#!/usr/bin/env python3
"""Three-way release-strategy comparison (docs/PREREGISTRATION.md + Amendment 1).

    python scripts/optimize.py select      # TRAINING maps only -> results/optimization/frozen_strategies.json
    python scripts/optimize.py evaluate    # direct, fresh-seed runs of the frozen strategies on all 17 conditions
    python scripts/optimize.py report      # tables + figures (+ response-map accuracy on these independent runs)

Primary outcome: D = target-plane first crossing (%). Exploratory: D_10 (plug and Poiseuille) — selected and
reported separately, never used for the primary claims.

Strategy = (particle diameter d, pulse start s), pulse width w fixed, equal introduced mass, flow-proportional release.
  A  continuous release (F 0-1); d = argmax of the training-mean delivery
  B  argmax_{d,s} D_ref(d,s)                    (reference condition from config/conditions.yaml)
  C  argmax_{d,s} min_k D_k(d,s) over the 9 training conditions
Search: exhaustive grid s in [s_min, s_max - w] step s_step for every d — identical budget for B and C.
Map estimates: D_k(d,s) = mass-weighted fraction of continuous-run parcels released in [s, s+w) that reached the plane.

Degeneracy rule (fixed 2026-11-05, before any training map was viewed): C is "degenerate" if the candidates whose
objective lies within 2 x SE of the best one span more than half of the feasible s range for the chosen d. Then the
pre-registered alternative (CVaR = mean of the worst 3 training conditions) is ALSO computed from training data and
reported; the frozen C remains the max-min choice (the objective is not switched).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config  # noqa: E402
from lib.conditions import all_conditions, load_conditions  # noqa: E402
from lib.response_map import OUTCOMES, add_penetration, parcel_table  # noqa: E402

PC = ROOT / "cases" / "particles"
OUT = ROOT / "results" / "optimization"
FROZEN = OUT / "frozen_strategies.json"
OUTCOME_SETS = {"primary": "target_delivery", "exploratory_D10_plug": "penetration_10mL",
                "exploratory_D10_poiseuille": "poiseuille_10mL"}


class Map:
    """Fast window estimates from one continuous-release run (prefix sums over parcels sorted by release F)."""

    def __init__(self, case_dir: Path, cfg: dict):
        df = add_penetration(parcel_table(case_dir, cfg), case_dir, cfg=cfg)
        df = df.sort_values("F_inject")
        self.F = df.F_inject.values
        self.w = df.mass.values
        self.cw = np.concatenate([[0], np.cumsum(self.w)])
        self.cw2 = np.concatenate([[0], np.cumsum(self.w ** 2)])
        self.cy = {}
        for name, oc in OUTCOME_SETS.items():
            y = OUTCOMES[oc](df).values.astype(float)
            self.cy[name] = np.concatenate([[0], np.cumsum(self.w * y)])
        self.n = len(df)

    def window(self, s0, s1, outcome="primary"):
        i, j = np.searchsorted(self.F, s0, "left"), np.searchsorted(self.F, s1, "left")
        W = self.cw[j] - self.cw[i]
        p = np.where(W > 0, (self.cy[outcome][j] - self.cy[outcome][i]) / np.where(W > 0, W, 1), np.nan)
        neff = np.where(self.cw2[j] - self.cw2[i] > 0, W ** 2 / np.where(self.cw2[j] - self.cw2[i] > 0, self.cw2[j] - self.cw2[i], 1), 0)
        se = np.sqrt(np.clip(p * (1 - p), 0, None) / np.where(neff > 0, neff, 1))
        return 100 * p, 100 * se


def load_maps(cfg, cond_ids, sizes):
    maps, missing = {}, []
    for c in cond_ids:
        for d in sizes:
            dd = PC / f"MAP_{c}_P{d:02d}"
            if (dd / "results.json").exists():
                maps[(c, d)] = Map(dd, cfg)
            else:
                missing.append(dd.name)
    return maps, missing


def select(cfg):
    reg = load_conditions()
    opt = reg["optimization"]
    train = [c["id"] for c in reg["training"]]
    ref = reg["reference_condition"]
    sizes, w = opt["sizes_um"], opt["window_width"]
    maps, missing = load_maps(cfg, train, sizes)
    if missing:
        sys.exit("training maps missing - cannot select: " + ", ".join(missing))
    s_grid = np.round(np.arange(opt["s_min"], opt["s_max"] - w + 1e-9, opt["s_step"]), 6)
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = {"frozen_on": dt.datetime.now().isoformat(timespec="seconds"), "training_conditions": train,
              "reference_condition": ref, "window_width": w, "s_grid": [float(s_grid[0]), float(s_grid[-1]), opt["s_step"]],
              "sizes_um": sizes, "maps": {f"{c}|{d}": f"MAP_{c}_P{d:02d}" for c, d in maps}, "strategies": {}}
    tables = []
    for oname in OUTCOME_SETS:
        D = np.zeros((len(sizes), len(s_grid), len(train)))
        SE = np.zeros_like(D)
        for i, d in enumerate(sizes):
            for k, c in enumerate(train):
                D[i, :, k], SE[i, :, k] = maps[(c, d)].window(s_grid, s_grid + w, oname)
        cont = np.array([[maps[(c, d)].window(np.array([0.0]), np.array([1.0 + 1e-9]), oname)[0][0] for c in train] for d in sizes])
        kref = train.index(ref)
        # A
        iA = int(np.argmax(cont.mean(1)))
        # B
        iB, jB = np.unravel_index(np.nanargmax(D[:, :, kref]), D[:, :, kref].shape)
        # C (max-min)
        mn = np.nanmin(D, axis=2)
        iC, jC = np.unravel_index(np.nanargmax(mn), mn.shape)
        kworst = int(np.nanargmin(D[iC, jC]))
        se_best = SE[iC, jC, kworst]
        ties = np.where(mn[iC] >= mn[iC, jC] - 2 * se_best)[0]
        span = (s_grid[ties].max() - s_grid[ties].min()) / (s_grid[-1] - s_grid[0])
        # CVaR (worst 3) reported in all cases
        cvar = np.sort(D, axis=2)[:, :, :3].mean(2)
        iV, jV = np.unravel_index(np.nanargmax(cvar), cvar.shape)
        strat = {
            "A": {"d_um": sizes[iA], "release": "continuous", "train_mean": float(cont[iA].mean()), "train_min": float(cont[iA].min())},
            "B": {"d_um": sizes[iB], "s": float(s_grid[jB]), "w": w, "ref_value": float(D[iB, jB, kref]),
                  "train_mean": float(D[iB, jB].mean()), "train_min": float(D[iB, jB].min())},
            "C": {"d_um": sizes[iC], "s": float(s_grid[jC]), "w": w, "objective_min": float(mn[iC, jC]), "objective_se": float(se_best),
                  "worst_training_condition": train[kworst], "train_mean": float(D[iC, jC].mean()),
                  "tie_set_s_range": [float(s_grid[ties].min()), float(s_grid[ties].max())], "tie_span_fraction": float(span),
                  "degenerate": bool(span > 0.5)},
            "C_cvar_reported": {"d_um": sizes[iV], "s": float(s_grid[jV]), "w": w, "objective_cvar3": float(cvar[iV, jV])},
        }
        frozen["strategies"][oname] = strat
        for i, d in enumerate(sizes):
            for j, s in enumerate(s_grid):
                tables.append({"outcome": oname, "d_um": d, "s": s, "min": mn[i, j], "mean": np.nanmean(D[i, j]),
                               "ref": D[i, j, kref], **{c: D[i, j, k] for k, c in enumerate(train)},
                               **{f"se_{c}": SE[i, j, k] for k, c in enumerate(train)}})
        for i, d in enumerate(sizes):
            tables.append({"outcome": oname, "d_um": d, "s": "continuous", "min": cont[i].min(), "mean": cont[i].mean(),
                           "ref": cont[i, kref], **{c: cont[i, k] for k, c in enumerate(train)}})
    pd.DataFrame(tables).to_csv(OUT / "training_objective_landscape.csv", index=False)
    body = json.dumps(frozen, indent=2, default=float)
    frozen["sha256"] = hashlib.sha256(body.encode()).hexdigest()
    if FROZEN.exists():
        sys.exit(f"{FROZEN} already exists - strategies are frozen; delete it only with a documented reason")
    FROZEN.write_text(json.dumps(frozen, indent=2, default=float))
    print(json.dumps(frozen["strategies"], indent=1, default=float))


def strategy_window(cfg_c, st):
    from lib.breathing import time_at_fraction
    return st


def evaluate(cfg):
    """Direct particle runs (fresh seed) of the frozen strategies on every condition."""
    import copy
    import run_study_v002 as S
    if not FROZEN.exists():
        sys.exit("no frozen strategies - run 'select' first")
    fz = json.loads(FROZEN.read_text())
    reg = load_conditions()
    opt = reg["optimization"]
    jobs = []
    for oname, strats in fz["strategies"].items():
        for meth in ("A", "B", "C"):
            st = strats[meth]
            key = f"{st['d_um']}_{st.get('s', 'cont')}"
            for c in all_conditions(reg):
                case = f"E_{c['id']}_P{st['d_um']:02d}_" + ("CONT" if meth == "A" else f"S{int(round(st['s'] * 1000)):04d}")
                if any(j[2] == case for j in jobs):
                    continue
                jobs.append((c, st, case))
    print(f"{len(jobs)} unique evaluation runs")
    from concurrent.futures import ThreadPoolExecutor

    def run(job):
        c, st, case = job
        k = copy.deepcopy(cfg)
        if "s" in st:
            k["particles"]["release_strategies"]["custom"] = {"F": [st["s"], st["s"] + st["w"]], "short": "CUST"}
            strat = "custom"
        else:
            strat = "continuous"
        return S.particle_job(k, c, c["id"], st["d_um"], strat, opt["eval_parcels"], 1001, case)
    with ThreadPoolExecutor(int(__import__("os").environ.get("AIRWAY_PARTICLE_JOBS", "2"))) as ex:
        list(ex.map(run, jobs))


def report(cfg):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fz = json.loads(FROZEN.read_text())
    reg = load_conditions()
    conds = all_conditions(reg)
    rows = []
    for oname, strats in fz["strategies"].items():
        oc = OUTCOME_SETS[oname]
        for meth in ("A", "B", "C"):
            st = strats[meth]
            for c in conds:
                case = f"E_{c['id']}_P{st['d_um']:02d}_" + ("CONT" if meth == "A" else f"S{int(round(st['s'] * 1000)):04d}")
                d = PC / case
                if not (d / "results.json").exists():
                    rows.append({"outcome": oname, "method": meth, "condition": c["id"], "split": c["split"], "case": case, "status": "missing"})
                    continue
                r = json.loads((d / "results.json").read_text())
                df = add_penetration(parcel_table(d, cfg), d, cfg=cfg)
                y = OUTCOMES[oc](df).values.astype(float)
                w = df.mass.values
                p = (w * y).sum() / w.sum()
                neff = w.sum() ** 2 / (w ** 2).sum()
                rows.append({"outcome": oname, "method": meth, "condition": c["id"], "split": c["split"], "case": case,
                             "status": r["qa_status"], "value": 100 * p, "se": 100 * np.sqrt(p * (1 - p) / neff),
                             "target_wall_dep": r["target_deposition_percent"], "upstream_dep": r["upstream_deposition_percent"],
                             "constriction_dep": r["constriction_deposition_percent"], "total_dep": r["total_deposition_percent"],
                             "escape_target": r["target_outlet_escape_percent"], "escape_comparison": r["comparison_outlet_escape_percent"],
                             "suspended": r["suspended_percent"], "d_um": st["d_um"], "s": st.get("s", "cont")})
    E = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    E.to_csv(OUT / "evaluation_runs.csv", index=False)
    summ = []
    for (oname, split, meth), g in E[E.status == "PASSED"].groupby(["outcome", "split", "method"]):
        summ.append({"outcome": oname, "split": split, "method": meth, "n": len(g), "mean": g.value.mean(), "min": g.value.min(),
                     "sd": g.value.std(ddof=1), "worst_condition": g.loc[g.value.idxmin(), "condition"],
                     "median_se": g.se.median(), "target_wall_dep_mean": g.target_wall_dep.mean(), "upstream_dep_mean": g.upstream_dep.mean(),
                     "suspended_mean": g.suspended.mean()})
    S = pd.DataFrame(summ)
    S.to_csv(OUT / "method_summary.csv", index=False)
    # paired differences on held-out
    pair = []
    for oname in OUTCOME_SETS:
        T = E[(E.outcome == oname) & (E.split == "test") & (E.status == "PASSED")].pivot(index="condition", columns="method", values="value")
        Tse = E[(E.outcome == oname) & (E.split == "test") & (E.status == "PASSED")].pivot(index="condition", columns="method", values="se")
        for a_, b_ in (("C", "B"), ("C", "A"), ("B", "A")):
            if a_ in T and b_ in T:
                dif = T[a_] - T[b_]
                se = np.sqrt(Tse[a_] ** 2 + Tse[b_] ** 2)
                pair.append({"outcome": oname, "comparison": f"{a_}-{b_}", "mean_diff_pts": dif.mean(), "min_diff": dif.min(), "max_diff": dif.max(),
                             "n_positive_beyond_2se": int((dif > 2 * se).sum()), "n_negative_beyond_2se": int((dif < -2 * se).sum()),
                             "n_within_2se": int((dif.abs() <= 2 * se).sum()), "min_of_" + a_: T[a_].min(), "min_of_" + b_: T[b_].min(),
                             "min_gap_pts": T[a_].min() - T[b_].min(),
                             "min_gap_se": float(np.sqrt(Tse.loc[T[a_].idxmin(), a_] ** 2 + Tse.loc[T[b_].idxmin(), b_] ** 2))})
    P = pd.DataFrame(pair)
    P.to_csv(OUT / "heldout_paired_differences.csv", index=False)
    print(S.round(3).to_string()); print(P.round(3).to_string())
    # figure
    fig, axs = plt.subplots(1, 3, figsize=(17, 5), sharey=False)
    for ax, oname in zip(axs, OUTCOME_SETS):
        sub = E[(E.outcome == oname) & (E.status == "PASSED")]
        order = [c["id"] for c in conds]
        x = np.arange(len(order))
        for k, (meth, col) in enumerate((("A", "#6c757d"), ("B", "#f4a261"), ("C", "#2a9d8f"))):
            g = sub[sub.method == meth].set_index("condition").reindex(order)
            st = fz["strategies"][oname][meth]
            lab = f"{meth}: {st['d_um']} µm, " + ("continuous" if meth == "A" else f"s = {st['s']:.3f}")
            ax.errorbar(x + (k - 1) * 0.25, g.value, yerr=2 * g.se, fmt="o", color=col, ms=4, label=lab)
        ax.axvline(8.5, color="k", lw=1); ax.text(4, ax.get_ylim()[1], "training", ha="center", va="bottom", fontsize=8)
        ax.text(12.5, ax.get_ylim()[1], "held-out", ha="center", va="bottom", fontsize=8)
        ax.set_xticks(x); ax.set_xticklabels(order, rotation=90, fontsize=7); ax.grid(alpha=.3)
        ax.set_title(oname + (" (PRIMARY)" if oname == "primary" else " (exploratory)"), fontsize=10)
        ax.set_ylabel("% of introduced aerosol (±2 SE)"); ax.legend(fontsize=7)
    fig.tight_layout(); fig.savefig(OUT / "abc_comparison.png", dpi=130); plt.close(fig)


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["select", "evaluate", "report"])
    a = ap.parse_args()
    {"select": select, "evaluate": evaluate, "report": report}[a.what](cfg)


if __name__ == "__main__":
    main()
