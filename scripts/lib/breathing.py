"""Breathing waveforms (normalised Beta shapes) and inspired-volume release windows.

Flow during inhalation (0 <= t <= T):
    Q(t) = V_total * f_beta(t/T; a, b) / T
where f_beta is the Beta probability density, so that

    integral_0^T Q dt = V_total = Q_mean * T     for EVERY waveform  (equal inspired volume)

Inspired-volume fraction:
    F(t) = V(t) / V_total = I_{t/T}(a, b)         (regularised incomplete Beta = Beta CDF)

Release windows are specified in F, and converted to clock time with the inverse
CDF:  t(F) = T * I^{-1}_F(a, b).  So "30 % of inspired volume" is reached at a
different clock time for early- vs late-peaking breathing.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

LPM_TO_M3S = 1e-3 / 60.0


def waveform(cfg: dict, name: str, n: int | None = None):
    """Return (t [s], Q [m3/s]) sampled over the inhalation for waveform `name`."""
    b = cfg["breathing"]
    T = b["inhalation_duration_s"]
    w = b["waveforms"][name]
    n = n or b["waveform_points"]
    v_total = b["mean_flow_L_per_min"] * LPM_TO_M3S * T
    t = np.linspace(0.0, T, n)
    q = v_total * stats.beta.pdf(t / T, w["a"], w["b"]) / T
    return t, q


def inspired_volume_total(cfg: dict) -> float:
    b = cfg["breathing"]
    return b["mean_flow_L_per_min"] * LPM_TO_M3S * b["inhalation_duration_s"]


def fraction_inspired(cfg: dict, name: str, t):
    b = cfg["breathing"]
    w = b["waveforms"][name]
    return stats.beta.cdf(np.clip(np.asarray(t) / b["inhalation_duration_s"], 0, 1), w["a"], w["b"])


def time_at_fraction(cfg: dict, name: str, F):
    """Clock time (s) at which a fraction F of the total inspired volume has entered."""
    b = cfg["breathing"]
    w = b["waveforms"][name]
    return b["inhalation_duration_s"] * stats.beta.ppf(np.asarray(F, float), w["a"], w["b"])


def release_window(cfg: dict, waveform_name: str, strategy: str) -> dict:
    F0, F1 = cfg["particles"]["release_strategies"][strategy]["F"]
    t0, t1 = (float(x) for x in time_at_fraction(cfg, waveform_name, [F0, F1]))
    vt = inspired_volume_total(cfg)
    return {"waveform": waveform_name, "strategy": strategy, "F_start": F0, "F_end": F1,
            "t_start_s": t0, "t_end_s": t1, "duration_s": t1 - t0,
            "window_volume_m3": (F1 - F0) * vt}


def peak_flow(cfg: dict, name: str) -> float:
    t, q = waveform(cfg, name, 4001)
    return float(q.max())
