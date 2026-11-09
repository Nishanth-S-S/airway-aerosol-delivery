"""Build concrete OpenFOAM cases from base_cases/ + config/experiment.yaml.

Mesh cases     cases/mesh/<geometry>_<level>/          (one mesh per geometry, shared)
Airflow cases  cases/airflow/<geometry>_<flow>/        (pimpleFoam, reuse the mesh)
Particle cases cases/particles/<P..>/                  (airwayParcelFoam, reuse airflow)
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np

from .breathing import LPM_TO_M3S, release_window, waveform
from .common import ROOT, foam_header, geometry_files
from .stl_io import read_ascii_regions

BASE_AIRFLOW = ROOT / "base_cases" / "airflow"
BASE_PARTICLES = ROOT / "base_cases" / "particles"
MESH_DIR = ROOT / "cases" / "mesh"
AIRFLOW_DIR = ROOT / "cases" / "airflow"
PARTICLE_DIR = ROOT / "cases" / "particles"


# ----------------------------------------------------------------- geometry helpers
def target_axis(cfg):
    g = cfg["geometry"]
    a = math.radians(g["branch_angle_deg"])
    return np.array(g["bifurcation_point_mm"], float), np.array([math.sin(a), 0.0, math.cos(a)])


def target_plane(cfg):
    """Point (m), unit normal, radius (m) of the target-entry disc."""
    bif, d = target_axis(cfg)
    p = (bif + cfg["regions"]["target_plane_s_mm"] * d) * 1e-3
    return p, d, cfg["regions"]["target_plane_radius_mm"] * 1e-3


def vec(v, fmt="{:.8g}"):
    return "(" + " ".join(fmt.format(float(x)) for x in v) + ")"


def _patches(cfg, geometry):
    """Patch STL for the configured geometry version (validation geometries have no versions)."""
    if geometry in cfg["geometry"]["variants"]:
        return geometry_files(cfg, geometry)["patches"]
    return ROOT / "geometry" / geometry / "airway_patches_m.stl"


# ----------------------------------------------------------------- mesh case
def mesh_case_dir(geometry: str, level: str) -> Path:
    return MESH_DIR / f"{geometry}_{level}"


def case_parameters(cfg, geometry: str, level: str, end_time: float, n_procs: int) -> str:
    m = cfg["mesh"]["levels"][level]
    a = cfg["airflow"]
    h = m["background_cell_mm"] * 1e-3
    regions = read_ascii_regions(_patches(cfg, geometry))
    pts = np.concatenate([r.reshape(-1, 3) for r in regions.values()])
    lo, hi = pts.min(0) - 2.5 * h, pts.max(0) + 2.5 * h
    n = np.ceil((hi - lo) / h).astype(int)
    hi = lo + n * h
    tp, tn, tr = target_plane(cfg)
    box_lo, box_hi = tp - 1.5 * tr, tp + 1.5 * tr
    loc = np.array(cfg["mesh"]["location_in_mesh_mm"]) * 1e-3
    return foam_header("dictionary", "caseParameters") + f"""// Generated from config/experiment.yaml - do not edit by hand
caseGeometry    {geometry};
caseMeshLevel   {level};

// background block mesh (m)
xmin {lo[0]:.8g}; xmax {hi[0]:.8g};
ymin {lo[1]:.8g}; ymax {hi[1]:.8g};
zmin {lo[2]:.8g}; zmax {hi[2]:.8g};
nx {n[0]}; ny {n[1]}; nz {n[2]};

// snappyHexMesh
surfMin       {m['surface_level'][0]};
surfMax       {m['surface_level'][1]};
featureLevel  {m['surface_level'][1]};
insideLevel   {m['refine_inside_level']};
nLayers       {m['boundary_layers']};
addLayers     {'true' if m['boundary_layers'] > 0 else 'false'};
includedAngle {180 - cfg['mesh']['feature_angle_deg']};
locationInMesh {vec(loc)};

