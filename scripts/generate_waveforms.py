#!/usr/bin/env python3
"""Phases 4 & 9: breathing waveforms and inspired-volume-based release windows.

    python scripts/generate_waveforms.py

Writes
    waveforms/early.csv, symmetric.csv, late.csv     time_s, flow_L_per_min, flow_m3_per_s, cumulative fraction F
    waveforms/release_windows.csv                    clock-time windows for every waveform x strategy
    results/figures/breathing_waveforms.png
    results/figures/release_windows.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.breathing import (LPM_TO_M3S, fraction_inspired, inspired_volume_total, release_window,  # noqa: E402
                           waveform)
from lib.common import ROOT, load_config, rel  # noqa: E402

COLORS = {"early": "#e76f51", "symmetric": "#2a9d8f", "late": "#264653"}
WIN_COLORS = {"early": "#f4a261", "middle": "#90be6d", "late": "#577590"}


def main() -> None:
    cfg = load_config()
    b = cfg["breathing"]
    T = b["inhalation_duration_s"]
    wdir = ROOT / "waveforms"
    wdir.mkdir(exist_ok=True)
    vt = inspired_volume_total(cfg)

    rows = []
    curves = {}
    for name in b["waveforms"]:
        t, q = waveform(cfg, name)
        F = fraction_inspired(cfg, name, t)
        df = pd.DataFrame({"time_s": t, "flow_L_per_min": q / LPM_TO_M3S, "flow_m3_per_s": q,
                           "inspired_fraction_F": F})
        df.to_csv(wdir / f"{name}.csv", index=False, float_format="%.8g")
        vol = np.trapz(q, t)
        curves[name] = (t, q, F)
        print(f"[ok] {rel(wdir / (name + '.csv'))}: volume {vol * 1e6:.3f} mL "
              f"(target {vt * 1e6:.3f} mL, err {100 * (vol - vt) / vt:+.4f} %), peak {q.max() / LPM_TO_M3S:.2f} L/min "
              f"at t={t[q.argmax()]:.3f} s")
        for strat in cfg["particles"]["release_strategies"]:
            rows.append(release_window(cfg, name, strat))
    rw = pd.DataFrame(rows)
    rw.to_csv(wdir / "release_windows.csv", index=False, float_format="%.6f")
    print(f"[ok] {rel(wdir / 'release_windows.csv')}")
    print(rw.pivot(index="strategy", columns="waveform", values="t_start_s").round(3).to_string())

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # ---- waveforms together
    fig, ax = plt.subplots(figsize=(8, 4.5))
    post = b["post_inhalation_s"]
    for name, (t, q, F) in curves.items():
        tt = np.concatenate([t, [T + 1e-6, T + post]])
        qq = np.concatenate([q, [0, 0]]) / LPM_TO_M3S
        ax.plot(tt, qq, color=COLORS[name], lw=2.2, label=b["waveforms"][name]["label"])
    ax.axhline(b["mean_flow_L_per_min"], color="grey", ls=":", lw=1, label=f"mean {b['mean_flow_L_per_min']} L/min")
    ax.axvspan(T, T + post, color="grey", alpha=0.08, label="post-inhalation (zero inlet flow)")
    ax.set_xlabel("time (s)"); ax.set_ylabel("inlet flow rate (L/min)")
    ax.set_title(f"Breathing waveforms — equal inspired volume {vt * 1e6:.1f} mL over {T:g} s")
    ax.legend(fontsize=8); ax.grid(alpha=0.3); ax.set_xlim(0, T + post); ax.set_ylim(bottom=0)
    fig.tight_layout()
    out = ROOT / "results" / "figures" / "breathing_waveforms.png"
    fig.savefig(out, dpi=140); plt.close(fig)
    print(f"[ok] {rel(out)}")

    # ---- release windows per waveform
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), sharey=True)
    for ax, (name, (t, q, F)) in zip(axes, curves.items()):
        ax.plot(t, q / LPM_TO_M3S, color=COLORS[name], lw=2.2, label="flow rate (L/min)")
        ax2 = ax.twinx()
        ax2.plot(t, F, color="k", lw=1.4, ls="--", label="cumulative inspired fraction F")
        ax2.set_ylim(0, 1.02)
        if name == "late":
            ax2.set_ylabel("inspired volume fraction F")
        else:
            ax2.set_yticklabels([])
        for strat in ("early", "middle", "late"):
            w = rw[(rw.waveform == name) & (rw.strategy == strat)].iloc[0]
            ax.axvspan(w.t_start_s, w.t_end_s, color=WIN_COLORS[strat], alpha=0.35,
                       label=f"{strat} pulse F={w.F_start:.1f}-{w.F_end:.1f}: {w.t_start_s:.3f}-{w.t_end_s:.3f} s")
            for Fv, tv in ((w.F_start, w.t_start_s), (w.F_end, w.t_end_s)):
                ax2.plot([tv], [Fv], "o", color=WIN_COLORS[strat], ms=4)
        ax.set_title(b["waveforms"][name]["label"])
        ax.set_xlabel("time (s)"); ax.set_xlim(0, T); ax.grid(alpha=0.3)
        h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, fontsize=7, loc="upper left" if name != "early" else "upper right")
    axes[0].set_ylabel("inlet flow rate (L/min)")
    fig.suptitle("Release windows are defined by inspired-volume fraction F, not clock time", fontsize=12)
    fig.tight_layout()
    out = ROOT / "results" / "figures" / "release_windows.png"
    fig.savefig(out, dpi=140); plt.close(fig)
    print(f"[ok] {rel(out)}")


if __name__ == "__main__":
    main()
