#!/usr/bin/env python3
"""Phase 16: build results/report.html (open it by double-clicking; no server needed).

    python scripts/build_report.py

Images are referenced with relative paths, so keep report.html inside results/.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_particle_cases import DEV_CASE, case_matrix  # noqa: E402
from lib.common import ROOT, load_config, read_status  # noqa: E402

RES = ROOT / "results"
OUT = RES / "report.html"


def img(path: Path, caption: str = "", cls: str = "") -> str:
    if not path.exists():
        return f'<figure class="missing {cls}"><div>not produced yet</div><figcaption>{html.escape(caption)}</figcaption></figure>'
    rel = path.relative_to(RES).as_posix()
    return (f'<figure class="{cls}"><a href="{rel}" target="_blank"><img src="{rel}" loading="lazy" alt="{html.escape(caption)}"></a>'
            f'<figcaption>{html.escape(caption)}</figcaption></figure>')


def badge(status: str) -> str:
    s = (status or "").upper()
    cls = {"PASSED": "ok", "COMPLETED": "ok", "FAILED": "bad", "RUNNING": "run", "BLOCKED": "warn"}.get(s, "na")
    return f'<span class="badge {cls}">{html.escape(status or "not run")}</span>'


def table(df: pd.DataFrame, fmt: dict | None = None, status_cols=("qa_status", "status", "mesh_status",
                                                                   "solver_status", "particle_status")) -> str:
    fmt = fmt or {}
    h = "<div class='tw'><table><thead><tr>" + "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns) + "</tr></thead><tbody>"
    for _, r in df.iterrows():
        bad = any(str(r.get(c, "")).upper() == "FAILED" for c in status_cols if c in df.columns)
        h += f"<tr class='{'failrow' if bad else ''}'>"
        for c in df.columns:
            v = r[c]
            if c in status_cols:
                cell = badge(str(v) if pd.notna(v) else "")
            elif isinstance(v, float):
                cell = "" if pd.isna(v) else (fmt.get(c, "{:.4g}").format(v))
            else:
                cell = html.escape(str(v)) if pd.notna(v) else ""
            h += f"<td>{cell}</td>"
        h += "</tr>"
    return h + "</tbody></table></div>"


def kv(d: dict, keys: list[tuple[str, str, str]]) -> str:
    out = "<dl class='kv'>"
    for k, label, f in keys:
        v = d.get(k)
        if v is None:
            continue
        out += f"<dt>{html.escape(label)}</dt><dd>{f.format(v) if isinstance(v, (int, float)) else html.escape(str(v))}</dd>"
    return out + "</dl>"


def geometry_qa_html(cfg) -> str:
    qf = ROOT / "geometry" / "geometry_qa.json"
    if not qf.exists():
        return ""
    q = json.loads(qf.read_text())
    rows = []
    for k, v in q.items():
        for ver, m in v.items():
            rows.append({"geometry": k, "version": ver, "flat wall facing the flow (mm²)": m["flat_flow_facing_area_mm2"],
                         "max radius below junction (mm)": m["max_radius_below_junction_mm"], "volume (mm³)": m["volume_mm3"]})
    ver = cfg["geometry"].get("version", "v001")
    return ("<h3>3D model check</h3><div class='failbox'><b>Junction defects in the approved v001 models</b> (all three): "
            "a flat shelf at z = 40 mm covering 35 % of the parent cross-section that faces straight into the flow, and "
            "branch cylinders poking out through the parent wall (pockets up to 0.42 mm). A corrected <b>v002</b> with a smooth "
            "junction and the identical narrowing is available. Details: <a href='../docs/GEOMETRY_QA.md'>docs/GEOMETRY_QA.md</a>.</div>"
            f"<p>CFD results in this report use geometry <b>{ver}</b>.</p>"
            + table(pd.DataFrame(rows), {"volume (mm³)": "{:.1f}"})
            + "<div class='gallery one'>" + img(RES / "figures" / "geometry_qa" / "junction_v001_vs_v002.png",
                                               "v001 (red) vs corrected v002 (blue): junction sections, lumen area, narrowing") + "</div>")


def main():
    cfg = load_config()
    st = read_status()
    variants = cfg["geometry"]["variants"]
    waves = cfg["breathing"]["waveforms"]
    study_airflow = [f"{g}_{w}" for g in variants for w in waves]
    matrix = case_matrix(cfg)
    af_done = [c for c in study_airflow if st.get(c, {}).get("qa_status") == "PASSED"]
    af_fail = [c for c in study_airflow + ["healthy_constant"] if st.get(c, {}).get("qa_status") == "FAILED"]
    p_ids = set(matrix.case_id)
    p_done = [c for c in p_ids if st.get(c, {}).get("particle_status") == "completed"]
    p_pass = [c for c in p_ids if st.get(c, {}).get("qa_status") == "PASSED"]
    p_fail = [c for c in p_ids if st.get(c, {}).get("qa_status") == "FAILED" or st.get(c, {}).get("particle_status") == "FAILED"]
    mesh_rows = {k: v for k, v in st.items() if v.get("case_type") == "mesh"}
    all_fail = sorted([k for k, v in st.items() if "FAILED" in (v.get("qa_status", "").upper(), v.get("mesh_status", "").upper(),
                                                                   v.get("solver_status", "").upper(), v.get("particle_status", "").upper())])

    S = []
    S.append(f"""