// time control
endTime       {end_time:.8g};
deltaT        {a['initial_dt']:.8g};
maxDeltaT     {a['max_dt']:.8g};
maxCo         {a['max_courant']:.8g};
writeInterval {a['write_interval_s']:.8g};
writeFormat   {cfg['openfoam']['write_format']};

// PIMPLE
nOuter   {a['n_outer_correctors']};
nCorr    {a['n_correctors']};
nNonOrth {a['n_non_orth_correctors']};

// physics
nu       [0 2 -1 0 0 0 0] {cfg['air']['kinematic_viscosity']:.8g};
nProcs   {n_procs};

// target-entry plane (downstream of the narrowing)
targetPlanePoint  {vec(tp)};
targetPlaneNormal {vec(tn)};
targetPlaneBounds {vec(box_lo)} {vec(box_hi)};
"""


def build_mesh_case(cfg, geometry: str, level: str) -> Path:
    d = mesh_case_dir(geometry, level)
    if d.exists():
        shutil.rmtree(d)
    (d / "constant" / "triSurface").mkdir(parents=True)
    shutil.copytree(BASE_AIRFLOW / "system", d / "system")
    shutil.copyfile(_patches(cfg, geometry), d / "constant" / "triSurface" / "airway.stl")
    (d / "system" / "caseParameters").write_text(case_parameters(cfg, geometry, level, 0.0, cfg["openfoam"]["n_procs"]))
    (d / "case.foam").touch()
    return d


# ----------------------------------------------------------------- airflow case
def flow_series(cfg, flow: str):
    """(t, Q) over inhalation + post-inhalation for flow = 'constant' or a waveform name."""
    b = cfg["breathing"]
    if flow == "constant":
        c = b["constant_flow_case"]
        q = c["flow_L_per_min"] * LPM_TO_M3S
        ramp = 0.01   # 10 ms smooth start avoids an impulsive start
        t = np.array([0.0, ramp, c["end_time_s"] + 1.0])
        return t, np.array([0.0, q, q]), c["end_time_s"]
    T, post = b["inhalation_duration_s"], b["post_inhalation_s"]
    t, q = waveform(cfg, flow, 201)
    t = np.concatenate([t, [T + 1e-4, T + post + 1.0]])
    q = np.concatenate([q, [0.0, 0.0]])
    return t, q, T + post


def write_inlet_bc(cfg, case: Path, t, q):
    R = cfg["geometry"]["parent_diameter_mm"] / 2 * 1e-3
    profile = cfg["airflow"]["inlet_profile"]
    table = "\n".join(f"    ({ti:.8g} {qi:.10g})" for ti, qi in zip(t, q))
    (case / "constant" / "inletFlowRate").write_text(f"// t [s]  Q [m3/s]\n(\n{table}\n)\n")
    if profile == "plug":
        bc = ("type flowRateInletVelocity;\n"
              "volumetricFlowRate { type tableFile; file \"<constant>/inletFlowRate\"; outOfBounds clamp; }\n"
              "value uniform (0 0 0);\n")
    elif profile == "parabolic":
        bd = case / "constant" / "boundaryData" / "inlet"
        if bd.exists():
            shutil.rmtree(bd)
        bd.mkdir(parents=True)
        # polar sample grid slightly larger than the inlet so every face is covered
        rings = np.linspace(0, 1.05 * R, 22)[1:]
        pts = [(0.0, 0.0, 0.0)]
        for r in rings:
            nth = max(8, int(2 * math.pi * r / (R / 20)))
            for th in np.linspace(0, 2 * math.pi, nth, endpoint=False):
                pts.append((r * math.cos(th), r * math.sin(th), 0.0))
        pts = np.array(pts)
        rr = np.hypot(pts[:, 0], pts[:, 1])
        shape = np.clip(1 - (rr / R) ** 2, 0, None)
        (bd / "points").write_text(f"{len(pts)}\n(\n" + "\n".join(vec(p) for p in pts) + "\n)\n")
        for ti, qi in zip(t, q):
            umax = 2 * qi / (math.pi * R * R)
            td = bd / f"{ti:.8g}"
            td.mkdir()
            vals = "\n".join(f"(0 0 {umax * s:.8g})" for s in shape)
            (td / "U").write_text(f"{len(pts)}\n(\n{vals}\n)\n")
        bc = ("type timeVaryingMappedFixedValue;\n"
              "mapMethod planar;\n"
              "offset (0 0 0);\n"
              "setAverage false;\n"
              "value uniform (0 0 0);\n")
    else:
        raise ValueError(f"unknown inlet_profile {profile}")
    (case / "constant" / "inletVelocityBC").write_text(
        f"// inlet profile: {profile} (config airflow.inlet_profile)\n" + bc)


def airflow_case_dir(case_id: str) -> Path:
    return AIRFLOW_DIR / case_id


def build_airflow_case(cfg, case_id: str, geometry: str, flow: str, level: str | None = None) -> Path:
    level = level or cfg["mesh"]["level"]
    d = airflow_case_dir(case_id)
    if d.exists():
        shutil.rmtree(d)
    (d / "constant" / "triSurface").mkdir(parents=True)
    shutil.copytree(BASE_AIRFLOW / "system", d / "system")
    shutil.copytree(BASE_AIRFLOW / "0.orig", d / "0.orig")
    for f in ("transportProperties", "turbulenceProperties"):
        shutil.copyfile(BASE_AIRFLOW / "constant" / f, d / "constant" / f)
    shutil.copyfile(_patches(cfg, geometry), d / "constant" / "triSurface" / "airway.stl")
    t, q, end = flow_series(cfg, flow)
    (d / "system" / "caseParameters").write_text(case_parameters(cfg, geometry, level, end, cfg["openfoam"]["n_procs"]))
    write_inlet_bc(cfg, d, t, q)
    (d / "case.foam").touch()
    meta = {"case_id": case_id, "geometry": geometry, "flow": flow, "mesh_level": level,
            "mesh_source": str(mesh_case_dir(geometry, level).relative_to(ROOT)), "end_time_s": end,
            "inlet_profile": cfg["airflow"]["inlet_profile"], "flow_model": cfg["airflow"]["flow_model"],
            "outlet_bc": cfg["airflow"]["outlet_bc"]}
    (d / "case_meta.json").write_text(json.dumps(meta, indent=2))
    return d


# ----------------------------------------------------------------- particle case
def cunningham(d_m, lam):
    kn = 2 * lam / d_m
    return 1 + kn * (1.257 + 0.4 * math.exp(-1.1 / kn))


def particle_case_id(cfg, d_um: float, strategy: str, geometry: str, wave: str) -> str:
    rs = cfg["particles"]["release_strategies"][strategy]["short"]
    g = cfg["geometry"]["variants"][geometry]["short"]
    w = cfg["breathing"]["waveforms"][wave]["short"]
    return f"P{int(round(d_um)):02d}_{rs}_{g}_{w}"


def build_particle_case(cfg, d_um: float, strategy: str, geometry: str, wave: str,
                        n_parcels: int | None = None, seed: int | None = None, case_id: str | None = None,
                        airflow_id: str | None = None) -> Path:
    p = cfg["particles"]
    case_id = case_id or particle_case_id(cfg, d_um, strategy, geometry, wave)
    airflow_id = airflow_id or f"{geometry}_{wave}"
    af = airflow_case_dir(airflow_id)
    n_parcels = n_parcels or p["parcels_per_case"]
    seed = p["random_seed"] if seed is None else seed
    d = PARTICLE_DIR / case_id
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(BASE_PARTICLES, d)

    rw = release_window(cfg, wave, strategy)
    dm = d_um * 1e-6
    cc = cunningham(dm, cfg["air"]["mean_free_path"]) if p["cunningham_slip"] else 1.0
    rho_eff = p["density"] * cc
    M = p["introduced_mass_kg"]
    v_aero = M / p["density"]                      # true particle volume to introduce
    conc = v_aero / rw["window_volume_m3"]         # aerosol volume per inspired air volume in the window
    parcel_conc = n_parcels / v_aero               # parcels per m3 of aerosol volume
    m_particle = p["density"] * math.pi * dm ** 3 / 6
    n_per_parcel = M / (n_parcels * m_particle)
    T_end = cfg["breathing"]["inhalation_duration_s"] + cfg["breathing"]["post_inhalation_s"]
    tp, tn, tr = target_plane(cfg)
    g = cfg["geometry"]
    bif, dt_ax = target_axis(cfg)
    a = math.radians(g["branch_angle_deg"])
    exits = {"inlet": np.array(g["inlet_center_mm"]) * 1e-3,
             "targetOutlet": np.array(g["target_outlet_center_mm"]) * 1e-3,
             "comparisonOutlet": np.array(g["comparison_outlet_center_mm"]) * 1e-3}
    params = foam_header("dictionary", "particleParameters") + f"""// Generated by scripts/generate_particle_cases.py - case {case_id}
