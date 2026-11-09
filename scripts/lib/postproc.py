"""Read OpenFOAM function-object output into pandas tables."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import load_config


def read_fo(case_dir: Path, name: str) -> pd.DataFrame | None:
    """Concatenate postProcessing/<name>/<startTime>/*.dat (handles restarts)."""
    base = Path(case_dir) / "postProcessing" / name
    if not base.exists():
        return None
    frames = []
    for sub in sorted(base.iterdir(), key=lambda p: float(p.name) if _num(p.name) else -1):
        for f in sub.glob("*.dat"):
            rows = []
            for line in f.read_text().splitlines():
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.replace("(", " ").replace(")", " ").split()
                rows.append([float(x) for x in parts])
            if rows:
                frames.append(pd.DataFrame(rows))
    if not frames:
        return None
    df = pd.concat(frames).drop_duplicates(subset=0, keep="last").sort_values(0).reset_index(drop=True)
    return df


def _num(s):
    try:
        float(s); return True
    except ValueError:
        return False


def airflow_timeseries(case_dir: Path) -> pd.DataFrame | None:
    """time, Q_in, Q_target, Q_comparison, Q_out_total, Q_target_plane [m3/s], pressures [Pa], dp_Pa."""
    cfg = load_config()
    rho = cfg["air"]["density"]
    parts = {}
    for key, fo in [("Q_in", "flowInlet"), ("Q_target", "flowTargetOutlet"),
                    ("Q_comparison", "flowComparisonOutlet"), ("p_in", "pInlet"),
                    ("p_target", "pTargetOutlet"), ("p_comparison", "pComparisonOutlet"),
                    ("Q_target_plane", "pTargetPlane")]:
        df = read_fo(case_dir, fo)
        if df is not None:
            parts[key] = df.set_index(0)[1]
    if "Q_in" not in parts:
        return None
    ts = pd.DataFrame(parts)
    ts.index.name = "time"
    ts = ts.reset_index().dropna(subset=["Q_in"])
    ts["Q_in"] = -ts["Q_in"]                                 # inflow is negative phi
    ts["Q_out_total"] = ts["Q_target"] + ts["Q_comparison"]
    for k in ("p_in", "p_target", "p_comparison"):
        if k in ts:
            ts[k] = ts[k] * rho                              # kinematic -> Pa
    if {"p_in", "p_target", "p_comparison"} <= set(ts.columns):
        ts["dp_Pa"] = ts["p_in"] - 0.5 * (ts["p_target"] + ts["p_comparison"])
        ts["dp_target_Pa"] = ts["p_in"] - ts["p_target"]
    return ts


def particle_outputs(case_dir: Path) -> dict:
    d = Path(case_dir) / "postProcessing" / "airwayParcels"
    out = {}
    for name in ("massBudget", "targetPlaneCrossings", "escapes", "finalParcels", "tracks"):
        f = d / f"{name}.csv"
        out[name] = pd.read_csv(f) if f.exists() and f.stat().st_size > 0 else None
    meta = Path(case_dir) / "case_meta.json"
    out["meta"] = json.loads(meta.read_text()) if meta.exists() else {}
    return out


def classify_region(xyz_m: np.ndarray, cfg: dict) -> np.ndarray:
    """Assign wall-deposition positions to upstream / constriction / target / comparison.

    Uses the distance to three centre-line segments (parent, target branch, comparison
    branch) and, inside the target branch, the distance s from the bifurcation:
        s < narrowing_start                 -> upstream
        narrowing_start <= s < plane_s      -> constriction
        s >= plane_s                        -> target
    """
    g, r = cfg["geometry"], cfg["regions"]
    p = np.asarray(xyz_m, float) * 1e3
    bif = np.array(g["bifurcation_point_mm"], float)
    a = np.radians(g["branch_angle_deg"])
    dirs = {"parent": (np.array(g["inlet_center_mm"], float), np.array([0, 0, 1.0]), g["parent_length_mm"]),
            "target": (bif, np.array([np.sin(a), 0, np.cos(a)]), g["daughter_length_mm"]),
            "comparison": (bif, np.array([-np.sin(a), 0, np.cos(a)]), g["daughter_length_mm"])}
    dist, svals = {}, {}
    for k, (o, dv, L) in dirs.items():
        s = np.clip((p - o) @ dv, 0, L)
        foot = o + np.outer(s, dv)
        dist[k] = np.linalg.norm(p - foot, axis=1)
        svals[k] = (p - o) @ dv
    keys = list(dirs)
    best = np.array(keys)[np.argmin(np.stack([dist[k] for k in keys]), axis=0)]
    region = np.where(best == "comparison", "comparison", "upstream").astype(object)
    st = svals["target"]
    tgt = best == "target"
    region[tgt & (st >= g["narrowing_start_mm"]) & (st < r["target_plane_s_mm"])] = "constriction"
    region[tgt & (st >= r["target_plane_s_mm"])] = "target"
    return region