<header>
  <div>
    <h1>Airway aerosol delivery — CFD workflow report</h1>
    <p class="sub">Y-shaped airway · healthy / 20 % / 40 % narrowing · OpenFOAM v2406 (Docker) · generated {dt.datetime.now():%Y-%m-%d %H:%M}</p>
  </div>
</header>
<div class="banner">Development stage. <b>No result in this report is scientifically validated yet</b> — the mesh, time-step,
parcel-count and outlet-condition studies in <code>validation/</code> must be run first. Numbers shown are produced by the solver,
on the provisional development settings listed under “Model settings”.</div>
<section class="cards">
  <div class="card"><div class="n">{len(af_done)} / 9</div><div class="l">airflow cases passed QA</div></div>
  <div class="card"><div class="n">{len(p_done)} / 144</div><div class="l">particle cases complete</div></div>
  <div class="card"><div class="n">{len(p_pass)}</div><div class="l">particle cases passed QA</div></div>
  <div class="card {'alert' if all_fail else ''}"><div class="n">{len(all_fail)}</div><div class="l">failed cases (any stage)</div></div>
  <div class="card"><div class="n">{sum(1 for v in mesh_rows.values() if v.get('mesh_status') == 'PASSED')} / {len(mesh_rows)}</div><div class="l">meshes passed checkMesh</div></div>
</section>
<nav>
  <a href="#status">Experiment status</a><a href="#geometry">Geometry</a><a href="#mesh">Mesh</a><a href="#airflow">Airflow</a>
  <a href="#breathing">Breathing</a><a href="#particles">Particles</a><a href="#validation">Validation</a><a href="#settings">Model settings</a><a href="#runs">All runs</a>
