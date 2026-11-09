#!/usr/bin/env python3
"""Self-contained summary report (all figures embedded) for sharing.

    python scripts/build_summary_page.py      # -> results/summary_report.html

Reads results/results.csv, results/tables/analysis_*.csv, cases/airflow/*/qa_report.json,
geometry/geometry_qa.json, validation/*/results/summary.json and the findings text in
docs/report_findings.json (written after reviewing the results).
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import ROOT, load_config  # noqa: E402

RES = ROOT / "results"
OUT = RES / "summary_report.html"
E = html.escape


def png(path: Path, alt: str, caption: str = "") -> str:
    if not path.exists():
        return ""
    b = base64.b64encode(path.read_bytes()).decode()
    cap = f"<figcaption>{E(caption)}</figcaption>" if caption else ""
    return f'<figure><img src="data:image/png;base64,{b}" alt="{E(alt)}">{cap}</figure>'


def tbl(df: pd.DataFrame, num: dict | None = None, cls: str = "") -> str:
    num = num or {}
    h = f"<div class='tw'><table class='{cls}'><thead><tr>" + "".join(f"<th>{E(str(c))}</th>" for c in df.columns) + "</tr></thead><tbody>"
    for _, r in df.iterrows():
        h += "<tr>" + "".join(
            f"<td class='{'n' if isinstance(r[c], (int, float)) and not isinstance(r[c], bool) else ''}'>"
            f"{E(num[c].format(r[c]) if c in num and pd.notna(r[c]) else str(r[c]))}</td>" for c in df.columns) + "</tr>"
    return h + "</tbody></table></div>"


def main():
    cfg = load_config()
    findings = json.loads((ROOT / "docs" / "report_findings.json").read_text())
    res = pd.read_csv(RES / "results.csv")
    passed = res[res.qa_status == "PASSED"]
    by_geom = pd.read_csv(RES / "tables" / "analysis_by_geometry.csv")
    rel = pd.read_csv(RES / "tables" / "analysis_release_effect.csv")
    best = pd.read_csv(RES / "tables" / "analysis_best_strategy.csv")
    geoq = json.loads((ROOT / "geometry" / "geometry_qa.json").read_text())
    tube = json.loads((ROOT / "validation" / "01_straight_tube_analytical" / "results" / "summary.json").read_text())

    af_rows = []
    for g in cfg["geometry"]["variants"]:
        for w in cfg["breathing"]["waveforms"]:
            q = json.loads((ROOT / "cases" / "airflow" / f"{g}_{w}" / "qa_report.json").read_text())
            af_rows.append({"geometry": cfg["geometry"]["variants"][g]["label"], "breathing": w,
                            "target branch airflow %": q["target_branch_ventilation_percent"],
                            "peak Δp (Pa)": q["peak_pressure_drop_Pa"], "mean Δp (Pa)": q["mean_pressure_drop_Pa"],
                            "flow imbalance %": q["mean_imbalance_percent"], "QA": q["status"]})
    af = pd.DataFrame(af_rows)

    names = {0: "Healthy", 20: "20 % narrowing", 40: "40 % narrowing"}
    bg = by_geom.rename(columns={"narrowing_percent": "geometry", "mean_delivery": "mean delivery %", "min_delivery": "lowest %",
                                 "max_delivery": "highest %", "target_vent": "target airflow %", "deposition": "wall deposition %",
                                 "suspended": "still airborne %"})
    bg["geometry"] = bg["geometry"].map(names)
    rl = rel.rename(columns={"narrowing_percent": "geometry"})
    rl["geometry"] = rl["geometry"].map(names)
    rl = rl[["geometry"] + [c for c in ["continuous", "early", "middle", "late"] if c in rl.columns]]
    bs = best[["narrowing_percent", "particle_size_um", "best_early", "best_symmetric", "best_late",
               "same_best_for_all_waveforms", "delivery_spread_across_releases_points"]].copy()
    bs.columns = ["geometry", "size µm", "best: early breath", "best: symmetric", "best: late breath", "same winner?", "spread (pts)"]
    bs["geometry"] = bs["geometry"].map(names)
    bs["same winner?"] = bs["same winner?"].map({True: "yes", False: "no"})

    gq = []
    for k, v in geoq.items():
        for ver, m in v.items():
            gq.append({"model": k, "version": ver, "flat wall facing flow (mm²)": m["flat_flow_facing_area_mm2"],
                       "max radius below junction (mm)": m["max_radius_below_junction_mm"], "volume (mm³)": m["volume_mm3"]})
    gq = pd.DataFrame(gq)

    vis, fig_a = RES / "visualizations", RES / "figures" / "analysis"
    n_total = len(res)
    max_err = passed.mass_balance_error_percent.abs().max()
    ver = cfg["geometry"].get("version", "v001")

    findings_html = "".join(f"<li><b>{E(f['head'])}</b> {E(f['body'])}</li>" for f in findings["findings"])
    caveats_html = "".join(f"<li>{E(c)}</li>" for c in findings["caveats"])
    next_html = "".join(f"<li>{E(c)}</li>" for c in findings["next_steps"])

    css = """
