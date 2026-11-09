#!/usr/bin/env python3
"""Test the release-time response map against independent direct pulse simulations, and
characterise the timing effect (docs/TIMING_FEASIBILITY.md).

    python scripts/response_map_check.py --cases archive/v001/cases/particles --tag v001
    python scripts/response_map_check.py --cases cases/particles --tag v002 --map-prefix MAP_

For each continuous-release run, the map predicts the early/middle/late pulse outcomes; the direct
pulse runs of the same (size, geometry, waveform) are the independent check. If superposition is exact,
z = (direct - map) / sqrt(se_map^2 + se_direct^2) should look like N(0, 1).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config  # noqa: E402
from lib.response_map import OUTCOMES, kernel, parcel_table, window_estimate  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def direct_se(r: dict) -> float:
    p = r["target_delivery_percent"] / 100
    return 100 * np.sqrt(p * (1 - p) / max(r["n_parcels"], 1))


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default="archive/v001/cases/particles")
    ap.add_argument("--tag", default="v001")
    a = ap.parse_args()
    base = ROOT / a.cases
    out = ROOT / "results" / "figures" / "response_map" / a.tag
    out.mkdir(parents=True, exist_ok=True)
    tab = ROOT / "results" / "tables"
    rels = cfg["particles"]["release_strategies"]
    rows, kern, transit = [], [], []
    for cont in sorted(base.glob("P*_CONT_*")):
        try:
            df = parcel_table(cont, cfg)
        except Exception as e:
            print(f"  skip {cont.name}: {e}")
            continue
        meta = json.loads((cont / "case_meta.json").read_text())
        tt = (df.t_cross - df.t_inject).dropna()
        transit.append({"case": cont.name, "size_um": meta["particle_size_um"], "geometry": meta["geometry"],
                        "waveform": meta["waveform"], "transit_median_ms": 1e3 * tt.median(),
                        "transit_p90_ms": 1e3 * tt.quantile(0.9)})
        for oc in ("target_delivery", "suspended", "upstream_deposition", "target_deposition", "constriction_deposition"):
            k = kernel(df, 20, oc)
            k["case"], k["outcome"] = cont.name, oc
            k["size_um"], k["geometry"], k["waveform"] = meta["particle_size_um"], meta["geometry"], meta["waveform"]
            kern.append(k)
        for strat, spec in rels.items():
            if strat == "continuous":
                continue
            dname = cont.name.replace("_CONT_", f"_{spec['short']}_")
            rf = base / dname / "results.json"
            if not rf.exists():
                continue
            r = json.loads(rf.read_text())
            F0, F1 = spec["F"]
            est, se, n = window_estimate(df, F0, F1)
            rows.append({"direct_case": dname, "size_um": meta["particle_size_um"], "geometry": meta["geometry"],
                         "waveform": meta["waveform"], "strategy": strat, "map_percent": est, "map_se": se, "map_n": n,
                         "direct_percent": r["target_delivery_percent"], "direct_se": direct_se(r)})
    res = pd.DataFrame(rows)
    res["diff"] = res.direct_percent - res.map_percent
    res["z"] = res["diff"] / np.sqrt(res.map_se ** 2 + res.direct_se ** 2)
    res.to_csv(tab / f"response_map_check_{a.tag}.csv", index=False)
    K = pd.concat(kern)
    K.to_csv(tab / f"release_time_kernels_{a.tag}.csv", index=False)
    T = pd.DataFrame(transit)
    T.to_csv(tab / f"transit_times_{a.tag}.csv", index=False)
    summ = {"n_pairs": int(len(res)), "mean_diff_pts": float(res["diff"].mean()), "rms_diff_pts": float(np.sqrt((res["diff"] ** 2).mean())),
            "mean_abs_diff_pts": float(res["diff"].abs().mean()), "mean_z": float(res.z.mean()), "sd_z": float(res.z.std()),
            "frac_abs_z_lt_2": float((res.z.abs() < 2).mean()), "median_map_se": float(res.map_se.median()),
            "median_direct_se": float(res.direct_se.median()),
            "transit_median_ms_range": [float(T.transit_median_ms.min()), float(T.transit_median_ms.max())],
            "transit_p90_ms_range": [float(T.transit_p90_ms.min()), float(T.transit_p90_ms.max())]}
    (tab / f"response_map_check_{a.tag}.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps(summ, indent=1))

    # ---- figure 1: map vs direct
    fig, axs = plt.subplots(1, 2, figsize=(12, 5))
    ax = axs[0]
    cols = {"early": "#f4a261", "middle": "#2a9d8f", "late": "#264653"}
    for s, g in res.groupby("strategy"):
        ax.errorbar(g.map_percent, g.direct_percent, xerr=2 * g.map_se, yerr=2 * g.direct_se, fmt="o", ms=4, alpha=0.8,
                    color=cols.get(s, "k"), label=s, elinewidth=0.6)
    lo, hi = res[["map_percent", "direct_percent"]].min().min() - 2, res[["map_percent", "direct_percent"]].max().max() + 2
    ax.plot([lo, hi], [lo, hi], "k--", lw=1)
    ax.set_xlabel("predicted from continuous-release map (%)"); ax.set_ylabel("direct pulse simulation (%)")
    ax.set_title(f"Response map vs direct runs ({a.tag}, n = {len(res)})\nbars = ±2 SE (Monte Carlo)"); ax.legend(); ax.grid(alpha=.3)
    ax = axs[1]
    ax.hist(res.z, bins=20, density=True, color="#8d99ae", alpha=0.8, label="observed z")
    zz = np.linspace(-4, 4, 200); ax.plot(zz, np.exp(-zz ** 2 / 2) / np.sqrt(2 * np.pi), "k-", label="N(0,1) if superposition is exact")
    ax.set_xlabel("z = (direct − map) / combined SE"); ax.set_title(f"mean z {summ['mean_z']:.2f}, SD {summ['sd_z']:.2f}, |z|<2: {100 * summ['frac_abs_z_lt_2']:.0f} %")
    ax.legend(fontsize=8); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(out / "map_vs_direct.png", dpi=130); plt.close(fig)

    # ---- figure 2: release-time kernels (symmetric breathing)
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.4), sharey=True)
    for ax, geo in zip(axs, ["healthy", "n20", "n40"]):
        for d, col in zip(sorted(K.size_um.unique()), ["#1d3557", "#457b9d", "#2a9d8f", "#e76f51"]):
            k = K[(K.geometry == geo) & (K.waveform == "symmetric") & (K.size_um == d) & (K.outcome == "target_delivery")]
            if len(k):
                ax.errorbar(k.F_mid, k.value_percent, yerr=k.se_percent, fmt="o-", ms=3, color=col, label=f"{d:g} µm", lw=1.2)
        ks = K[(K.geometry == geo) & (K.waveform == "symmetric") & (K.outcome == "suspended")].groupby("F_mid").value_percent.mean()
        ax.plot(ks.index, ks.values, ":", color="#7209b7", lw=2, label="still airborne at 3 s (mean)")
        for sname, spec in rels.items():
            if sname != "continuous":
                ax.axvspan(*spec["F"], color=cols[sname], alpha=0.12)
        ax.set_title(f"{geo}, symmetric breathing"); ax.set_xlabel("release point F (fraction of inspired volume)"); ax.grid(alpha=.3)
    axs[0].set_ylabel("% of aerosol released at F that\nreaches the target plane"); axs[0].legend(fontsize=7)
    fig.suptitle(f"Release-time response curves G(F) ({a.tag}); shaded = early/middle/late windows", fontsize=11)
    fig.tight_layout(); fig.savefig(out / "release_time_kernels.png", dpi=130); plt.close(fig)
    print(f"[ok] results/figures/response_map/{a.tag}/, results/tables/response_map_check_{a.tag}.*")


if __name__ == "__main__":
    main()
