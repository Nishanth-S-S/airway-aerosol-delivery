#!/usr/bin/env python3
"""Diagnosis of the coarse-vs-medium mesh failure (does NOT change any pre-registered pass/fail result).

    python scripts/mesh_diagnose.py

D1  where and for which particles the extra coarse-mesh deposition happens (region, injection radius, size)
D2  delivery among particles that did NOT deposit (is the delivery gap just the spurious deposition?)
D3  release-timing pattern: per-window delivery after removing each mesh's mean (is the timing signal mesh-sensitive?)
D4  jet-region velocity L2 split into lumen core vs near-wall band, at several snapshot times
Writes validation/04_mesh_independence/results/diagnosis.json and mesh_particles.png.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config  # noqa: E402
from lib.response_map import kernel, parcel_table  # noqa: E402
import mesh_compare as MC  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PC = ROOT / "cases" / "particles"
OUT = ROOT / "validation" / "04_mesh_independence" / "results"
LEVELS = [("coarse", "T_N40_SYM"), ("medium", "V_MESH_medium_T_N40_SYM")]
if (PC / "MAP_V_MESH_fine_T_N40_SYM_P03" / "results.json").exists():
    LEVELS.append(("fine", "V_MESH_fine_T_N40_SYM"))


def main():
    cfg = load_config()
    res = {}
    # D1/D2
    rows = []
    for lab, aid in LEVELS:
        for d in (1, 3, 5):
            j = json.loads((PC / f"MAP_{aid}_P{d:02d}" / "results.json").read_text())
            dep = j["total_deposition_percent"]
            rows.append({"mesh": lab, "size_um": d, "delivery": j["target_delivery_percent"], "deposition": dep,
                         "upstream_dep": j["upstream_deposition_percent"], "constriction_dep": j["constriction_deposition_percent"],
                         "target_dep": j["target_deposition_percent"], "suspended": j["suspended_percent"],
                         "delivery_given_not_deposited": 100 * j["target_delivery_percent"] / (100 - dep)})
    T = pd.DataFrame(rows)
    T["other_dep"] = T.deposition - T.upstream_dep - T.constriction_dep - T.target_dep
    res["D1_D2_table"] = T.round(3).to_dict("records")
    # D3 timing pattern (3 um and 5 um, 10 windows)
    res["D3"] = {}
    K = {}
    for d in (1, 3, 5):
        ks = {lab: kernel(parcel_table(PC / f"MAP_{aid}_P{d:02d}", cfg), 10) for lab, aid in LEVELS}
        K[d] = ks
        c, m = ks["coarse"], ks["medium"]
        # last bin (F 0.9-1.0) holds the late-inspiration drop; compare the centred pattern
        cc = c.value_percent - c.value_percent.mean()
        mm = m.value_percent - m.value_percent.mean()
        z = (cc - mm) / np.hypot(c.se_percent, m.se_percent)
        res["D3"][f"{d}um"] = {"mean_offset_pts": float((c.value_percent - m.value_percent).mean()),
                               "centred_bins_within_2se": int((z.abs() <= 2).sum()),
                               "max_abs_centred_diff_pts": float((cc - mm).abs().max()),
                               "corr_bins_1_to_9": float(np.corrcoef(c.value_percent[:9], m.value_percent[:9])[0, 1]),
                               "range_bins_1_to_9_coarse": float(np.ptp(c.value_percent[:9])),
                               "range_bins_1_to_9_medium": float(np.ptp(m.value_percent[:9])),
                               "median_se_pts": float(np.median(np.hypot(c.se_percent, m.se_percent)))}
    # D4 velocity core vs wall band
    g = cfg["geometry"]
    ang = math.radians(g["branch_angle_deg"])
    bif = np.array([g["bifurcation_point_mm"][0], g["bifurcation_point_mm"][2]])
    u_ax = np.array([math.sin(ang), math.cos(ang)]); e1 = np.array([math.cos(ang), -math.sin(ang)])
    gx, gz = np.meshgrid(np.arange(-34, 34, 0.2), np.arange(0, 94, 0.2))
    P = np.c_[gx.ravel(), gz.ravel()]
    from scipy.spatial import cKDTree
    res["D4"] = []
    for t in (0.6, 1.0, 1.4):
        tc, cc_, uc = MC.snapshot(LEVELS[0][1], t)
        tm, cm_, um = MC.snapshot(LEVELS[1][1], t)
        inside = (cKDTree(cc_).query(P)[0] < 0.35) & (cKDTree(cm_).query(P)[0] < 0.25)
        outside_pts = P[~inside]
        wall_dist = cKDTree(outside_pts).query(P)[0]          # distance to nearest grid point outside the lumen
        s = (P - bif) @ u_ax; nn = (P - bif) @ e1
        jet = inside & (s > 10) & (s < 40) & (np.abs(nn) < 3.2)
        out = {"t": float(tm)}
        for name, sel in (("all", jet), ("core_ge_0.6mm", jet & (wall_dist >= 0.6)), ("wallband_lt_0.6mm", jet & (wall_dist < 0.6))):
            Uc, Um = MC.sample(cc_, uc, P[sel]), MC.sample(cm_, um, P[sel])
            l2, n = MC.l2rel(Uc, Um)
            out[name] = {"l2_rel_percent": 100 * l2, "n": int(n)}
        res["D4"].append(out)
    (OUT / "diagnosis.json").write_text(json.dumps(res, indent=2, default=float))
    print(T.round(2).to_string(index=False))
    print(json.dumps({k: res[k] for k in ("D3", "D4")}, indent=1, default=float))

    # figure: delivery, deposition by region, timing pattern
    fig, axs = plt.subplots(1, 3, figsize=(17, 5))
    cols = {"coarse": "#e76f51", "medium": "#264653", "fine": "#2a9d8f"}
    x = np.arange(3); w = 0.8 / len(LEVELS)
    for i, (lab, _) in enumerate(LEVELS):
        s = T[T.mesh == lab]
        axs[0].bar(x + i * w, s.delivery, w, color=cols[lab], label=f"{lab} delivery")
        axs[0].bar(x + i * w, s.delivery_given_not_deposited - s.delivery, w, bottom=s.delivery, color=cols[lab], alpha=0.3)
    axs[0].set_xticks(x + w * (len(LEVELS) - 1) / 2, ["1 µm", "3 µm", "5 µm"]); axs[0].set_ylim(30, 40)
    axs[0].set_ylabel("target delivery (% of released mass)")
    axs[0].set_title("C5 delivery (solid) and delivery among\nnon-deposited particles (light top)"); axs[0].legend(fontsize=8)
    bottom = np.zeros(len(T))
    lbl = [f"{r.mesh[0].upper()} {r.size_um}" for r in T.itertuples()]
    for k, c in (("upstream_dep", "#8d99ae"), ("constriction_dep", "#e9c46a"), ("target_dep", "#f4a261"), ("other_dep", "#2b2d42")):
        axs[1].bar(np.arange(len(T)), T[k], bottom=bottom, color=c, label=k.replace("_dep", ""))
        bottom += T[k].values
    axs[1].set_xticks(np.arange(len(T)), lbl); axs[1].set_ylabel("wall deposition (% of released mass)")
    axs[1].set_title("C6 deposition by region (C = coarse, M = medium, µm)"); axs[1].legend(fontsize=8)
    for lab, _ in LEVELS:
        k = K[3][lab]
        axs[2].errorbar(k.index if "F_mid" not in k else k.F_mid, k.value_percent, yerr=2 * k.se_percent, fmt="o-", ms=4,
                        color=cols[lab], label=f"{lab} (±2 SE)", capsize=2)
    axs[2].set_xlabel("release window (inspired-volume fraction bin)"); axs[2].set_ylabel("delivery of mass released in bin (%)")
    axs[2].set_title("C7 release-timing kernel, 3 µm"); axs[2].legend(fontsize=8); axs[2].grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(OUT / "mesh_particles.png", dpi=130); plt.close(fig)


if __name__ == "__main__":
    main()