</nav>""")

    # ---------------------------------------------------------------- status grids
    def cell_cls(cid):
        s = st.get(cid, {})
        if "FAILED" in (s.get("qa_status", "").upper(), s.get("particle_status", "").upper(), s.get("solver_status", "").upper()):
            return "g-fail", "failed"
        if s.get("qa_status") == "PASSED":
            return "g-ok", "passed QA"
        if s.get("particle_status") in ("running",) or s.get("solver_status") == "running":
            return "g-run", "running"
        if s.get("particle_status") == "blocked":
            return "g-block", "blocked: airflow not ready"
        if s.get("particle_status") == "generated" or s.get("solver_status") == "generated":
            return "g-gen", "generated, not run"
        return "g-none", "not generated"

    g_af = "<div class='grid3'><div></div>" + "".join(f"<div class='gh'>{html.escape(w['label'])}</div>" for w in waves.values())
    for g, gv in variants.items():
        g_af += f"<div class='gh l'>{html.escape(gv['label'])}</div>"
        for w in waves:
            c = f"{g}_{w}"; cls, t = cell_cls(c)
            g_af += f"<div class='gc {cls}' title='{c}: {t}'>{c}</div>"
    g_af += "</div>"
    sizes = cfg["particles"]["diameters_um"]; rels = cfg["particles"]["release_strategies"]
    g_p = "<div class='tw'><table class='pgrid'><thead><tr><th>geometry · waveform</th>"
    for d in sizes:
        for r in rels:
            g_p += f"<th>{d:g} µm<br>{r}</th>"
    g_p += "</tr></thead><tbody>"
    for g, gv in variants.items():
        for w, wv in waves.items():
            g_p += f"<tr><th>{gv['short']} · {wv['short']}</th>"
            for d in sizes:
                for r in rels:
                    row = matrix[(matrix.geometry == g) & (matrix.waveform == w) & (matrix.particle_size_um == d) & (matrix.release_strategy == r)]
                    cid = row.case_id.iloc[0]; cls, t = cell_cls(cid)
                    g_p += f"<td class='{cls}' title='{cid}: {t}'>{'★' if cid == DEV_CASE else ''}</td>"
            g_p += "</tr>"
    g_p += "</tbody></table></div>"
    legend = ("<div class='legend'><span class='g-ok'></span>passed QA <span class='g-fail'></span>failed "
              "<span class='g-run'></span>running <span class='g-gen'></span>generated, not run "
              "<span class='g-block'></span>blocked <span class='g-none'></span>not generated &nbsp; ★ = development case</div>")
    fail_list = ("<p class='ok-text'>No failed cases.</p>" if not all_fail else
                 "<div class='failbox'><b>Failed cases:</b><ul>" + "".join(
                     f"<li><code>{c}</code> — {html.escape(st[c].get('notes', ''))}</li>" for c in all_fail) + "</ul></div>")
    S.append(f"<section id='status'><h2>Experiment status</h2>{fail_list}<h3>Airflow solutions (9)</h3>{g_af}"
             f"<h3>Particle cases (144 = 4 sizes × 4 releases × 3 geometries × 3 waveforms)</h3>{legend}{g_p}</section>")

    # ---------------------------------------------------------------- geometry
    gc = json.loads((ROOT / "geometry" / "geometry_check.json").read_text())
    bi = json.loads((ROOT / "geometry" / "boundary_identification.json").read_text())
    rows = []
    for k, v in gc.items():
        b = bi[k]
        rows.append({"geometry": k, "source STL": v["source"], "triangles": v["n_triangles"],
                     "zero-area tris removed": v["degenerate_triangles_removed"], "watertight": v["watertight"],
                     "volume err vs QA %": v["volume_error_percent"], "min target Ø (mm)": b["measured_min_target_diameter_mm"],
                     "diameter reduction %": b["measured_diameter_reduction_percent"],
                     "area reduction %": b["measured_area_reduction_percent"], "status": "PASSED" if v["cfd_usable"] else "FAILED"})
    S.append("<section id='geometry'><h2>Geometry</h2><p>Approved Onshape geometries (units mm, scaled to m for OpenFOAM). "
             "Boundaries were identified geometrically from the STL — see <a href='../docs/boundary_identification.md'>docs/boundary_identification.md</a>. "
             "The +X (right, orange) branch is the target branch. Note: “20 % / 40 % narrowing” is a <b>diameter</b> reduction; "
             "the cross-sectional area is reduced by 36 % / 64 %.</p>"
             + table(pd.DataFrame(rows), {"volume err vs QA %": "{:+.3f}"})
             + "<div class='gallery one'>" + "".join(img(RES / "figures" / f"geometry_{k}.png", variants[k]["label"]) for k in variants) + "</div>"
             + geometry_qa_html(cfg) + "</section>")

    # ---------------------------------------------------------------- mesh
    mrows, mimgs = [], ""
    for d in sorted((ROOT / "cases" / "mesh").glob("*/mesh_report.json")):
        r = json.loads(d.read_text())
        if r.get("geometry") not in variants:
            continue
        mrows.append({"mesh": d.parent.name, "cells": r["cells"], "max non-orth (°)": r["max_non_orthogonality"],
                      "max skewness": r["max_skewness"], "max aspect": r["max_aspect_ratio"],
                      "volume vs STL %": r.get("volume_error_vs_stl_percent"), "status": r["status"],
                      "problems": "; ".join(r.get("problems", []))})
    lvl = cfg["mesh"]["level"]
    for k in variants:
        mimgs += img(RES / "visualizations" / "mesh" / f"mesh_{k}_{lvl}.png", f"{variants[k]['label']} — {lvl} mesh (used by the study runs)")
    other = [p for p in sorted((RES / "visualizations" / "mesh").glob("*.png")) if f"_{lvl}." not in p.name]
    S.append(f"<section id='mesh'><h2>Mesh</h2><p>snappyHexMesh → checkMesh quality gate (non-orthogonality ≤ "
             f"{cfg['mesh']['checkmesh_limits']['max_non_orthogonality']}°, skewness ≤ {cfg['mesh']['checkmesh_limits']['max_skewness']}, "
             f"no failed checks). Study runs currently use the <b>{lvl}</b> level (PROVISIONAL until validation/04).</p>"
             + (table(pd.DataFrame(mrows)) if mrows else "") + f"<div class='gallery one'>{mimgs}</div>"
             + ("<details><summary>Other mesh levels</summary><div class='gallery one'>" + "".join(img(p, p.stem) for p in other) + "</div></details>" if other else "")
             + "</section>")

    # ---------------------------------------------------------------- airflow
    A = "<section id='airflow'><h2>Airflow</h2>"
    order = ["healthy_symmetric", "healthy_constant"] + [c for c in study_airflow if c != "healthy_symmetric"]
    any_af = False
    for c in order:
        qf = ROOT / "cases" / "airflow" / c / "qa_report.json"
        if not qf.exists():
            continue
        any_af = True
        q = json.loads(qf.read_text())
        v = RES / "visualizations" / c
        A += (f"<details {'open' if c == 'healthy_symmetric' else ''}><summary><b>{c}</b> {badge(q['status'])} "
              f"<span class='muted'>{q.get('wallclock_min', '?')} min wall-clock · {q.get('mesh_cells', '?'):,} cells</span></summary>"
              + kv(q, [("mean_inlet_flow_L_min", "mean inlet flow", "{:.3f} L/min"),
                       ("inspired_volume_mL", "inspired volume (whole run)", "{:.2f} mL"),
                       ("mean_imbalance_percent", "mean |Q_in − Q_out| / Q_in", "{:.2e} %"),
                       ("target_branch_ventilation_percent", "target branch share of flow", "{:.2f} %"),
                       ("comparison_branch_ventilation_percent", "comparison branch share", "{:.2f} %"),
                       ("peak_pressure_drop_Pa", "peak pressure drop", "{:.3f} Pa"),
                       ("mean_pressure_drop_Pa", "mean pressure drop", "{:.3f} Pa")])
              + ("<p class='bad-text'>" + html.escape("; ".join(q["problems"])) + "</p>" if q.get("problems") else "")
              + "<div class='gallery three'>"
              + img(v / "velocity_magnitude.png", "velocity magnitude (y = 0 section)")
              + img(v / "pressure.png", "pressure")
              + img(v / "streamlines.png", "streamlines")
              + "</div><div class='gallery two'>"
              + img(v / "flow_rates.png", "flow through each outlet over time")
              + img(v / "pressure_drop.png", "pressure drop over time")
              + img(v / "conservation.png", "inlet flow vs total outlet flow")
              + (img(v / "velocity_over_time.png", "velocity through the breath", "wide") if (v / "velocity_over_time.png").exists() else "")
              + f"</div><p class='muted'>ParaView: open <code>cases/airflow/{c}/case.foam</code>.</p></details>")
    if not any_af:
        A += "<p>No airflow case has run yet.</p>"
    S.append(A + "</section>")

    # ---------------------------------------------------------------- breathing
    rw = pd.read_csv(ROOT / "waveforms" / "release_windows.csv")
    rw = rw[["waveform", "strategy", "F_start", "F_end", "t_start_s", "t_end_s", "duration_s"]]
    S.append("<section id='breathing'><h2>Breathing waveforms &amp; release timing</h2>"
             f"<p>Inhalation {cfg['breathing']['inhalation_duration_s']} s, mean {cfg['breathing']['mean_flow_L_per_min']} L/min, "
             f"equal inspired volume for all three shapes, then {cfg['breathing']['post_inhalation_s']} s with zero inlet flow. "
             "Release windows are defined by the fraction F of inspired volume and converted to clock time per waveform.</p>"
             "<div class='gallery one'>" + img(RES / "figures" / "breathing_waveforms.png", "Beta(2,5) / Beta(3,3) / Beta(5,2) waveforms")
             + img(RES / "figures" / "release_windows.png", "flow, cumulative volume and release windows") + "</div>"
             + table(rw, {"t_start_s": "{:.3f}", "t_end_s": "{:.3f}", "duration_s": "{:.3f}", "F_start": "{:.2f}", "F_end": "{:.2f}"}) + "</section>")

    # ---------------------------------------------------------------- particles
    P = "<section id='particles'><h2>Particles</h2>"
    rcsv = RES / "results.csv"
    res = pd.read_csv(rcsv) if rcsv.exists() and rcsv.stat().st_size > 0 else pd.DataFrame()
    if res.empty:
        P += "<p>No particle case has completed yet.</p>"
    else:
        cols = ["case_id", "target_delivery_percent", "target_deposition_percent", "upstream_deposition_percent",
                "constriction_deposition_percent", "comparison_branch_deposition_percent", "target_outlet_escape_percent",
                "comparison_outlet_escape_percent", "suspended_percent", "mass_balance_error_percent", "arrival_time_mean", "qa_status"]
        P += "<p>All percentages are of the introduced aerosol mass. Target delivery = mass whose <i>first</i> crossing of the target-entry plane was recorded (transport measure; not part of the mass balance).</p>"
        P += table(res[cols], {c: "{:.2f}" for c in cols if c.endswith("percent")} | {"mass_balance_error_percent": "{:.1e}", "arrival_time_mean": "{:.3f} s"})
        for _, r in res.iterrows():
            c = r.case_id; v = RES / "visualizations" / c
            P += (f"<details {'open' if c == DEV_CASE else ''}><summary><b>{c}</b> {badge(r.qa_status)} "
                  f"<span class='muted'>target delivery <b>{r.target_delivery_percent:.2f} %</b> · mass-balance error {r.mass_balance_error_percent:.1e} %</span></summary>"
                  + (f"<p class='bad-text'>{html.escape(str(r.qa_notes))}</p>" if isinstance(r.qa_notes, str) and r.qa_notes else "")
                  + "<div class='gallery two'>" + img(v / "particle_trajectories.png", "trajectories and final particle positions")
                  + img(v / "mass_budget.png", "mass budget over time") + img(v / "arrival_times.png", "arrival-time distribution at target plane")
                  + "</div></details>")
    S.append(P + "</section>")

    # ---------------------------------------------------------------- validation
    V = "<section id='validation'><h2>Validation framework</h2><p>Each study is run with <code>python scripts/run_validation.py &lt;study&gt;</code>. Status below is read from <code>validation/*/results/</code>.</p><div class='tw'><table><thead><tr><th>#</th><th>study</th><th>status</th><th>key numbers</th></tr></thead><tbody>"
    vdirs = sorted((ROOT / "validation").glob("0*"))
    for vd in vdirs:
        sfiles = sorted((vd / "results").glob("*summary.json")) if (vd / "results").exists() else []
        if sfiles:
            data = {}
            for f in sfiles:
                data.update(json.loads(f.read_text()))
            keys = {k: v for k, v in data.items() if not isinstance(v, (list, dict))}
            txt = ", ".join(f"{k} = {v:.4g}" if isinstance(v, float) else f"{k} = {v}" for k, v in list(keys.items())[:9])
            stat = "ran (review)"
        else:
            txt, stat = "", "prepared, not run"
        V += f"<tr><td>{vd.name[:2]}</td><td>{vd.name[3:].replace('_', ' ')}</td><td>{badge(stat)}</td><td class='small'>{html.escape(txt)}</td></tr>"
    V += "</tbody></table></div>"
    for p in sorted((ROOT / "validation").glob("0*/results/*.png")):
        V += img(p.resolve(), p.parent.parent.name) if False else ""
    vimgs = "".join(f"<figure><a href='../{p.relative_to(ROOT).as_posix()}' target='_blank'><img src='../{p.relative_to(ROOT).as_posix()}'></a>"
                    f"<figcaption>{p.parent.parent.name}</figcaption></figure>" for p in sorted((ROOT / "validation").glob("0*/results/*.png")))
    S.append(V + (f"<div class='gallery two'>{vimgs}</div>" if vimgs else "") + "</section>")

    # ---------------------------------------------------------------- settings
    a = cfg["airflow"]; p = cfg["particles"]
    rows = [("Solver (air)", "pimpleFoam, laminar", "DERIVED — max Re ≈ 970"),
            ("Inlet profile", a["inlet_profile"], "PROVISIONAL"), ("Outlet BC", "equal static pressure (p = 0)", "PROVISIONAL — validation 09"),
            ("Mesh level", cfg["mesh"]["level"], "PROVISIONAL — validation 04"),
            ("Max Courant / outer correctors", f"{a['max_courant']} / {a['n_outer_correctors']}", "PROVISIONAL — validation 05"),
            ("Airflow snapshot interval", f"{a['write_interval_s']} s", "PROVISIONAL"),
            ("Particle solver", "airwayParcelFoam (custom, one-way, reads stored airflow)", "CHOICE"),
            ("Forces", "Schiller–Naumann drag + gravity " + str(p["gravity"]), "gravity direction PROVISIONAL"),
            ("Cunningham slip", str(p["cunningham_slip"]), "DERIVED — +17 % τ at 1 µm"),
            ("Brownian diffusion", str(p["brownian"]), "DERIVED — negligible"),
            ("Wall interaction", p["wall_interaction"], "CHOICE"), ("Parcels per case", str(p["parcels_per_case"]), "PROVISIONAL — validation 06"),
            ("Introduced mass (every case)", f"{p['introduced_mass_kg']:g} kg", "CHOICE"),
            ("Cloud time step", f"{p['tracking_dt_s']} s", "PROVISIONAL — validation 05"),
            ("Target entry plane", f"s = {cfg['regions']['target_plane_s_mm']} mm along target branch", "CHOICE")]
    S.append("<section id='settings'><h2>Model settings</h2>" + table(pd.DataFrame(rows, columns=["setting", "value", "basis"]))
             + "<p>Full reasoning: <a href='../docs/MODEL_DECISIONS.md'>docs/MODEL_DECISIONS.md</a> · all values live in <code>config/experiment.yaml</code>.</p></section>")

    # ---------------------------------------------------------------- run table
    sdf = pd.DataFrame(list(st.values()))
    if not sdf.empty:
        sdf = sdf[sdf.case_id.isin(set(matrix.case_id)) == False].sort_values(["case_type", "case_id"]).pipe(  # noqa: E712
            lambda d: pd.concat([d, pd.DataFrame([v for v in st.values() if v["case_id"] in p_ids and v.get("particle_status") not in ("generated", "")])]))
        sdf = sdf.drop(columns=["updated"], errors="ignore")
    S.append("<section id='runs'><h2>All runs (from results/run_status.csv)</h2><p class='muted'>Generated-but-not-run particle cases are omitted here; they appear in the grid above.</p>"
             + (table(sdf) if not sdf.empty else "") + "</section>")

    css = """
