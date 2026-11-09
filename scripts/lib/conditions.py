"""Condition registry: training / held-out conditions -> case ids and per-condition config."""
from __future__ import annotations

import copy

import yaml

from .common import ROOT

COND_PATH = ROOT / "config" / "conditions.yaml"


def load_conditions() -> dict:
    return yaml.safe_load(COND_PATH.read_text())


def all_conditions(reg: dict | None = None) -> list[dict]:
    reg = reg or load_conditions()
    out = []
    for split in ("training", "test"):
        for c in reg[split]:
            out.append({**c, "split": split})
    return out


def get_condition(cid: str) -> dict:
    for c in all_conditions():
        if c["id"] == cid:
            return c
    raise KeyError(cid)


def wave_name(c: dict) -> str:
    return f"beta{c['a']}{c['b']}"


def cfg_for(cfg: dict, c: dict) -> dict:
    """Deep-copied config whose breathing section describes condition c (waveform key = wave_name)."""
    k = copy.deepcopy(cfg)
    k["breathing"]["mean_flow_L_per_min"] = float(c["flow_lpm"])
    k["breathing"]["waveforms"][wave_name(c)] = {"a": c["a"], "b": c["b"], "label": f"Beta({c['a']},{c['b']})",
                                                 "short": f"B{c['a']}{c['b']}"}
    reg = load_conditions()
    for g, spec in reg.get("extra_geometries", {}).items():
        if g not in k["geometry"]["variants"]:
            k["geometry"]["variants"][g] = {"source_stem": None, "narrowing_percent": None, "label": spec["label"], "short": g.upper()}
    return k


def airflow_id(c: dict) -> str:
    """Airflow case directory name for a condition (v002 study cases live in cases/airflow/)."""
    return f"{c['id']}"
