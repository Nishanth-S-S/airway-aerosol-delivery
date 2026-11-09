#!/usr/bin/env python3
"""PNG figures that need no ParaView (matplotlib only).

    python scripts/plot_results.py --mesh healthy
    python scripts/plot_results.py --airflow healthy_symmetric
    python scripts/plot_results.py --particles P03_CONT_HLT_SYM

Images go to results/visualizations/<case>/ . The symmetry plane y = 0 contains the
whole Y-shaped airway, so the y = 0 section shows every branch at once.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config  # noqa: E402
from lib.foam_case import airflow_case_dir, mesh_case_dir, target_plane  # noqa: E402
from lib.postproc import airflow_timeseries, classify_region, particle_outputs  # noqa: E402
from lib.vtk_io import read_vtk_polydata  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection, PolyCollection  # noqa: E402

VIS = ROOT / "results" / "visualizations"
C_T, C_C, C_I = "#e76f51", "#457b9d", "#2a9d8f"


def _outline(ax, cfg, geometry, lw=1.0, color="k"):
    """Draw the y=0 airway outline from the geometry STL."""
    from identify_boundaries import slice_y0
    from lib.stl_io import read_stl
    from lib.common import geometry_files
    src = geometry_files(cfg, geometry)["source"] if geometry in cfg["geometry"]["variants"] else None
    if src is None or not src.exists():
        return
    tris, _ = read_stl(src)
    segs = [s[:, [0, 2]] for s in slice_y0(tris)]
    ax.add_collection(LineCollection(segs, colors=color, linewidths=lw))


def _plane_line(ax, cfg, color="k"):
    p, n, r = target_plane(cfg)
    perp = np.array([n[2], 0, -n[0]])
    a, b = (p + r * perp) * 1e3, (p - r * perp) * 1e3
    ax.plot([a[0], b[0]], [a[2], b[2]], "--", color=color, lw=1.2)
    ax.annotate("target entry plane", xy=(a[0], a[2]), xytext=(a[0] + 2, a[2] - 6), fontsize=7, color=color)


def _polys_xz(vtk):
    pts = vtk["points"][:, [0, 2]] * 1e3
    return [pts[p] for p in vtk["polys"]], pts


def _style(ax, title):
    ax.set_aspect("equal")
    ax.set_xlim(-35, 35); ax.set_ylim(-2, 96)
    ax.set_xlabel("x (mm)   [+x = target branch]"); ax.set_ylabel("z (mm)")
    ax.set_title(title, fontsize=10)


# ===================================================================== mesh
def plot_mesh(geometry: str, level: str | None = None):
    cfg = load_config()
    level = level or cfg["mesh"]["level"]
    d = mesh_case_dir(geometry, level)
    f = d / "postProcessing" / "meshCut" / "0" / "yMid.vtk"
    if not f.exists():
        raise FileNotFoundError(f)
    vtk = read_vtk_polydata(f)
    polys, _ = _polys_xz(vtk)
    area = np.array([0.5 * abs(np.dot(p[:, 0], np.roll(p[:, 1], 1)) - np.dot(p[:, 1], np.roll(p[:, 0], 1))) for p in polys])
    size = np.sqrt(np.maximum(area, 1e-12))
    rep = json.loads((d / "mesh_report.json").read_text())
    fig = plt.figure(figsize=(14, 7.5))
    gs = fig.add_gridspec(2, 3, width_ratios=[1.25, 1, 1])
    ax = fig.add_subplot(gs[:, 0])
    pc = PolyCollection(polys, array=size, cmap="viridis_r", edgecolors="k", linewidths=0.08)
    ax.add_collection(pc)
    _style(ax, f"{cfg['geometry']['variants'][geometry]['label']} — mesh section y = 0 ({level})")
    fig.colorbar(pc, ax=ax, shrink=0.6, label="local cell size in section (mm)")
    zooms = [("junction / carina", (-8, 8, 34, 50)), ("target branch narrowing", (4, 20, 48, 70)),
             ("inlet", (-6, 6, -1, 8)), ("target outlet", (24, 34, 84, 95))]
    for k, (title, (x0, x1, z0, z1)) in enumerate(zooms):
        a = fig.add_subplot(gs[k // 2, 1 + k % 2])
        a.add_collection(PolyCollection(polys, facecolors="#eef1f6", edgecolors="#1d3557", linewidths=0.25))
        a.set_xlim(x0, x1); a.set_ylim(z0, z1); a.set_aspect("equal"); a.set_title(title, fontsize=9)
        a.tick_params(labelsize=7)
    txt = (f"cells: {rep['cells']:,}   hex: {rep['hexahedra']:,}   poly: {rep['polyhedra']:,}\n"
           f"max non-orthogonality: {rep['max_non_orthogonality']:.1f}°   max skewness: {rep['max_skewness']:.2f}\n"
           f"meshed volume vs STL: {rep.get('volume_error_vs_stl_percent', float('nan')):+.2f} %   checkMesh: {rep['status']}")
    fig.text(0.01, 0.01, txt, fontsize=9, family="monospace",
             color="#1b5e20" if rep["status"] == "PASSED" else "#b71c1c")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    out = VIS / "mesh"
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"mesh_{geometry}_{level}.png", dpi=130)
    plt.close(fig)
    print(f"  [png] results/visualizations/mesh/mesh_{geometry}_{level}.png")


# ===================================================================== airflow
def _surface_times(case_dir: Path):
    base = case_dir / "postProcessing" / "midPlane"
    out = []
    if base.exists():
        for t in base.iterdir():
            try:
                tv = float(t.name)
            except ValueError:
                continue
            if (t / "yMid.vtk").exists():
                out.append((tv, t / "yMid.vtk"))
    return sorted(out)


def _field_map(ax, vtk, values, cmap, label, fig, vmin=None, vmax=None):
    polys, _ = _polys_xz(vtk)
    pc = PolyCollection(polys, array=values, cmap=cmap, edgecolors="face", linewidths=0.05)
    if vmin is not None:
        pc.set_clim(vmin, vmax)
    ax.add_collection(pc)
    fig.colorbar(pc, ax=ax, shrink=0.75, label=label)
    return pc


def _grid_velocity(vtk, h=0.25):
    """Interpolate in-plane (Ux, Uz) at polygon centroids onto a regular grid (mm)."""
    from scipy.interpolate import griddata
    from scipy.spatial import cKDTree
    polys, _ = _polys_xz(vtk)
    cen = np.array([p.mean(0) for p in polys])
    U = vtk["cell_data"]["U"]
    xs = np.arange(-34, 34, h); zs = np.arange(-1, 95, h)
    X, Z = np.meshgrid(xs, zs)
    ux = griddata(cen, U[:, 0], (X, Z), method="linear")
    uz = griddata(cen, U[:, 2], (X, Z), method="linear")
    dist, _ = cKDTree(cen).query(np.c_[X.ravel(), Z.ravel()])
    mask = dist.reshape(X.shape) > 0.6
    ux[mask] = np.nan; uz[mask] = np.nan
    return xs, zs, ux, uz


def plot_airflow(case_id: str):
    cfg = load_config()
    d = airflow_case_dir(case_id)
    meta = json.loads((d / "case_meta.json").read_text())
    geometry = meta["geometry"]
    out = VIS / case_id
    out.mkdir(parents=True, exist_ok=True)
    rho = cfg["air"]["density"]
    ts = airflow_timeseries(d)
    T = cfg["breathing"]["inhalation_duration_s"]
    title_case = f"{cfg['geometry']['variants'][geometry]['label']}, {meta['flow']} flow"

    times = _surface_times(d)
    if times:
        if meta["flow"] == "constant":
            t_show = times[-1][0]
        else:   # write time closest to peak inlet flow
            t_peak = float(ts.time[ts.Q_in.idxmax()])
            t_show = min(times, key=lambda x: abs(x[0] - t_peak))[0]
        vtk = read_vtk_polydata(dict(times)[t_show])
        U = vtk["cell_data"]["U"]; umag = np.linalg.norm(U, axis=1)
        p_pa = vtk["cell_data"]["p"] * rho
        q_now = float(np.interp(t_show, ts.time, ts.Q_in)) * 6e4

        # 1 velocity magnitude
        fig, ax = plt.subplots(figsize=(7, 8.5))
        _field_map(ax, vtk, umag, "turbo", "|U| (m/s)", fig)
        _outline(ax, cfg, geometry, 0.6)
        _plane_line(ax, cfg)
        _style(ax, f"Velocity magnitude, y = 0 section\n{title_case}, t = {t_show:.2f} s (inlet {q_now:.2f} L/min)")
        fig.tight_layout(); fig.savefig(out / "velocity_magnitude.png", dpi=140); plt.close(fig)

        # 2 pressure
        fig, ax = plt.subplots(figsize=(7, 8.5))
        _field_map(ax, vtk, p_pa, "viridis", "static pressure (Pa, outlets = 0)", fig)
        _outline(ax, cfg, geometry, 0.6)
        _style(ax, f"Pressure, y = 0 section\n{title_case}, t = {t_show:.2f} s")
        fig.tight_layout(); fig.savefig(out / "pressure.png", dpi=140); plt.close(fig)

        # 3 streamlines of the in-plane velocity
        xs, zs, ux, uz = _grid_velocity(vtk)
        fig, ax = plt.subplots(figsize=(7, 8.5))
        spd = np.hypot(ux, uz)
        ax.imshow(spd, origin="lower", extent=(xs[0], xs[-1], zs[0], zs[-1]), cmap="Blues", alpha=0.55)
        seeds = np.array([[x, 1.0] for x in np.linspace(-3.4, 3.4, 15)])
        ax.streamplot(xs, zs, np.nan_to_num(ux), np.nan_to_num(uz), color=spd, cmap="plasma", density=2.2,
                      linewidth=0.8, arrowsize=0.7, start_points=seeds, broken_streamlines=False)
        ax.streamplot(xs, zs, np.nan_to_num(ux), np.nan_to_num(uz), color="#555", density=1.4, linewidth=0.35,
                      arrowsize=0.5)
        _outline(ax, cfg, geometry, 1.0)
        _plane_line(ax, cfg)
        _style(ax, f"Streamlines (in-plane velocity, y = 0)\n{title_case}, t = {t_show:.2f} s\n"
                   "coloured lines start at the inlet")
        fig.tight_layout(); fig.savefig(out / "streamlines.png", dpi=140); plt.close(fig)

        # velocity over time montage
        if meta["flow"] != "constant":
            wanted = [0.25, 0.5, 1.0, 1.5, 1.9, 2.5]
            sel = [min(times, key=lambda x: abs(x[0] - w)) for w in wanted]
            fig, axes = plt.subplots(1, len(sel), figsize=(3.1 * len(sel), 5.2))
            vmax = max(np.linalg.norm(read_vtk_polydata(f)["cell_data"]["U"], axis=1).max() for _, f in sel)
            for ax, (tv, f) in zip(axes, sel):
                v = read_vtk_polydata(f)
                polys, _ = _polys_xz(v)
                pc = PolyCollection(polys, array=np.linalg.norm(v["cell_data"]["U"], axis=1), cmap="turbo",
                                    edgecolors="face", linewidths=0.05)
                pc.set_clim(0, vmax); ax.add_collection(pc)
                ax.set_aspect("equal"); ax.set_xlim(-35, 35); ax.set_ylim(-2, 96); ax.set_xticks([]); ax.set_yticks([])
                ax.set_title(f"t = {tv:.2f} s\nQ_in = {np.interp(tv, ts.time, ts.Q_in) * 6e4:.2f} L/min", fontsize=9)
            fig.colorbar(pc, ax=axes, shrink=0.8, label="|U| (m/s)")
            fig.suptitle(f"Velocity magnitude through the breath — {title_case}")
            fig.savefig(out / "velocity_over_time.png", dpi=120, bbox_inches="tight"); plt.close(fig)

    # 4 outlet flow rates
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    ax.plot(ts.time, ts.Q_in * 6e4, color=C_I, lw=2.2, label="inlet")
    ax.plot(ts.time, ts.Q_target * 6e4, color=C_T, lw=1.8, label="target outlet (+x, narrowed side)")
    ax.plot(ts.time, ts.Q_comparison * 6e4, color=C_C, lw=1.8, label="comparison outlet (-x)")
    if "Q_target_plane" in ts:
        ax.plot(ts.time, ts.Q_target_plane * 6e4, ":", color="k", lw=1.2, label="through target entry plane")
    if meta["flow"] != "constant":
        ax.axvspan(T, ts.time.max(), color="grey", alpha=0.08, label="post-inhalation (no inlet flow)")
    ax.set_xlabel("time (s)"); ax.set_ylabel("flow rate (L/min)"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    ax.set_title(f"Flow through each boundary — {title_case}")
    fig.tight_layout(); fig.savefig(out / "flow_rates.png", dpi=140); plt.close(fig)

    # 5 pressure drop
    if "dp_Pa" in ts:
        fig, ax = plt.subplots(figsize=(8.5, 4.2))
        ax.plot(ts.time, ts.dp_Pa, color="#6d597a", lw=2, label="inlet − mean outlet")
        ax.plot(ts.time, ts.dp_target_Pa, "--", color=C_T, lw=1.2, label="inlet − target outlet")
        ax.set_xlabel("time (s)"); ax.set_ylabel("pressure drop (Pa)"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
        ax.set_title(f"Pressure drop (area-averaged static pressure) — {title_case}")
        fig.tight_layout(); fig.savefig(out / "pressure_drop.png", dpi=140); plt.close(fig)

    # 6 conservation
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8.5, 5.6), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    a1.plot(ts.time, ts.Q_in * 6e4, color=C_I, lw=2.4, label="inlet flow")
    a1.plot(ts.time, ts.Q_out_total * 6e4, "--", color="k", lw=1.4, label="target + comparison outlet")
    a1.set_ylabel("L/min"); a1.legend(fontsize=8); a1.grid(alpha=0.3)
    a1.set_title(f"Mass conservation check — {title_case}")
    qref = max(ts.Q_in.abs().max(), 1e-12)
    a2.plot(ts.time, 100 * (ts.Q_in - ts.Q_out_total) / qref, color="#b5179e", lw=1)
    a2.set_ylabel("imbalance\n(% of peak inflow)"); a2.set_xlabel("time (s)"); a2.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(out / "conservation.png", dpi=140); plt.close(fig)
    ts.to_csv(out / "airflow_timeseries.csv", index=False)
    print(f"  [png] results/visualizations/{case_id}/ (velocity, pressure, streamlines, flow rates, dp, conservation)")


# ===================================================================== particles
REGION_COLORS = {"upstream": "#8d99ae", "constriction": "#f4a261", "target": C_T, "comparison": C_C}


def plot_particles(case_id: str):
    cfg = load_config()
    case = ROOT / "cases" / "particles" / case_id
    o = particle_outputs(case)
    meta = o["meta"]
    out = VIS / case_id
    out.mkdir(parents=True, exist_ok=True)
    geometry = meta["geometry"]
    glabel = cfg["geometry"]["variants"].get(geometry, {}).get("label", geometry)
    label = (f"{meta['particle_size_um']:g} µm, {meta['release_strategy']} release, "
             f"{glabel}, {meta['waveform']} breathing")

    fig, axes = plt.subplots(1, 2, figsize=(13, 8.2))
    ax = axes[0]
    tr = o["tracks"]
    if tr is not None and len(tr):
        for pid, g in tr.groupby("origId"):
            ax.plot(g.x * 1e3, g.z * 1e3, lw=0.5, alpha=0.6, color=plt.cm.viridis(g.time.iloc[0] / tr.time.max()))
    _outline(ax, cfg, geometry, 1.0); _plane_line(ax, cfg)
    sm = plt.cm.ScalarMappable(cmap="viridis", norm=plt.Normalize(0, tr.time.max() if tr is not None else 1))
    fig.colorbar(sm, ax=ax, shrink=0.6, label="release time of the parcel (s)")
    _style(ax, f"Sample parcel trajectories (projected on x-z)\n{label}")

    ax = axes[1]
    fp = o["finalParcels"]
    if fp is not None and len(fp):
        dep = fp[fp.active == 0]
        reg = classify_region(dep[["x", "y", "z"]].values, cfg)
        for r_, col in REGION_COLORS.items():
            m = reg == r_
            ax.scatter(dep.x[m] * 1e3, dep.z[m] * 1e3, s=3, color=col, label=f"deposited – {r_}")
        sus = fp[fp.active == 1]
        ax.scatter(sus.x * 1e3, sus.z * 1e3, s=3, color="#7209b7", marker="x", label="still suspended at end")
    _outline(ax, cfg, geometry, 1.0); _plane_line(ax, cfg)
    _style(ax, "Where the aerosol ended up (final state)")
    ax.legend(fontsize=7, loc="lower right", markerscale=3)
    fig.tight_layout(); fig.savefig(out / "particle_trajectories.png", dpi=140); plt.close(fig)

    mb = o["massBudget"]
    if mb is not None:
        M = mb.injected_mass.iloc[-1]
        fig, ax = plt.subplots(figsize=(8.5, 4.6))
        ax.stackplot(mb.time, 100 * mb.deposited_mass / M, 100 * mb.escaped_targetOutlet / M,
                     100 * mb.escaped_comparisonOutlet / M, 100 * mb.get("escaped_inlet", 0 * mb.time) / M,
                     100 * mb.suspended_mass / M,
                     colors=["#8d99ae", C_T, C_C, "#ccc", "#7209b7"],
                     labels=["deposited on walls", "escaped target outlet", "escaped comparison outlet",
                             "left via inlet", "suspended in airway"])
        ax.plot(mb.time, 100 * mb.crossed_mass / M, "k--", lw=1.6, label="crossed target entry plane (cumulative)")
        ax.plot(mb.time, 100 * mb.injected_mass / M, color="k", lw=0.8, label="introduced so far")
        ax.set_xlabel("time (s)"); ax.set_ylabel("% of total introduced aerosol mass"); ax.set_ylim(0, 105)
        ax.grid(alpha=0.3); ax.legend(fontsize=7, loc="center right")
        ax.set_title(f"Aerosol mass budget over time\n{label}", fontsize=10)
        fig.tight_layout(); fig.savefig(out / "mass_budget.png", dpi=140); plt.close(fig)

    cr = o["targetPlaneCrossings"]
    if cr is not None and len(cr):
        fig, ax = plt.subplots(figsize=(7.5, 4))
        ax.hist(cr.time, bins=40, weights=100 * cr.mass / mb.injected_mass.iloc[-1], color=C_T, alpha=0.85)
        ax.axvline(np.average(cr.time, weights=cr.mass), color="k", ls="--",
                   label=f"mass-weighted mean {np.average(cr.time, weights=cr.mass):.3f} s")
        ax.set_xlabel("first-crossing time at target entry plane (s)"); ax.set_ylabel("% of introduced mass")
        ax.legend(fontsize=8); ax.grid(alpha=0.3); ax.set_title(f"Arrival-time distribution — {case_id}")
        fig.tight_layout(); fig.savefig(out / "arrival_times.png", dpi=140); plt.close(fig)
    print(f"  [png] results/visualizations/{case_id}/ (trajectories, mass budget, arrival times)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mesh"); ap.add_argument("--level")
    ap.add_argument("--airflow"); ap.add_argument("--particles")
    a = ap.parse_args()
    if a.mesh:
        plot_mesh(a.mesh, a.level)
    if a.airflow:
        plot_airflow(a.airflow)
    if a.particles:
        plot_particles(a.particles)


if __name__ == "__main__":
    main()