diameter            {dm:.8g};
rhoEffective        {rho_eff:.8g};   // rho_p * Cunningham Cc ({cc:.5f}); mass uses the true density
SOI                 {rw['t_start_s']:.8g};
duration            {rw['duration_s']:.8g};
concentration       {conc:.8g};      // aerosol volume / inspired air volume inside the window
parcelConcentration {parcel_conc:.8g};
randomSeed          {seed};
endTime             {T_end:.8g};
deltaT              {p['tracking_dt_s']:.8g};
gravity             {vec(p['gravity'])};
"""
    (d / "constant" / "particleParameters").write_text(params)
    (d / "constant" / "airwayParcelDict").write_text(foam_header("dictionary", "airwayParcelDict") + f"""airflowCase         "/work/{af.relative_to(ROOT).as_posix()}";   // reused airflow solution
rhoAir              {cfg['air']['density']};
nuAir               {cfg['air']['kinematic_viscosity']};
particleDensityTrue {p['density']};
targetPlanePoint    {vec(tp)};
targetPlaneNormal   {vec(tn)};
targetPlaneRadius   {tr:.8g};
inletCentre         {vec(exits['inlet'])};
inletNormal         (0 0 1);
inletRadius         {g['parent_diameter_mm'] / 2e3:.8g};
inletFluxWeighting  {'parabolic' if cfg['airflow']['inlet_profile'] == 'parabolic' else 'none'};
trackSampleEvery    {max(1, n_parcels // 300)};
trackStepStride     5;
randomSeed          {seed};
exitCentres
(
    (inlet {vec(exits['inlet'])})
    (targetOutlet {vec(exits['targetOutlet'])})
    (comparisonOutlet {vec(exits['comparisonOutlet'])})
);
""")
    if cfg["openfoam"]["runner"] != "docker":
        txt = (d / "constant" / "airwayParcelDict").read_text().replace("/work/", str(ROOT) + "/")
        (d / "constant" / "airwayParcelDict").write_text(txt)
    meta = {"case_id": case_id, "particle_size_um": d_um, "release_strategy": strategy, "geometry": geometry,
            "narrowing_percent": g["variants"].get(geometry, {}).get("narrowing_percent"), "waveform": wave,
            "airflow_case": airflow_id, "introduced_mass_target_kg": M, "n_parcels_target": n_parcels,
            "physical_particles_per_parcel": n_per_parcel, "particle_mass_kg": m_particle,
            "parcel_mass_kg": M / n_parcels,
            "cunningham_Cc": cc, "rho_effective": rho_eff, "release_window": rw, "aerosol_volume_concentration": conc,
            "parcel_concentration_per_m3_aerosol": parcel_conc, "random_seed": seed,
            "formula": "n_p = M / (N_parcels * rho_p * pi d^3 / 6); every case introduces the same M"}
    (d / "case_meta.json").write_text(json.dumps(meta, indent=2))
    (d / "case.foam").touch()
    return d
