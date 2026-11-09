#!/usr/bin/env python3
"""Run the rest of the v002 study on ONE desktop: AMD Ryzen 9 9950X3D (16 cores / 32 threads, two 8-core CCDs, the
first with 3D V-Cache), 64 GB DDR5, Linux or Windows 11 + WSL2. Same Docker image, solvers, meshes, tolerances, physics,
QA and gates as the Mac and cloud paths; only the core layout and the scheduler settings differ.

    python3 local/desktop.py check        # hardware, Docker image, Python env, toolchain identity (E1)    ~2 min
    python3 local/desktop.py stage1       # fine-mesh verification (resumed from the Mac's t = 0.52 s state)
                                          #   on the V-Cache CCD, desktop benchmark + equivalence tests on the
                                          #   other CCD; after the fine case: scaling/concurrency + E6       ~10-16 h
    python3 local/desktop.py production   # whole study on the approved mesh (refused until MESH_DECISION approved)
    python3 local/desktop.py status       # progress
    python3 local/desktop.py stop         # graceful stop: solvers save their state and exit; re-run to resume

Start long commands with  bash local/run.sh <command>  (runs in the background, survives closing the terminal).

The RTX 5090 is not used: pimpleFoam (OpenFOAM v2406) and the airwayParcelFoam particle solver are CPU-only codes, and
moving them to a GPU would change the linear solvers / numerics, which the study protocol does not allow.

Hyper-threading: only one thread per physical core is used (cloud/runner/cloud_runner.core_groups). CFD is limited by
memory bandwidth (two DDR5 channels here), so sibling threads would slow both ranks down.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "cloud" / "runner"))
sys.path.insert(0, str(ROOT / "cloud" / "bench"))
OUT = ROOT / "cloud" / "results" / "desktop_benchmark"
DRAIN = ROOT / "DRAIN"
os.environ.setdefault("AIRWAY_DRAIN_FILE", str(DRAIN))   # graceful stop signal read by every airflow job
os.environ["AIRWAY_NO_SYNC"] = "1"                       # no S3 on the desktop
FINE = "V_MESH_fine_T_N40_SYM"
EQ = "D_EQ_medium_T_N40_SYM"                             # desktop complete-case equivalence run (E6)
PY = sys.executable

from cloud_runner import core_groups, cpuset, group_l3_kb  # noqa: E402


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} DESKTOP {msg}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "desktop.log", "a") as fh:
        fh.write(line + "\n")


def layout():
    """(fine/long-case group, benchmark group): the V-Cache CCD (largest L3) runs the long case."""
    g = core_groups()
    if len(g) < 2:
        sys.exit(f"expected 2 core groups (CCDs), found {g}; set AIRWAY_CORE_GROUPS='0-7;8-15' (see local/README.md)")
    l3 = group_l3_kb(g)
    big = max(range(len(g)), key=lambda i: l3[i] or 0)
    other = [i for i in range(len(g)) if i != big][0]
    return g[big], g[other], l3


# ------------------------------------------------------------------ check
def check():
    g = core_groups()
    l3 = group_l3_kb(g)
    mem = {ln.split(":")[0]: int(ln.split()[1]) for ln in open("/proc/meminfo")} if Path("/proc/meminfo").exists() else {}
    free_gb = shutil.disk_usage(ROOT).free / 1e9
    res = {"core_groups": g, "l3_kib": l3, "physical_cores_used": sum(map(len, g)), "logical_cpus": os.cpu_count(),
           "mem_total_GiB": round(mem.get("MemTotal", 0) / 2**20, 1), "disk_free_GB": round(free_gb, 1),
           "project_path": str(ROOT)}
    problems = []
    if [len(x) for x in g] != [8, 8]:
        problems.append(f"expected 2 groups of 8 physical cores, got {[len(x) for x in g]} (set AIRWAY_CORE_GROUPS)")
    if res["mem_total_GiB"] and res["mem_total_GiB"] < 40:
        problems.append(f"only {res['mem_total_GiB']} GiB visible to Linux (WSL2: set memory=56GB in .wslconfig)")
    if free_gb < 250:
        problems.append(f"only {free_gb:.0f} GB free disk; the medium study needs ~120 GB, fine ~250 GB")
    if str(ROOT).startswith("/mnt/"):
        problems.append("project is on a Windows drive (/mnt/...): copy it into the WSL2 home folder (10x faster disk)")
    import bench as B
    B.OUT = OUT
    OUT.mkdir(parents=True, exist_ok=True)
    res["E1_toolchain_identity"] = B.stage_E1("E1_desktop")
    if not res["E1_toolchain_identity"]:
        problems.append("E1 toolchain identity FAILED - see cloud/results/desktop_benchmark/E1_desktop.json")
    for need in (f"cases/airflow/{FINE}/processor7/0.52/U", "cases/airflow/V_MESH_medium_T_N40_SYM/1.02/U",
                 "cases/mesh/n40_fine", "cases/mesh/n40_medium", "cases/particles/MAP_V_MESH_medium_T_N40_SYM_P03/results.json"):
        if not (ROOT / need).exists():
            problems.append(f"missing data: {need} (unpack the data bundle, local/README.md step 4)")
    res["problems"] = problems
    res["ok"] = not problems
    (OUT / "check.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    print("\nCHECK", "PASSED" if res["ok"] else "FAILED")
    return 0 if res["ok"] else 3


# ------------------------------------------------------------------ stage 1
def run(cmd, cores, logname, extra_env=None):
    env = {**os.environ, "AIRWAY_DOCKER_ARGS": f"--cpuset-cpus={cpuset(cores)}", **(extra_env or {})}
    with open(OUT / f"{logname}.out", "a") as fh:
        return subprocess.run(cmd, cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode


def fine_job(cores):
    """Resume the Mac's fine-mesh case from its last complete save (t = 0.52 s, 8 ranks: same decomposition, exact
    restart), finish + QA + snapshot-grid check (cloud/runner/job_airflow.py), then the 1/3/5 um maps."""
    d = ROOT / "cases" / "airflow" / FINE
    ck = d / "cloud_checkpoint.json"
    if not ck.exists() and (d / "processor0").exists():
        ck.write_text(json.dumps({"ranks": 8, "level": "fine", "parts": 1, "started": "Mac (2026-11-06)",
                                  "host": "MacBook Pro i9-9880H", "note": "parts 1 = Mac run to t = 0.52 s (power loss)"}, indent=2))
    log(f"fine-mesh case: resume on cores {cpuset(cores)}")
    t0 = time.time()
    rc = run([PY, "cloud/runner/job_airflow.py", "T_N40_SYM", "--as", FINE, "--level", "fine", "--ranks", "8",
              "--allow-unapproved"], cores, "fine_airflow")
    log(f"fine-mesh airflow exit {rc} after {(time.time() - t0) / 3600:.2f} h")
    if rc != 0:
        return rc
    rc = run([PY, "scripts/run_fine_mesh_check.py"], cores, "fine_maps")     # airflow already PASSED -> maps only
    log(f"fine-mesh maps exit {rc}; total {(time.time() - t0) / 3600:.2f} h")
    (OUT / "fine_done.json").write_text(json.dumps({"rc": rc, "hours": (time.time() - t0) / 3600}))
    return rc


def bench_during_fine(B, cores):
    """Equivalence tests + rank scaling on the 8 cores the fine case does not use."""
    if not B.stage_E1("E1_desktop"):
        log("E1 FAILED: toolchain differs from the Mac - stopping the benchmark")
        return False
    # E2 (particle solver, 1 core) + E3 (mesh reproducibility, 1 core) together; GROUPS[-1] = this group (set below)
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(lambda f: f(), (B.stage_E2, B.stage_E3)))
    rows = B.load("D_E4") or []
    done = {r["case"] for r in rows}
    plan = [("seg_1_r1", "1", 1, cores[:1]), ("seg_1_r4", "1", 4, cores[:4]), ("seg_1_r7", "1", 7, cores[:7]),
            ("seg_1_r8", "1", 8, cores[:8]), ("seg_0.24_r7", "0.24", 7, cores[:7]), ("seg_2_r7", "2", 7, cores[:7])]
    for name, ph, r, cs_ in plan:
        if name in done:
            continue
        rows.append(B.run_segment(name, ph, B.PHASES[ph], r, cs_))
        B.save("D_E4", rows)
        log(f"{name}: {rows[-1].get('s_per_step', float('nan')):.3f} s/step, U vs Mac {rows[-1].get('vs_mac', {}).get('U', {}).get('rel_l2')}")
    if not B.have("D_E5"):
        B.save("D_E5", B.run_segment("E5_restart_1_r7", "1", "1.02", 7, cores[:7], stop_after=60))
        log("E5 interruption/restart segment done")
    return True


def bench_after_fine(B, gA, gB):
    """Whole-machine layouts (needs both CCDs), each leaving 1 core per CCD for the particle queue:
    1 case x 14 ranks (7 per CCD) vs 2 cases x 7 ranks (one per CCD), same segment -> production layout."""
    if B.have("D_B3"):
        return
    res = []
    for K, R in ((1, 14), (2, 7)):
        sets = [gA[:7] + gB[:7]] if K == 1 else [gA[:7], gB[:7]]
        t0 = time.time()
        with ThreadPoolExecutor(K) as ex:
            rows = list(ex.map(lambda k: B.run_segment(f"conc_{K}x{R}_{k}", "1", "1.02", R, sets[k]), range(K)))
        sps = [r.get("s_per_step", float("nan")) for r in rows]
        res.append({"K": K, "R": R, "wall_s": time.time() - t0, "s_per_step": sps, "cases_per_unit_time": K / max(sps),
                    "max_rel_l2_U_vs_mac": max(r.get("vs_mac", {}).get("U", {}).get("rel_l2", 9) for r in rows)})
        log(f"layout {K}x{R}: s/step {sps}")
    B.save("D_B3", res)


def e6_job(cores):
    """Complete medium T_N40_SYM case at the production rank count (7) + 1/3/5 um maps -> E6 vs the Mac case."""
    f = OUT / "D_E6_started.json"
    if (ROOT / "cases/particles" / f"MAP_{EQ}_P05" / "results.json").exists():
        return 0
    if not f.exists():
        f.write_text(json.dumps({"started": time.time(), "cores": cpuset(cores)}))
    rc = run([PY, "cloud/runner/job_airflow.py", "T_N40_SYM", "--as", EQ, "--level", "medium", "--ranks", "7",
              "--allow-unapproved"], cores, "e6_airflow")
    if rc == 0:
        rc = run([PY, "cloud/runner/job_maps.py", EQ, "--condition", "T_N40_SYM", "--sizes", "1", "3", "5"], cores, "e6_maps")
    return rc


def summary(B):
    import equivalence as Q
    import numpy as np
    Q.EQ_CASE = EQ
    shutil.copy(OUT / "D_E6_started.json", OUT / "B5_started.json") if (OUT / "D_E6_started.json").exists() else None
    e4 = B.load("D_E4") or []
    e5 = B.load("D_E5")
    tol = 1e-4

    def ok(r):
        v = r.get("vs_mac", {})
        return all(v.get(k, {}).get("rel_l2", 9) <= tol for k in ("U", "p")) and \
            v.get("U", {}).get("rel_l2", 9) <= 0.1 * r.get("segment_change_U", 0)
    E6 = Q.e6(OUT)
    tests = {"E1": (B.load("E1_desktop") or {}).get("pass"), "E2": (B.load("E2") or {}).get("pass"),
             "E3": (B.load("E3") or {}).get("pass"), "E4": bool(e4) and all(ok(r) for r in e4),
             "E5": None, "E6": E6.get("pass") if E6.get("available") else None}
    b3 = B.load("D_B3")
    rec = {"ranks": 7, "particle_cores": 2, "why": "default: one airflow case per CCD (7 cores) + 1 particle core per CCD"}
    if b3:
        best = max(b3, key=lambda x: x["cases_per_unit_time"])
        rec["ranks"] = best["R"]
        rec["why"] = f"{best['K']} x {best['R']} measured fastest (throughput {[round(x['cases_per_unit_time'], 3) for x in b3]})"
    # E5: interrupted + resumed vs the uninterrupted 7-rank segment (same as the cloud rule)
    if e5:
        from foam_field import compare_time
        c = compare_time(B.BENCH / e5["case"], B.BENCH / "seg_1_r7", "1.02")
        e5 = {**e5, "vs_uninterrupted": c}
        e5_pass = (e5.get("interrupted_at") not in (None, "1.02") and c.get("U", {}).get("rel_l2", 9) <= tol
                   and c.get("p", {}).get("rel_l2", 9) <= tol)
        tests["E5"] = e5_pass
    # desktop vs Mac speed: same phase, same 8 ranks (Mac medium case, steps between t = 1.00 and 1.02)
    mac = None
    ml = ROOT / "cases/airflow/V_MESH_medium_T_N40_SYM/logs/pimpleFoam.log"
    if ml.exists():
        t = ml.read_text(errors="ignore")
        ex = []
        for blk in t.split("\nTime = ")[1:]:
            T = float(blk.split("\n", 1)[0])
            import re
            m = re.search(r"ExecutionTime = ([\d.]+) s", blk)
            if m and 1.0 < T <= 1.02 + 1e-9:
                ex.append(float(m.group(1)))
        if len(ex) > 3:
            mac = float(np.mean(np.diff(ex)))
    r8 = [r for r in e4 if r["case"] == "seg_1_r8" and "s_per_step" in r]
    speed = {"mac_s_per_step_8r_t1": mac, "desktop_s_per_step_8r_t1": r8[0]["s_per_step"] if r8 else None}
    if mac and r8:
        speed["desktop_speedup_vs_mac_8_ranks"] = mac / r8[0]["s_per_step"]
    res = {"tests": tests, "required_pass": all(tests.get(k) for k in ("E1", "E2", "E4", "E5", "E6")),
           "E4": e4, "E5": e5, "E6": E6, "layouts": b3, "speed": speed, "production_layout": rec}
    B.save("summary", res)
    L = ["# Desktop benchmark (Ryzen 9 9950X3D) - equivalence with the Mac reference", "",
         "Thresholds: cloud/EQUIVALENCE_CRITERIA.md (fixed before any run; identical for the desktop).", "",
         "| Test | Result |", "|---|---|"]
    L += [f"| {k} | {'PASS' if v else ('not run yet' if v is None else 'FAIL')} |" for k, v in tests.items()]
    L += ["", f"Required tests (E1, E2, E4, E5, E6) all pass: **{res['required_pass']}**", "",
          "| Segment | Ranks | s/step | U rel L2 vs Mac | p rel L2 vs Mac |", "|---|---|---|---|---|"]
    for r in e4 + ([e5] if e5 else []):
        v = r.get("vs_mac", {})
        L.append(f"| {r['case']} | {r['ranks']} | {r.get('s_per_step', float('nan')):.3f} | {v.get('U', {}).get('rel_l2', float('nan')):.2e} | "
                 f"{v.get('p', {}).get('rel_l2', float('nan')):.2e} |")
    L += ["", f"Speed (same 8-rank segment): {json.dumps(speed)}", "",
          f"Production layout: --ranks {rec['ranks']} --particle-cores {rec['particle_cores']} ({rec['why']})"]
    (OUT / "SUMMARY.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    return res


def stage1():
    import bench as B
    gA, gB, l3 = layout()
    B.OUT, B.BENCH = OUT, ROOT / "cases" / "bench_desktop"
    B.GROUPS = [gA, gB]               # bench helpers put E2/E3 on GROUPS[-1] = the benchmark CCD
    OUT.mkdir(parents=True, exist_ok=True)
    B.BENCH.mkdir(parents=True, exist_ok=True)
    DRAIN.unlink(missing_ok=True)
    log(f"stage 1: fine case on {cpuset(gA)} (L3 {l3}), benchmark on {cpuset(gB)}")
    sampler = B.Sampler(OUT / "system_samples.csv").start()
    import run_particle_cases as RP
    from lib.common import load_config
    RP.ensure_solver(load_config())
    fine_rc = {}
    th = threading.Thread(target=lambda: fine_rc.update(rc=fine_job(gA)))
    th.start()
    sampler.tag = "fine+bench"
    ok = bench_during_fine(B, gB)
    if ok:
        sampler.tag = "fine+E6"
        e6_rc = e6_job(gB)            # complete medium case on the benchmark CCD while the fine case continues
        log(f"E6 complete medium case exit {e6_rc}")
    th.join()
    if DRAIN.exists():
        log("stopped on request (DRAIN); run stage1 again to resume")
        return 75
    if ok:
        sampler.tag = "layouts"
        bench_after_fine(B, gA, gB)
        summary(B)
    sampler.stop.set()
    log(f"stage 1 finished: fine rc {fine_rc.get('rc')}; next: medium-vs-fine comparison and the mesh decision")
    return 0 if fine_rc.get("rc") == 0 and ok else 2


# ------------------------------------------------------------------ production
def production():
    import yaml
    md = ROOT / "validation/04_mesh_independence/results/MESH_DECISION.json"
    d = json.loads(md.read_text()) if md.exists() else {}
    lvl = yaml.safe_load((ROOT / "config/experiment.yaml").read_text())["mesh"]["level"]
    if d.get("approved") is not True or d.get("production_level") != lvl:
        sys.exit(f"refused: production mesh not approved (MESH_DECISION approved={d.get('approved')}, "
                 f"production_level={d.get('production_level')}, config mesh.level={lvl})")
    s = json.loads((OUT / "summary.json").read_text()) if (OUT / "summary.json").exists() else {}
    if not s.get("required_pass"):
        sys.exit("refused: desktop equivalence tests (E1, E2, E4, E5, E6) have not all passed - see SUMMARY.md")
    rec = s["production_layout"]
    DRAIN.unlink(missing_ok=True)
    # both measured layouts leave one core per CCD to the particle queue (16 = 2 x 7 + 2 or 14 + 2)
    args = ["--ranks", str(rec["ranks"]), "--particle-cores", "2", "--spread-particles"]
    log(f"production: cloud/runner/cloud_runner.py {' '.join(args)} (mesh {lvl})")
    return subprocess.run([PY, "cloud/runner/cloud_runner.py", *args], cwd=ROOT).returncode


# ------------------------------------------------------------------ status / stop
def status():
    for f in (ROOT / "logs/cloud_status.json", OUT / "summary.json"):
        if f.exists():
            print(f"== {f.relative_to(ROOT)}")
            print(f.read_text()[:3000])
    d = ROOT / "cases/airflow" / FINE
    import job_airflow as J
    t = J.proc_times(d)
    if t:
        print(f"== fine-mesh case: latest saved time {t[-1][1]} s of 3.0 s")
    lf = OUT / "desktop.log"
    if lf.exists():
        print("== last log lines")
        print("\n".join(lf.read_text().splitlines()[-15:]))
    print("stop requested (DRAIN present)" if DRAIN.exists() else "")


def stop():
    DRAIN.write_text(time.strftime("%Y-%m-%d %H:%M:%S") + " stop requested by user\n")
    print("Stop requested: running solvers save their state (stopAt writeNow) and exit within ~1 min.\n"
          "Resume later with the same command (e.g. bash local/run.sh stage1).")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    fn = {"check": check, "stage1": stage1, "production": production, "status": status, "stop": stop}.get(cmd)
    if fn is None:
        sys.exit(__doc__)
    sys.exit(fn() or 0)