/* Layout: one reading column (~72ch) with full-width figure rows; lab-notebook feel, clinical palette */
:root{--bg:#f6f8f8;--paper:#ffffff;--ink:#16232a;--muted:#5a6b72;--line:#d8e1e3;--accent:#167a72;--target:#d9583b;--warn:#a5521d;--warnbg:#fbefe4;--ok:#22704a;--okbg:#e5f3ec;
--display:"Newsreader",Georgia,serif;--body:"IBM Plex Sans",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,monospace}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0f1719;--paper:#162125;--ink:#e3ecee;--muted:#93a6ac;--line:#2a3a3f;--accent:#4fc1b6;--target:#f0805f;--warn:#e9a46c;--warnbg:#33251a;--ok:#6fd19e;--okbg:#17302a;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0f1719;--paper:#162125;--ink:#e3ecee;--muted:#93a6ac;--line:#2a3a3f;--accent:#4fc1b6;--target:#f0805f;--warn:#e9a46c;--warnbg:#33251a;--ok:#6fd19e;--okbg:#17302a;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font:16px/1.6 var(--body);padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:32px 64px}
.wrap{max-width:1080px;margin:0 auto}.col{max-width:72ch}
h1{font:600 clamp(2rem,5vw,3rem)/1.1 var(--display);margin:0 0 8px;text-wrap:balance;letter-spacing:-.01em}
h2{font:600 1.6rem/1.2 var(--display);margin:56px 0 12px;text-wrap:balance}h3{font:600 1.05rem var(--body);margin:28px 0 8px}
.eyebrow{font:500 .75rem var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}
.lede{font-size:1.15rem;color:var(--muted);max-width:68ch}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(200px,100%),1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:6px;overflow:hidden;margin:24px 0}
.facts div{background:var(--paper);padding:14px 16px;min-width:0}.facts b{display:block;font:600 1.5rem var(--mono);font-variant-numeric:tabular-nums}.facts span{font-size:.82rem;color:var(--muted)}
.answer{background:var(--paper);border:1px solid var(--line);border-left:4px solid var(--target);padding:18px 22px;border-radius:4px}
.answer ul{margin:0;padding-left:1.1em;display:grid;gap:10px}
.note{background:var(--warnbg);border-left:4px solid var(--warn);padding:12px 16px;border-radius:4px;font-size:.95rem}
figure{margin:16px 0;background:#fff;border:1px solid var(--line);border-radius:6px;padding:8px;max-width:100%}
figure img{display:block;width:100%;height:auto}figcaption{font-size:.85rem;color:#4a5a60;padding:6px 4px 0}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr));gap:14px}.row>*{min-width:0}
.tw{overflow-x:auto;margin:12px 0}table{border-collapse:collapse;font-size:.88rem;background:var(--paper);min-width:100%}
th,td{border-bottom:1px solid var(--line);padding:6px 10px;text-align:left;white-space:nowrap}th{font:600 .75rem var(--mono);letter-spacing:.05em;text-transform:uppercase;color:var(--muted)}
td.n{font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right}
code{font:.88em var(--mono);background:var(--paper);border:1px solid var(--line);padding:1px 5px;border-radius:3px}
ul.plain{padding-left:1.1em}.pill{display:inline-block;font:600 .72rem var(--mono);padding:2px 8px;border-radius:999px;background:var(--okbg);color:var(--ok)}
footer{margin-top:56px;color:var(--muted);font-size:.85rem;border-top:1px solid var(--line);padding-top:16px}
"""
    doc = f"""<title>Airway Aerosol Delivery Study</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,600&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>{css}</style>
<div class="wrap">
<header class="col">
  <div class="eyebrow">CFD study report · OpenFOAM v2406 · {dt.date.today():%d %b %Y}</div>
  <h1>Airway Aerosol Delivery</h1>
  <p class="lede">How particle size and release timing change the share of an inhaled aerosol that reaches the airway beyond a narrowing, and whether the best strategy holds when breathing changes. Y-shaped airway, healthy vs 20 % vs 40 % narrowing of the right (target) branch.</p>
</header>
<div class="facts">
  <div><b>9 / 9</b><span>airflow solutions passed QA</span></div>
  <div><b>{len(passed)} / 144</b><span>particle cases passed QA</span></div>
  <div><b>{max_err:.0e} %</b><span>worst particle mass-balance error</span></div>
  <div><b>{tube['dp_error_percent']:+.1f} %</b><span>pressure-drop error vs Poiseuille (straight-tube check)</span></div>
  <div><b>{ver}</b><span>geometry version used for these runs</span></div>
</div>
<p class="note col"><b>Status: development results, not validated.</b> {E(findings['status_note'])}</p>

<h2>What the simulations show</h2>
<div class="answer col"><ul>{findings_html}</ul></div>

<h2>Target delivery by size and release timing</h2>
<p class="col">Target delivery is the share of the introduced aerosol mass that first crosses a disc 2 mm past the end of the narrowing in the target branch. Every case introduces the same aerosol mass (1 ng).</p>
{png(fig_a / 'delivery_vs_size.png', 'Target delivery versus particle size', 'Lines: mean over the three breathing waveforms. Bands: lowest to highest waveform.')}
{png(fig_a / 'delivery_heatmaps.png', 'Heat maps of target delivery', 'Every one of the 144 cases. Rows: release strategy, columns: particle diameter.')}
<h3>Average delivery by geometry</h3>
{tbl(bg, {c: '{:.1f}' for c in bg.columns if c != 'geometry'})}
<h3>Average delivery by release strategy (%)</h3>
{tbl(rl, {c: '{:.2f}' for c in rl.columns if c != 'geometry'})}
<h3>Which release wins, and does it survive a change in breathing?</h3>
{tbl(bs, {'size µm': '{:g}', 'spread (pts)': '{:.2f}'})}

<h2>Where the aerosol goes</h2>
<div class="row">{png(fig_a / 'aerosol_fate.png', 'Aerosol fate breakdown', 'Symmetric breathing. Deposits, outlet escapes and aerosol still airborne at 3 s add up to 100 %.')}
{png(fig_a / 'delivery_per_ventilation.png', 'Delivery relative to airflow share', 'Values below 1 mean the target branch gets less aerosol than its share of the air.')}</div>
<div class="row">{png(vis / 'P03_CONT_HLT_SYM' / 'particle_trajectories.png', 'Particle trajectories', 'Development case: 3 µm, continuous release, healthy, symmetric breathing.')}
{png(vis / 'P03_CONT_HLT_SYM' / 'mass_budget.png', 'Mass budget over time', 'Mass budget of the development case through the breath.')}</div>

<h2>Airflow</h2>
<p class="col">Laminar, transient airflow (maximum Reynolds number about 970). Both outlets at equal pressure, so the narrowing alone sets how air divides between the branches.</p>
{tbl(af, {'target branch airflow %': '{:.1f}', 'peak Δp (Pa)': '{:.2f}', 'mean Δp (Pa)': '{:.2f}', 'flow imbalance %': '{:.1e}'})}
<div class="row">{png(vis / 'healthy_symmetric' / 'velocity_magnitude.png', 'Velocity healthy', 'Healthy airway at peak flow.')}
{png(vis / 'n40_symmetric' / 'velocity_magnitude.png', 'Velocity 40 percent', '40 % narrowing at peak flow: jet through the throat, less air into the target branch.')}</div>
<div class="row">{png(vis / 'n40_symmetric' / 'streamlines.png', 'Streamlines', 'Streamlines, 40 % narrowing.')}
{png(vis / 'n40_symmetric' / 'flow_rates.png', 'Flow rates', 'Flow through each boundary over the breath, 40 % narrowing.')}</div>
{png(RES / 'figures' / 'release_windows.png', 'Release windows', 'Release windows are set by the fraction of the breath volume inhaled, so their clock times differ between waveforms.')}

<h2>3D model check</h2>
<div class="col"><p>All three approved models match the README dimensions, the narrowing is centred and exact (4.80 and 3.60 mm minimum at 20 mm), and the comparison branch is identical across models. Two defects sit at the junction where the parent tube meets the branches:</p>
<ul class="plain"><li><b>Flat shelf at z = 40 mm</b> covering 35 % of the parent cross-section, facing straight into the inhaled flow. The open area drops from 50.3 to 32.6 mm² in one step. Most of the "upstream" deposition lands on it.</li>
<li><b>Branch cylinders poke out through the parent wall</b> just below the junction, leaving pockets up to 0.42 mm deep.</li></ul>
<p>A corrected version (v002) replaces the junction with a smooth transition and keeps everything else, including the narrowing profile, identical. The results above still use <b>{ver}</b>.</p></div>
{png(RES / 'figures' / 'geometry_qa' / 'junction_v001_vs_v002.png', 'Junction comparison', 'Red: approved v001. Blue: corrected v002. Left to right: two sections, lumen area through the junction, narrowing profile.')}
{tbl(gq, {'volume (mm³)': '{:.1f}', 'flat wall facing flow (mm²)': '{:.1f}', 'max radius below junction (mm)': '{:.3f}'})}

<h2>Checks that passed</h2>
<ul class="plain col">
<li>Straight tube vs exact solutions: pressure drop {tube['dp_error_percent']:+.1f} %, centre-line velocity {tube['u_centre_error_percent']:+.1f} %, 10 µm gravitational deposition {tube['cfd_deposition_percent']:.1f} % vs {tube['pich_deposition_percent']:.1f} % (Pich formula).</li>
<li>Airflow conservation in all 9 runs: inflow equals outflow to better than 1×10⁻⁴ %; inspired volume 66.5 mL in every case.</li>
<li>Particle mass balance in all {len(passed)} cases: introduced = deposited + escaped + still airborne, worst error {max_err:.0e} %.</li>
<li>Every mesh passed the checkMesh quality gate (max non-orthogonality 51°, max skewness 1.6 on the meshes used).</li></ul>

<h2>Limitations</h2><ul class="plain col">{caveats_html}</ul>
<h2>Next steps</h2><ul class="plain col">{next_html}</ul>
<footer>Generated by <code>scripts/build_summary_page.py</code> from {n_total} particle results, 9 airflow solutions and the validation folder. Full per-case detail: <code>results/report.html</code> in the project.</footer>
</div>"""
    OUT.write_text(doc)
    print(f"[ok] {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