:root{--bg:#f7f8fa;--fg:#1d2433;--muted:#667085;--card:#fff;--line:#e3e7ee;--accent:#2a9d8f;--ok:#2e7d32;--okbg:#e6f4ea;--bad:#c62828;--badbg:#fdecea;
--run:#1565c0;--runbg:#e3f0fd;--warn:#b26a00;--warnbg:#fff4e0;--na:#7a8394;--nabg:#eef0f4;--gen:#d6dbe4}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#11151c;--fg:#e6e9ef;--muted:#9aa4b2;--card:#1a2029;--line:#2b3340;
--okbg:#163a20;--badbg:#4a1c1c;--runbg:#16304d;--warnbg:#45330f;--nabg:#262d38;--gen:#3a4352}}
:root[data-theme="dark"]{--bg:#11151c;--fg:#e6e9ef;--muted:#9aa4b2;--card:#1a2029;--line:#2b3340;--okbg:#163a20;--badbg:#4a1c1c;--runbg:#16304d;--warnbg:#45330f;--nabg:#262d38;--gen:#3a4352}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header,section,.banner,.cards,nav{max-width:1240px;margin:0 auto;padding:0 16px}header{padding-top:28px}h1{margin:0;font-size:1.7rem}
.sub{color:var(--muted);margin:4px 0 14px}h2{margin-top:36px;border-bottom:2px solid var(--line);padding-bottom:6px}h3{margin-top:22px}
.banner{background:var(--warnbg);border-left:4px solid var(--warn);padding:10px 14px;border-radius:6px;max-width:1208px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:16px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.card .n{font-size:1.8rem;font-weight:700}.card .l{color:var(--muted);font-size:.85rem}.card.alert{border-color:var(--bad);background:var(--badbg)}
nav{display:flex;flex-wrap:wrap;gap:6px;margin-top:16px;position:sticky;top:0;background:var(--bg);padding-top:8px;padding-bottom:8px;z-index:5;border-bottom:1px solid var(--line)}
nav a{color:var(--fg);text-decoration:none;background:var(--card);border:1px solid var(--line);padding:4px 10px;border-radius:999px;font-size:.85rem}
a{color:var(--accent)}code{background:var(--nabg);padding:1px 5px;border-radius:4px;font-size:.88em}
.gallery{display:grid;gap:14px;margin:12px 0}.gallery.one{grid-template-columns:1fr}.gallery.two{grid-template-columns:repeat(auto-fit,minmax(min(480px,100%),1fr))}
.gallery.three{grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr))}figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px}
figure img{width:100%;height:auto;display:block;border-radius:4px;background:#fff}figcaption{color:var(--muted);font-size:.85rem;margin-top:4px}
figure.missing div{padding:40px;text-align:center;color:var(--muted)}figure.wide{grid-column:1/-1}
.tw{overflow-x:auto;margin:10px 0}table{border-collapse:collapse;width:100%;font-size:.85rem;background:var(--card)}th,td{border:1px solid var(--line);padding:4px 7px;text-align:left;white-space:nowrap}
th{background:var(--nabg)}tr.failrow td{background:var(--badbg)}td.small{white-space:normal;font-size:.8rem}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:.78rem;font-weight:600}.badge.ok{background:var(--okbg);color:var(--ok)}
.badge.bad{background:var(--badbg);color:var(--bad)}.badge.run{background:var(--runbg);color:var(--run)}.badge.warn{background:var(--warnbg);color:var(--warn)}.badge.na{background:var(--nabg);color:var(--na)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:12px 0}summary{cursor:pointer}
.muted{color:var(--muted)}.bad-text{color:var(--bad);font-weight:600}.ok-text{color:var(--ok)}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:2px 16px;margin:10px 0}.kv dt{color:var(--muted)}.kv dd{margin:0;font-weight:600}
.grid3{display:grid;grid-template-columns:150px repeat(3,minmax(0,1fr));gap:6px;max-width:760px}.gh{font-size:.8rem;color:var(--muted);align-self:end}.gh.l{align-self:center}
.gc{padding:10px 6px;border-radius:6px;text-align:center;font-size:.8rem;font-family:ui-monospace,monospace;overflow:hidden;text-overflow:ellipsis}
.pgrid td{width:22px;height:22px;padding:0;text-align:center;font-size:.75rem}.pgrid th{font-size:.7rem;padding:3px}
.g-ok{background:var(--okbg);color:var(--ok)}.g-fail{background:var(--bad)!important;color:#fff}.g-run{background:var(--runbg)}.g-gen{background:var(--gen)}.g-block{background:var(--warnbg)}.g-none{background:var(--nabg)}
.legend{font-size:.8rem;color:var(--muted);margin:6px 0}.legend span{display:inline-block;width:14px;height:14px;border-radius:3px;vertical-align:middle;margin:0 4px 0 10px;border:1px solid var(--line)}
.failbox{background:var(--badbg);border:1px solid var(--bad);border-radius:8px;padding:8px 14px}footer{max-width:1240px;margin:40px auto;padding:0 16px;color:var(--muted);font-size:.8rem}
"""
    doc = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Airway CFD Report</title><style>{css}</style></head><body>{''.join(S)}"
           f"<footer>Built by scripts/build_report.py from results/run_status.csv, results/results.csv, cases/*/qa_report.json and results/visualizations/.</footer></body></html>")
    OUT.write_text(doc)
    print(f"[ok] {OUT.relative_to(ROOT)}  (airflow {len(af_done)}/9, particles {len(p_done)}/144, failed {len(all_fail)})")


if __name__ == "__main__":
    main()
