"""Release-time response map ("transfer kernel") from a continuous-release particle run.

Model assumptions that make superposition exact (in expectation)
----------------------------------------------------------------
1. One-way coupling: the air velocity u(x,t) does not depend on the aerosol.
2. No particle-particle interaction (no collisions, coagulation, evaporation, charge).
3. Each physical particle obeys the same deterministic equation of motion (drag + gravity);
   no Brownian / turbulent dispersion terms.
4. Release is flow-proportional: the aerosol mass released between F and F+dF is m(F) dF,
   with each parcel's position drawn from the same inlet distribution (area-random positions,
   flux-weighted masses).

Under 1-3 the fate of a particle depends only on (release time t0, release position x0) and the
fixed airflow, so the delivered mass of ANY schedule m(F) is

    M_target = integral m(F) G(F) dF,   G(F) = E_x0[ 1{particle released at F reaches target} ]

i.e. delivery is LINEAR in the release schedule. For a pulse of equal total mass on [s, s+w]:

    D(s, w) = (1/w) integral_s^{s+w} G(F) dF.

G(F) is estimated by Monte Carlo from a continuous run (F = 0..1): parcels released in a bin of F,
mass-weighted fraction that crossed the target plane. The estimator for a window is the mass-weighted
mean outcome of the continuous-run parcels whose release F lies in the window. Its only errors are
(a) Monte Carlo sampling noise and (b) window-edge discretisation by the cloud time step.

Parcel release times are recovered exactly: OpenFOAM numbers parcels 0,1,2,... in injection order
(serial run) and massBudget.csv logs the cumulative parcel count n_injected at every step, so parcel k
was injected in the first step where n_injected > k. (airwayParcelFoam >= v2 also writes injections.csv.)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .breathing import fraction_inspired
from .postproc import classify_region


def parcel_table(case_dir: Path, cfg: dict) -> pd.DataFrame:
    """One row per parcel: origId, t_inject, F_inject, mass, fate, region, t_cross."""
    case_dir = Path(case_dir)
    pp = case_dir / "postProcessing" / "airwayParcels"
    meta = json.loads((case_dir / "case_meta.json").read_text())
    inj_file = pp / "injections.csv"
    if inj_file.exists():
        inj = pd.read_csv(inj_file)[["origId", "time", "mass"]].rename(columns={"time": "t_inject"})
    else:
        mb = pd.read_csv(pp / "massBudget.csv")
        n = mb.n_injected.values
        t = mb.time.values
        dt = np.diff(np.r_[0.0, t])
        ids = np.arange(int(n[-1]))
        step = np.searchsorted(n, ids, side="right")          # first step with n_injected > id
        inj = pd.DataFrame({"origId": ids, "t_inject": t[step] - 0.5 * dt[step]})   # mid-step
        inj["mass"] = np.nan
    fin = pd.read_csv(pp / "finalParcels.csv")
    esc = pd.read_csv(pp / "escapes.csv")
    cr = pd.read_csv(pp / "targetPlaneCrossings.csv")
    mass = pd.concat([fin[["origId", "mass"]], esc[["origId", "mass"]]]).drop_duplicates("origId").set_index("origId").mass
    df = inj.set_index("origId")
    df["mass"] = mass.reindex(df.index)
    df["fate"] = "unknown"
    df.loc[fin.origId[fin.active == 1], "fate"] = "suspended"
    dep = fin[fin.active == 0]
    df.loc[dep.origId, "fate"] = "deposited"
    df["region"] = ""
    if len(dep):
        df.loc[dep.origId, "region"] = classify_region(dep[["x", "y", "z"]].values, cfg)
    df.loc[esc.origId, "fate"] = "escaped_" + esc.set_index("origId").boundary.reindex(esc.origId).values
    df["crossed"] = False
    df.loc[cr.origId, "crossed"] = True
    df["t_cross"] = np.nan
    df.loc[cr.origId, "t_cross"] = cr.time.values
    for c in ("x", "y", "z"):
        df[f"cross_{c}"] = np.nan
        df.loc[cr.origId, f"cross_{c}"] = cr[c].values
    wave = meta["waveform"]
    if wave not in cfg["breathing"]["waveforms"] and wave.startswith("beta"):
        import copy
        cfg = copy.deepcopy(cfg)          # condition waveforms are named beta<a><b>; F depends only on the shape
        cfg["breathing"]["waveforms"][wave] = {"a": int(wave[4]), "b": int(wave[5])}
    df["F_inject"] = fraction_inspired(cfg, wave, df.t_inject.values)
    df = df.reset_index()
    if df.mass.isna().any():
        raise ValueError(f"{case_dir.name}: {df.mass.isna().sum()} parcels without mass/fate")
    return df


OUTCOMES = {
    "target_delivery": lambda d: d.crossed,
    "target_deposition": lambda d: (d.fate == "deposited") & (d.region == "target"),
    "upstream_deposition": lambda d: (d.fate == "deposited") & (d.region == "upstream"),
    "constriction_deposition": lambda d: (d.fate == "deposited") & (d.region == "constriction"),
    "comparison_deposition": lambda d: (d.fate == "deposited") & (d.region == "comparison"),
    "target_escape": lambda d: d.fate == "escaped_targetOutlet",
    "comparison_escape": lambda d: d.fate == "escaped_comparisonOutlet",
    "suspended": lambda d: d.fate == "suspended",
}


def window_estimate(df: pd.DataFrame, F0: float, F1: float, outcome: str = "target_delivery") -> tuple[float, float, int]:
    """Mass-weighted % of the parcels released in [F0, F1) with the outcome; returns (value, std. error, n)."""
    sel = df[(df.F_inject >= F0) & (df.F_inject < F1)]
    if sel.empty:
        return float("nan"), float("nan"), 0
    w = sel.mass.values
    y = OUTCOMES[outcome](sel).values.astype(float)
    p = np.sum(w * y) / np.sum(w)
    # ratio-estimator standard error (weighted Bernoulli)
    n_eff = np.sum(w) ** 2 / np.sum(w ** 2)
    se = np.sqrt(max(p * (1 - p), 0) / n_eff)
    return 100 * p, 100 * se, len(sel)


def kernel(df: pd.DataFrame, bins: int = 40, outcome: str = "target_delivery") -> pd.DataFrame:
    edges = np.linspace(0, 1, bins + 1)
    rows = []
    for a, b in zip(edges[:-1], edges[1:]):
        v, se, n = window_estimate(df, a, b if b < 1 else 1.0000001, outcome)
        rows.append({"F_mid": 0.5 * (a + b), "value_percent": v, "se_percent": se, "n": n})
    return pd.DataFrame(rows)


def add_penetration(df: pd.DataFrame, case_dir: Path, volumes_mL=(5, 10, 20), T_insp: float = 2.0,
                    cfg: dict | None = None) -> pd.DataFrame:
    """Secondary outcome (docs/PENETRATION_OUTCOME.md).

    V_after(t_c) = air volume entering the target branch between the parcel's first plane crossing t_c and the end
    of inhalation (from the CFD flow through the target outlet).
      plug       : penetrates V  <=>  V_after >= V                     (pre-declared definition)
      poiseuille : penetrates V  <=>  2 (1 - r^2/R^2) V_after >= V      (sensitivity: parcel follows the streamline at
                   its crossing radius r in a fully developed laminar tube of radius R = 3 mm)
    Both: no deposition, branching or breath-hold downstream; nothing moves after inhalation ends."""
    from .common import load_config
    from .foam_case import target_plane
    from .postproc import airflow_timeseries
    cfg = cfg or load_config()
    meta = json.loads((Path(case_dir) / "case_meta.json").read_text())
    af = Path(case_dir).parent.parent / "airflow" / meta["airflow_case"]
    ts = airflow_timeseries(af)
    t = ts.time.values
    q = np.clip(ts.Q_target.values, 0, None)
    q[t > T_insp] = 0.0
    cumV = np.concatenate([[0], np.cumsum(0.5 * (q[1:] + q[:-1]) * np.diff(t))]) * 1e6   # mL
    V_end = cumV[-1]
    v_after = V_end - np.interp(df.t_cross.fillna(np.inf).clip(upper=t[-1]).values, t, cumV)
    p0, n, _ = target_plane(cfg)
    R = cfg["geometry"]["daughter_diameter_mm"] / 2e3
    X = df[["cross_x", "cross_y", "cross_z"]].values - p0
    rr = np.linalg.norm(X - np.outer(X @ n, n), axis=1)
    shape = np.clip(2 * (1 - (rr / R) ** 2), 0, None)
    df["v_after_mL"] = v_after
    for V in volumes_mL:
        df[f"pen{V}"] = df.crossed & (v_after >= V)
        df[f"pois{V}"] = df.crossed & (np.nan_to_num(shape * v_after) >= V)
        OUTCOMES[f"penetration_{V}mL"] = (lambda d, V=V: d[f"pen{V}"])
        OUTCOMES[f"poiseuille_{V}mL"] = (lambda d, V=V: d[f"pois{V}"])
    df.attrs["target_branch_volume_mL"] = V_end
    return df
