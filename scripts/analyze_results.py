#!/usr/bin/env python3
"""Study-level analysis of results/results.csv (answers the research question).

    python scripts/analyze_results.py

Writes results/figures/analysis/*.png and results/tables/analysis_*.csv:
  * target delivery heat maps (release x size) for every geometry x waveform
  * delivery vs particle size per release strategy
  * best release strategy per (geometry, size) and how stable it is across waveforms
  * where the aerosol ends up (deposition / escape breakdown)
  * delivery normalised by the target branch's share of the airflow
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

FIG = ROOT / "results" / "figures" / "analysis"
TAB = ROOT / "results" / "tables"
REL_ORDER = ["continuous", "early", "middle", "late"]
REL_COL = {"continuous": "#6c757d", "early": "#f4a261", "middle": "#2a9d8f", "late": "#264653"}
WAVE_ORDER = ["early", "symmetric", "late"]
GEOM = {0: "Healthy", 20: "20 % narrowing", 40: "40 % narrowing"}


def main():
    cfg = load_config()
    FIG.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(ROOT / "results" / "results.csv")
    df = df[df.qa_status == "PASSED"].copy()
    if df.empty:
        print("no QA-passed cases"); return
    df["release_strategy"] = pd.Categorical(df.release_strategy, REL_ORDER, ordered=True)
    df["waveform"] = pd.Categorical(df.waveform, WAVE_ORDER, ordered=True)
    df["delivery_per_ventilation"] = df.target_delivery_percent / df.target_branch_ventilation_percent
    sizes = sorted(df.particle_size_um.unique())
    summary = {"n_cases": int(len(df))}

    # ---------------- 1 heat maps
    vmin, vmax = df.target_delivery_percent.min(), df.target_delivery_percent.max()
    fig, axs = plt.subplots(3, 3, figsize=(13, 10.5), sharex=True, sharey=True)
    for i, npct in enumerate([0, 20, 40]):
        for j, w in enumerate(WAVE_ORDER):
            ax = axs[i, j]
            sub = df[(df.narrowing_percent == npct) & (df.waveform == w)]
            M = sub.pivot_table(index="release_strategy", columns="particle_size_um", values="target_delivery_percent",
                                observed=False).reindex(index=REL_ORDER, columns=sizes)
            im = ax.imshow(M.values, cmap="viridis", vmin=vmin, vmax=vmax, aspect="auto")
            for (r, c), v in np.ndenumerate(M.values):
                if np.isfinite(v):
                    ax.text(c, r, f"{v:.1f}", ha="center", va="center", fontsize=9,
                            color="white" if v < (vmin + vmax) / 2 else "black")
            ax.set_xticks(range(len(sizes))); ax.set_xticklabels([f"{s:g} µm" for s in sizes])
            ax.set_yticks(range(4)); ax.set_yticklabels(REL_ORDER)
            if i == 0:
                ax.set_title(f"{w} breathing", fontsize=11)
            if j == 0:
                ax.set_ylabel(f"{GEOM[npct]}\nrelease", fontsize=10)
    fig.colorbar(im, ax=axs, shrink=0.6, label="target delivery (% of introduced aerosol)")
    fig.suptitle("Target delivery for every case (QA-passed only)", fontsize=13)
    fig.savefig(FIG / "delivery_heatmaps.png", dpi=130, bbox_inches="tight"); plt.close(fig)

    # ---------------- 2 delivery vs size, per release, per geometry (band = range over waveforms)
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.6), sharey=True)
    for ax, npct in zip(axs, [0, 20, 40]):
        sub = df[df.narrowing_percent == npct]
        for rel in REL_ORDER:
            s = sub[sub.release_strategy == rel].groupby("particle_size_um").target_delivery_percent
            if s.size().sum() == 0:
                continue
            m, lo, hi = s.mean(), s.min(), s.max()
            ax.plot(m.index, m.values, "o-", color=REL_COL[rel], lw=2, label=rel)
            ax.fill_between(m.index, lo.values, hi.values, color=REL_COL[rel], alpha=0.15)
        ax.set_title(GEOM[npct]); ax.set_xlabel("particle diameter (µm)"); ax.set_xticks(sizes); ax.grid(alpha=.3)
    axs[0].set_ylabel("target delivery (%)\nline = mean over 3 waveforms, band = range")
    axs[0].legend(title="release", fontsize=8)
    fig.suptitle("How particle size and release timing change target delivery", fontsize=12)
    fig.tight_layout(); fig.savefig(FIG / "delivery_vs_size.png", dpi=130); plt.close(fig)

    # ---------------- 3 best strategy and robustness across waveforms
    rows = []
    for (npct, d), g in df.groupby(["narrowing_percent", "particle_size_um"]):
        per_w = {}
        for w, gw in g.groupby("waveform", observed=True):
            if len(gw) == 0:
                continue
            best = gw.loc[gw.target_delivery_percent.idxmax()]
            per_w[w] = (str(best.release_strategy), float(best.target_delivery_percent))
        mean_by_rel = g.groupby("release_strategy", observed=True).target_delivery_percent.mean()
        worst_by_rel = g.groupby("release_strategy", observed=True).target_delivery_percent.min()
        overall = mean_by_rel.idxmax() if len(mean_by_rel) else None
        rows.append({"narrowing_percent": npct, "particle_size_um": d, "best_overall_release": overall,
                     "best_overall_mean_delivery": mean_by_rel.max() if len(mean_by_rel) else np.nan,
                     "best_overall_worst_waveform_delivery": worst_by_rel.get(overall, np.nan),
                     **{f"best_{w}": per_w.get(w, ("", np.nan))[0] for w in WAVE_ORDER},
                     "same_best_for_all_waveforms": len({v[0] for v in per_w.values()}) == 1 and len(per_w) == 3,
                     "delivery_spread_across_releases_points": (mean_by_rel.max() - mean_by_rel.min()) if len(mean_by_rel) else np.nan})
    best = pd.DataFrame(rows)
    best.to_csv(TAB / "analysis_best_strategy.csv", index=False)
    summary["best_strategy_table"] = best.to_dict("records")

    # ---------------- 4 where the aerosol goes (3 um, symmetric, each release)
    comp = ["upstream_deposition_percent", "constriction_deposition_percent", "target_deposition_percent",
            "comparison_branch_deposition_percent", "target_outlet_escape_percent", "comparison_outlet_escape_percent",
            "suspended_percent"]
    names = ["deposit: upstream", "deposit: constriction", "deposit: target", "deposit: comparison",
             "escaped: target outlet", "escaped: comparison outlet", "still airborne"]
    cols = ["#8d99ae", "#f4a261", "#e76f51", "#457b9d", "#c1440e", "#1d3557", "#7209b7"]
    fig, axs = plt.subplots(1, len(sizes), figsize=(4.2 * len(sizes), 4.8), sharey=True)
    for ax, d in zip(np.atleast_1d(axs), sizes):
        sub = df[(df.particle_size_um == d) & (df.waveform == "symmetric")].sort_values(["narrowing_percent", "release_strategy"])
        labels = [f"{GEOM[r.narrowing_percent].split()[0]} {r.release_strategy[:4]}" for r in sub.itertuples()]
        bottom = np.zeros(len(sub))
        for c, n_, col in zip(comp, names, cols):
            ax.bar(range(len(sub)), sub[c].values, bottom=bottom, color=col, label=n_)
            bottom += sub[c].values
        ax.set_xticks(range(len(sub))); ax.set_xticklabels(labels, rotation=90, fontsize=7)
        ax.set_title(f"{d:g} µm, symmetric breathing")
    np.atleast_1d(axs)[0].set_ylabel("% of introduced aerosol")
    np.atleast_1d(axs)[-1].legend(fontsize=7, loc="lower right")
    fig.tight_layout(); fig.savefig(FIG / "aerosol_fate.png", dpi=130); plt.close(fig)

    # ---------------- 5 normalised by ventilation
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    for npct, mk in zip([0, 20, 40], ["o", "s", "^"]):
        sub = df[df.narrowing_percent == npct].groupby("particle_size_um").delivery_per_ventilation.mean()
        ax.plot(sub.index, sub.values, mk + "-", lw=2, label=GEOM[npct])
    ax.axhline(1, color="grey", ls=":", lw=1)
    ax.set_xlabel("particle diameter (µm)"); ax.set_ylabel("target delivery / target-branch airflow share")
    ax.set_title("Is the aerosol just following the air?\n(1 = delivered in proportion to ventilation; mean over releases & waveforms)", fontsize=10)
    ax.set_xticks(sizes); ax.legend(); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(FIG / "delivery_per_ventilation.png", dpi=130); plt.close(fig)

    # ---------------- headline numbers
    by_geom = df.groupby("narrowing_percent").agg(mean_delivery=("target_delivery_percent", "mean"),
                                                   min_delivery=("target_delivery_percent", "min"),
                                                   max_delivery=("target_delivery_percent", "max"),
                                                   target_vent=("target_branch_ventilation_percent", "mean"),
                                                   deposition=("total_deposition_percent", "mean"),
                                                   suspended=("suspended_percent", "mean"))
    by_geom.to_csv(TAB / "analysis_by_geometry.csv")
    summary["by_geometry"] = by_geom.reset_index().to_dict("records")
    rel_effect = df.groupby(["narrowing_percent", "release_strategy"], observed=True).target_delivery_percent.mean().unstack()
    rel_effect.to_csv(TAB / "analysis_release_effect.csv")
    summary["release_effect"] = rel_effect.reset_index().to_dict("records")
    summary["max_abs_mass_balance_error_percent"] = float(df.mass_balance_error_percent.abs().max())
    (TAB / "analysis_summary.json").write_text(json.dumps(summary, indent=2, default=float))
    print(by_geom.round(2).to_string()); print(rel_effect.round(2).to_string())
    print(best[["narrowing_percent", "particle_size_um", "best_overall_release", "best_early", "best_symmetric", "best_late",
                "same_best_for_all_waveforms", "delivery_spread_across_releases_points"]].to_string(index=False))
    print(f"[ok] {len(df)} QA-passed cases analysed -> results/figures/analysis/, results/tables/analysis_*")


if __name__ == "__main__":
    main()
