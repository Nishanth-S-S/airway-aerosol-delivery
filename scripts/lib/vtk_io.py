"""Tiny reader for OpenFOAM legacy-ASCII VTK POLYDATA surfaces (no VTK/ParaView needed)."""
from __future__ import annotations

from pathlib import Path

import numpy as np


def read_vtk_polydata(path: str | Path) -> dict:
    tok = Path(path).read_text().split()
    i = 0
    out = {"points": None, "polys": [], "point_data": {}, "cell_data": {}, "field_data": {}}
    section = "field_data"
    n_cells = n_points = 0
    while i < len(tok):
        t = tok[i].upper()
        if t == "POINTS":
            n_points = int(tok[i + 1]); i += 3
            out["points"] = np.array(tok[i:i + 3 * n_points], float).reshape(-1, 3); i += 3 * n_points
        elif t == "POLYGONS":
            n_cells = int(tok[i + 1]); size = int(tok[i + 2]); i += 3
            if tok[i].upper() == "OFFSETS":               # VTK >= 5.1 layout
                i += 2
                offs = np.array(tok[i:i + n_cells + 1], int); i += n_cells + 1
                i += 2                                     # CONNECTIVITY vtktypeint64
                conn = np.array(tok[i:i + offs[-1]], int); i += offs[-1]
                out["polys"] = [conn[offs[k]:offs[k + 1]] for k in range(n_cells)]
                n_cells = len(out["polys"])
            else:
                vals = np.array(tok[i:i + size], int); i += size
                k = 0
                while k < len(vals):
                    n = vals[k]; out["polys"].append(vals[k + 1:k + 1 + n]); k += n + 1
        elif t in ("POINT_DATA", "CELL_DATA"):
            section = "point_data" if t == "POINT_DATA" else "cell_data"
            i += 2
        elif t == "FIELD":
            nf = int(tok[i + 2]); i += 3
            for _ in range(nf):
                name, nc, nt = tok[i], int(tok[i + 1]), int(tok[i + 2]); i += 4
                arr = np.array(tok[i:i + nc * nt], float).reshape(nt, nc); i += nc * nt
                out[section][name] = arr.squeeze() if nc == 1 else arr
        elif t in ("SCALARS", "VECTORS", "NORMALS"):
            name = tok[i + 1]; nc = 3 if t != "SCALARS" else 1
            i += 3
            if tok[i].upper() == "LOOKUP_TABLE":
                i += 2
            nt = n_points if section == "point_data" else n_cells
            arr = np.array(tok[i:i + nc * nt], float).reshape(nt, nc); i += nc * nt
            out[section][name] = arr.squeeze() if nc == 1 else arr
        else:
            i += 1
    return out
