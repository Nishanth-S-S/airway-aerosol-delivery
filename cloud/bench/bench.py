#!/usr/bin/env python3
"""Paid cloud benchmark + equivalence tests (one c7a.24xlarge, ~3-4 h). Restart-safe: finished stages are skipped.

    python3 cloud/bench/bench.py all            # everything, in the order below
    python3 cloud/bench/bench.py summary        # (re)build cloud/results/benchmark/summary.json from what exists

Stages (EQUIVALENCE_CRITERIA.md fixes the pass/fail thresholds):
  E1  toolchain identity (image digest, binary hashes, Python versions)
  E2  particle solver on the uploaded Mac airflow, same seed (MAP_V_MESH_medium_T_N40_SYM_P03)
  E3  snappyHexMesh n40/medium reproduced in a separate tree, compared with the Mac mesh
  B5  COMPLETE medium T_N40_SYM case (0-3 s, decomposition, solver, reconstruction, QA, 1/3/5 um maps) -> E6;
      started first, on its own L3 group, so its wall time is the real end-to-end figure under benchmark load
  B2  rank scaling: restart segments from the Mac state at t = 0.24, 1.00, 2.00 s (to the next 0.02 s write),
      1/2/4/8/16 ranks, measured per time step after warm-up -> E4 (fields vs the Mac's own fields)
  E5  interruption/restart: segment 1.00-1.02 s stopped by the Spot mechanism after 60 s and resumed
  B6  fine mesh: first 0.02 s from t = 0 with 8 ranks (same ranks as the Mac's running fine case -> direct
      per-step speed ratio cloud/Mac) and 24 ranks
  B3  concurrency: K simultaneous cases x R ranks (11x8, 14x6, 22x4, 7x12, 5x16 on the 88 cores not used by B5),
      CPU / memory / disk sampled every 5 s
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "cloud" / "runner"))
OUT = ROOT / "cloud" / "results" / "benchmark"
BENCH = ROOT / "cases" / "bench"
MAC_MED = ROOT / "cases" / "airflow" / "V_MESH_medium_T_N40_SYM"
IMAGE = os.environ.get("AIRWAY_DOCKER_IMAGE", "")
EQ_CASE = "C_EQ_medium_T_N40_SYM"
FINE_CASE = "C_FINE_T_N40_SYM"
BENCH_FINE = os.environ.get("BENCH_FINE", "0") == "1"   # also run the full fine-mesh verification case (32 ranks)


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} BENCH {msg}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "bench.log", "a") as fh:
        fh.write(line + "\n")


def save(name, obj):
    (OUT / f"{name}.json").write_text(json.dumps(obj, indent=2, default=float))


def have(name):
    return (OUT / f"{name}.json").exists()


def load(name):
    return json.loads((OUT / f"{name}.json").read_text()) if have(name) else None


# ------------------------------------------------------------------ cores (same grouping as the runner)
from cloud_runner import core_groups  # noqa: E402

GROUPS = core_groups()
N = len(GROUPS)
B5_GROUP, LAST_GROUP = N - 2, N - 1                                  # B5 full medium case; E2/E3 (short)
FINE_GROUPS = list(range(N - 6, N - 2)) if BENCH_FINE else []         # 4 groups = 32 cores for the fine case
FREE = [i for i in range(N) if i not in FINE_GROUPS and i != B5_GROUP]  # for B2 / E5 / B6 / B3


def cs(groups_idx, n=None):
    c = [x for i in groups_idx for x in GROUPS[i]]
    return c[:n] if n else c


def cpuset(c):
    return ",".join(map(str, c))


def foam(case: Path, command: str, cores, logname: str) -> tuple[int, float]:
    from lib.common import foam_cmd, load_config
    cmd = foam_cmd(load_config(), case, command)
    cmd.insert(cmd.index("--shm-size=1g") + 1, f"--cpuset-cpus={cpuset(cores)}")
    (case / "logs").mkdir(exist_ok=True)
    t0 = time.time()
    with open(case / "logs" / f"{logname}.log", "w") as fh:
        rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT).returncode
    return rc, time.time() - t0


# ------------------------------------------------------------------ system sampler
class Sampler:
    def __init__(self, path: Path):
        self.path, self.stop, self.tag = path, threading.Event(), "idle"

    def _cpu(self):
        v = [int(x) for x in open("/proc/stat").readline().split()[1:]]
        return sum(v), v[3] + v[4]

    def _disk(self):
        w = r = 0
        for ln in open("/proc/diskstats"):
            p = ln.split()
            if re.match(r"^(nvme\d+n\d+|xvd[a-z]|sd[a-z])$", p[2]):
                r += int(p[5]); w += int(p[9])
        return r * 512, w * 512

    def run(self):
        if not Path("/proc/stat").exists():
            return
        with open(self.path, "a") as fh:
            fh.write("time,tag,cpu_busy_percent,mem_used_GiB,mem_avail_GiB,disk_read_MBps,disk_write_MBps,load1\n")
            t0, (tot0, idle0), (r0, w0) = time.time(), self._cpu(), self._disk()
            while not self.stop.wait(5):
                t1, (tot1, idle1), (r1, w1) = time.time(), self._cpu(), self._disk()
                mem = {ln.split(":")[0]: int(ln.split()[1]) for ln in open("/proc/meminfo")}
                busy = 100 * (1 - (idle1 - idle0) / max(tot1 - tot0, 1))
                fh.write(f"{time.strftime('%H:%M:%S')},{self.tag},{busy:.1f},{(mem['MemTotal'] - mem['MemAvailable']) / 2**20:.2f},"
                         f"{mem['MemAvailable'] / 2**20:.2f},{(r1 - r0) / (t1 - t0) / 1e6:.2f},{(w1 - w0) / (t1 - t0) / 1e6:.2f},"
                         f"{open('/proc/loadavg').read().split()[0]}\n")
                fh.flush()
                t0, tot0, idle0, r0, w0 = t1, tot1, idle1, r1, w1

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
        return self


# ------------------------------------------------------------------ log parsing
def step_times(logf: Path, skip=10):
    """Per-step wall seconds (ExecutionTime deltas) after `skip` warm-up steps, plus start-up clock time."""
    t = logf.read_text(errors="ignore")
    ex, clk, pit = [], [], []
    for blk in t.split("\nTime = ")[1:]:
        m = re.search(r"ExecutionTime = ([\d.]+) s\s+ClockTime = ([\d.]+) s", blk)
        if m:
            ex.append(float(m.group(1))); clk.append(float(m.group(2)))
            pit.append(sum(int(x) for x in re.findall(r"Solving for p, .*No Iterations (\d+)", blk)))
    if len(ex) <= skip + 2:
        return None
    d = [b - a for a, b in zip(ex[skip:-1], ex[skip + 1:])]
    return {"steps": len(ex), "s_per_step": sum(d) / len(d), "p_iters_per_step": sum(pit[skip:]) / len(pit[skip:]),
            "startup_clock_s": clk[0], "total_clock_s": clk[-1], "finished": "\nEnd" in t}


# ------------------------------------------------------------------ restart segments from the Mac state
PHASES = {"0.24": "0.26", "1": "1.02", "2": "2.02"}


def make_segment(name: str, t0: str, t1: str, ranks: int) -> Path:
    d = BENCH / name
    if d.exists():                       # earlier attempt (e.g. before an interruption): keep it, never delete
        (BENCH / "_old").mkdir(parents=True, exist_ok=True)
        shutil.move(str(d), str(BENCH / "_old" / f"{name}_{int(time.time())}"))
    d.mkdir(parents=True)
    for sub in ("system", "constant"):
        shutil.copytree(MAC_MED / sub, d / sub)
    shutil.copytree(MAC_MED / t0, d / t0)
    shutil.copy(MAC_MED / "case_meta.json", d / "case_meta.json")
    cp = d / "system" / "caseParameters"
    txt = cp.read_text()
    txt = re.sub(r"^endTime\s+\S+;", f"endTime       {t1};", txt, flags=re.M)
    txt = re.sub(r"^nProcs\s+\S+;", f"nProcs   {ranks};", txt, flags=re.M)
    cp.write_text(txt)
    return d


def run_segment(name, t0, t1, ranks, cores, stop_after=None):
    d = make_segment(name, t0, t1, ranks)
    res = {"case": name, "t0": t0, "t1": t1, "ranks": ranks, "cores": cpuset(cores)}
    if ranks > 1:
        rc, res["decompose_s"] = foam(d, "decomposePar -force", cores, "decomposePar")
        cmd = f"mpirun -np {ranks} --oversubscribe pimpleFoam -parallel"
    else:
        cmd = "pimpleFoam"
    if stop_after:                       # E5: interruption via the production mechanism
        import job_airflow as J
        th = threading.Timer(stop_after, lambda: J.set_stop(d, "writeNow"))
        th.start()
        rc, w1 = foam(d, cmd, cores, "pimpleFoam_part1")
        th.cancel()
        J.set_stop(d, "endTime")
        times = J.proc_times(d) if ranks > 1 else []
        res["interrupted_at"] = times[-1][1] if times else None
        rc, w2 = foam(d, cmd, cores, "pimpleFoam")
        res["solve_wall_s"] = w1 + w2
        if ranks > 1:
            for t, nm in J.proc_times(d):
                if not J.on_grid(t):
                    J.quarantine(d, nm, ranks, "off-schedule checkpoint (E5 test)")
    else:
        rc, res["solve_wall_s"] = foam(d, cmd, cores, "pimpleFoam")
    res["solver_rc"] = rc
    if ranks > 1:
        _, res["reconstruct_s"] = foam(d, "reconstructPar -latestTime", cores, "reconstructPar")
    st = step_times(d / "logs" / "pimpleFoam.log")
    res.update(st or {"error": "no steps parsed"})
    from foam_field import compare_time, read_internal, rel_l2
    tname = t1 if (d / t1).exists() else None
    if tname:
        res["vs_mac"] = compare_time(d, MAC_MED, tname)
        res["segment_change_U"] = rel_l2(read_internal(MAC_MED / t1 / "U"), read_internal(MAC_MED / t0 / "U"))
    return res


# ------------------------------------------------------------------ stages
def stage_E1(name="E1"):
    if have(name):
        return load(name)["pass"]
    ref = json.loads((ROOT / "cloud" / "toolchain_reference.json").read_text())
    script = ("source /usr/lib/openfoam/openfoam2406/etc/bashrc >/dev/null 2>&1; cd $FOAM_APPBIN/..; "
              "sha256sum bin/pimpleFoam bin/decomposePar bin/reconstructPar bin/snappyHexMesh lib/libfiniteVolume.so "
              "lib/libOpenFOAM.so lib/liblagrangianIntermediate.so")
    out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "/bin/bash", IMAGE or ref["docker_image"], "-c", script],
                         capture_output=True, text=True).stdout
    got = {ln.split()[1]: ln.split()[0] for ln in out.splitlines() if len(ln.split()) == 2}
    digest = subprocess.run(["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", IMAGE or ref["docker_image"]],
                            capture_output=True, text=True).stdout.strip()
    import hashlib
    frozen = json.loads((ROOT / "geometry" / "FROZEN_v002.json").read_text())
    src_hash = hashlib.sha256((ROOT / "tools/openfoam/airwayParcelFoam/airwayParcelFoam.C").read_bytes()).hexdigest()
    cfg_hash = hashlib.sha256((ROOT / "config/conditions.yaml").read_bytes()).hexdigest()
    geo_ok = {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() == h for f, h in frozen["files"].items()}
    import matplotlib
    import numpy
    import pandas
    import scipy
    import yaml
    py = {"python": sys.version.split()[0], "numpy": numpy.__version__, "pandas": pandas.__version__, "scipy": scipy.__version__,
          "matplotlib": matplotlib.__version__, "pyyaml": yaml.__version__}
    binf = ROOT / "tools" / "openfoam" / "bin" / "airwayParcelFoam"
    res = {"binary_hashes": {k: {"cloud": got.get(k), "mac": v, "match": got.get(k) == v} for k, v in ref["sha256"].items() if k.startswith(("bin/", "lib/"))},
           "image_repo_digests": digest, "image_digest_expected": ref["docker_image"].split("@")[1],
           "python": {k: {"cloud": py[k], "mac": v, "match": py[k] == v} for k, v in ref["python"].items()},
           "airwayParcelFoam_binary_cloud_sha256": hashlib.sha256(binf.read_bytes()).hexdigest() if binf.exists() else None,
           "airwayParcelFoam_binary_mac_sha256": ref["sha256"]["airwayParcelFoam (built on the Mac from tools/openfoam/airwayParcelFoam)"],
           "particle_solver_source_matches_frozen": src_hash == frozen["solver_source_sha256"],
           "conditions_match_frozen": cfg_hash == frozen["conditions_sha256"],
           "geometry_files_match_frozen": all(geo_ok.values()), "geometry_mismatches": [f for f, ok in geo_ok.items() if not ok]}
    res["pass"] = (all(v["match"] for v in res["binary_hashes"].values()) and res["image_digest_expected"] in digest
                   and all(v["match"] for v in res["python"].values()) and res["particle_solver_source_matches_frozen"]
                   and res["conditions_match_frozen"] and res["geometry_files_match_frozen"])
    save(name, res)
    log(f"{name} toolchain identity: {'PASS' if res['pass'] else 'FAIL'}")
    return res["pass"]


def stage_E2():
    if have("E2"):
        return
    case = "E2_MAP_V_MESH_medium_T_N40_SYM_P03"
    r = subprocess.run([sys.executable, str(ROOT / "cloud/runner/job_maps.py"), "V_MESH_medium_T_N40_SYM", "--condition", "T_N40_SYM",
                        "--sizes", "3", "--case-id", case], cwd=ROOT,
                       env={**os.environ, "AIRWAY_DOCKER_ARGS": f"--cpuset-cpus={cpuset(cs([len(GROUPS) - 1], 1))}"})
    mac = json.loads((ROOT / "cases/particles/MAP_V_MESH_medium_T_N40_SYM_P03/results.json").read_text())
    f = ROOT / "cases/particles" / case / "results.json"
    cl = json.loads(f.read_text()) if f.exists() else {}
    keys = ["target_delivery_percent", "total_deposition_percent", "suspended_percent", "n_parcels", "mass_balance_error_percent"]
    res = {"rc": r.returncode, "mac": {k: mac.get(k) for k in keys}, "cloud": {k: cl.get(k) for k in keys}}
    res["max_abs_diff_pts"] = max(abs((cl.get(k) or 1e9) - mac[k]) for k in keys[:3]) if cl else None
    res["pass"] = bool(cl) and cl.get("n_parcels") == mac.get("n_parcels") and res["max_abs_diff_pts"] <= 0.01
    save("E2", res)
    log(f"E2 particle solver equivalence: {'PASS' if res['pass'] else 'FAIL'} (max diff {res['max_abs_diff_pts']})")


def stage_E3():
    if have("E3"):
        return
    tree = ROOT.parent / "e3_mesh_tree"
    if not tree.exists():
        tree.mkdir()
        for sub in ("scripts", "config", "geometry", "base_cases"):
            shutil.copytree(ROOT / sub, tree / sub, ignore=shutil.ignore_patterns("*.pyc"))
        (tree / "logs").mkdir(); (tree / "results").mkdir()
    env = {**os.environ, "AIRWAY_DOCKER_ARGS": f"--cpuset-cpus={cpuset(cs([len(GROUPS) - 1], 2)[1:])}"}
    # job_mesh.py resolves the project root from its own location, so the separate tree's copy meshes into that tree
    shutil.copytree(ROOT / "cloud" / "runner", tree / "cloud" / "runner", dirs_exist_ok=True)
    t0 = time.time()
    r = subprocess.run([sys.executable, str(tree / "cloud/runner/job_mesh.py"), "n40", "medium"], cwd=tree, env=env,
                       capture_output=True, text=True)
    (OUT / "E3_mesh.out").write_text(r.stdout + r.stderr)
    wall = time.time() - t0
    mac = json.loads((ROOT / "cases/mesh/n40_medium/mesh_report.json").read_text())
    f = tree / "cases/mesh/n40_medium/mesh_report.json"
    cl = json.loads(f.read_text()) if f.exists() else {}
    keys = ["cells", "points", "max_non_orthogonality", "avg_non_orthogonality", "max_skewness", "max_aspect_ratio"]
    rel = {k: (abs(cl[k] - mac[k]) / abs(mac[k]) if cl.get(k) is not None and mac.get(k) else None) for k in keys}
    res = {"mac": {k: mac.get(k) for k in keys}, "cloud": {k: cl.get(k) for k in keys}, "rel_diff": rel, "mesh_wall_s": wall,
           "status": cl.get("status")}
    res["identical_cell_count"] = cl.get("cells") == mac.get("cells")
    res["pass"] = bool(cl) and res["identical_cell_count"] and all(v is not None and v <= 1e-3 for v in rel.values())
    save("E3", res)
    log(f"E3 mesh reproducibility: {'PASS' if res['pass'] else 'FAIL (Mac n40 meshes will be used; reported)'}")


def start_fine():
    """Full fine-mesh T_N40_SYM case (0-3 s) + 1/3/5 um maps on 32 cores: the medium-vs-fine verification of
    validation/04_mesh_independence/CRITERIA.md, run here instead of on the Mac (same image, inputs and settings)."""
    if not BENCH_FINE or (ROOT / "cases/particles" / f"MAP_{FINE_CASE}_P05" / "results.json").exists():
        return None
    g = cs(FINE_GROUPS)
    env = {**os.environ, "AIRWAY_DOCKER_ARGS": f"--cpuset-cpus={cpuset(g)}"}
    cmd = (f"{sys.executable} cloud/runner/job_airflow.py T_N40_SYM --as {FINE_CASE} --level fine --ranks {len(g)} --allow-unapproved"
           f" && {sys.executable} cloud/runner/job_maps.py {FINE_CASE} --condition T_N40_SYM --sizes 1 3 5")
    (OUT / "FINE_started.json").write_text(json.dumps({"started": time.time(), "cores": cpuset(g)}))
    log(f"fine-mesh verification case started on cores {cpuset(g)}")
    return subprocess.Popen(["bash", "-c", cmd], cwd=ROOT, env=env, stdout=open(OUT / "FINE.out", "a"), stderr=subprocess.STDOUT)


def start_B5():
    """Full medium case + maps, as a background process on the last L3 group but one."""
    f = OUT / "B5_started.json"
    if f.exists() and (ROOT / "cases/particles" / f"MAP_{EQ_CASE}_P05" / "results.json").exists():
        return None
    g = cs([B5_GROUP])
    env = {**os.environ, "AIRWAY_DOCKER_ARGS": f"--cpuset-cpus={cpuset(g)}"}
    cmd = (f"{sys.executable} cloud/runner/job_airflow.py T_N40_SYM --as {EQ_CASE} --level medium --ranks 8 --allow-unapproved"
           f" && {sys.executable} cloud/runner/job_maps.py {EQ_CASE} --condition T_N40_SYM --sizes 1 3 5")
    f.write_text(json.dumps({"started": time.time(), "cores": cpuset(g)}))
    log(f"B5 full medium case started on cores {cpuset(g)}")
    return subprocess.Popen(["bash", "-c", cmd], cwd=ROOT, env=env, stdout=open(OUT / "B5.out", "a"), stderr=subprocess.STDOUT)


def stage_B2_E5(sampler):
    if have("B2"):
        return
    rows = []
    # layout per phase: group a -> 1, 2, 4 ranks (7 cores); group b -> 8; groups c, d -> 16
    def layout(base):
        i = FREE.index(base)
        a = cs([FREE[i]]); return {1: a[0:1], 2: a[1:3], 4: a[3:7], 8: cs([FREE[i + 1]]), 16: cs([FREE[i + 2], FREE[i + 3]])}
    F = FREE
    if len(F) >= 9:
        batches = ((("0.24", F[0]), ("2", F[4])), (("1", F[0]),))
    else:                                                   # fine case running: one phase at a time
        batches = ((("0.24", F[0]),), (("2", F[0]),), (("1", F[0]),))
    for batch in batches:
        sampler.tag = "B2:" + "+".join(p for p, _ in batch)
        jobs = []
        for phase, base in batch:
            L = layout(base)
            for r in (1, 2, 4, 8, 16):
                jobs.append((f"seg_{phase}_r{r}", phase, PHASES[phase], r, L[r], None))
        if batch[0][0] == "1":
            jobs.append(("E5_restart_1_r8", "1", "1.02", 8, cs([FREE[4]]), 60))   # E5 on its own group
        with ThreadPoolExecutor(len(jobs)) as ex:
            rows += list(ex.map(lambda j: run_segment(*j), jobs))
        log(f"B2 batch {[p for p, _ in batch]} done")
    save("B2", rows)


def stage_B6(sampler):
    if have("B6"):
        return
    import run_airflow_cases as R
    import run_study_v002 as S
    from lib.common import load_config
    cfg = load_config()
    first = [c for c in S.all_conditions() if c["id"] == "T_N40_SYM"][0]
    rows = []
    sampler.tag = "B6"

    def one(r, cores):
        aid = f"B6_fine_r{r}"
        S.build_condition_case(cfg, first, aid, "fine")
        R.prepare_fresh(aid, "n40", S.wave_name(first), r, "fine")
        d = ROOT / "cases/airflow" / aid
        cp = d / "system" / "caseParameters"
        cp.write_text(re.sub(r"^endTime\s+\S+;", "endTime       0.02;", cp.read_text(), flags=re.M))
        foam(d, "decomposePar -force", cores, "decomposePar")
        rc, w = foam(d, f"mpirun -np {r} --oversubscribe pimpleFoam -parallel", cores, "pimpleFoam")
        st = step_times(d / "logs" / "pimpleFoam.log", skip=10)
        return {"ranks": r, "rc": rc, "wall_s": w, **(st or {})}
    with ThreadPoolExecutor(2) as ex:
        rows = list(ex.map(lambda a: one(*a), ((8, cs([FREE[0]])), (24, cs(FREE[1:4])))))
    # Mac reference: the same steps of the Mac's running fine case (8 ranks, nothing else running on the Mac)
    mac_log = ROOT / "cases/airflow/V_MESH_fine_T_N40_SYM/logs/pimpleFoam.log"
    mac = None
    if mac_log.exists():
        t = mac_log.read_text(errors="ignore")
        ex_, n = [], 0
        for blk in t.split("\nTime = ")[1:]:
            T = float(blk.split("\n", 1)[0])
            m = re.search(r"ExecutionTime = ([\d.]+) s", blk)
            if m and T <= 0.02 + 1e-12:
                ex_.append(float(m.group(1)))
        if len(ex_) > 12:
            d = [b - a for a, b in zip(ex_[10:-1], ex_[11:])]
            mac = {"steps": len(ex_), "s_per_step": sum(d) / len(d)}
    save("B6", {"cloud": rows, "mac_fine_8_ranks_same_steps": mac})
    log("B6 fine-mesh segment done")


def stage_B3(sampler):
    if have("B3"):
        return
    res = []
    usable = FREE                                     # all groups except B5's (and the fine case's, if running)
    flat = [c for i in usable for c in GROUPS[i]]
    for R in (8, 6, 4, 12, 16):
        K = len(flat) // R
        if K < 2:
            continue
        sampler.tag = f"B3:{K}x{R}"
        jobs = []
        for k in range(K):
            if R == 8 or R == 4:
                per = 8 // R if R < 8 else 1
                g = usable[k // per]
                off = (k % per) * R
                cores = GROUPS[g][off:off + R]
            else:
                cores = flat[k * R:(k + 1) * R]
            jobs.append((f"conc_{K}x{R}_{k}", "1", "1.02", R, cores, None))
        t0 = time.time()
        with ThreadPoolExecutor(K) as ex:
            rows = list(ex.map(lambda j: run_segment(*j), jobs))
        wall = time.time() - t0
        sps = sorted(r.get("s_per_step", float("nan")) for r in rows)
        res.append({"K": K, "R": R, "wall_s": wall, "median_s_per_step": sps[len(sps) // 2], "max_s_per_step": sps[-1],
                    "all_finished": all(r.get("finished") for r in rows),
                    "max_rel_l2_U_vs_mac": max(r.get("vs_mac", {}).get("U", {}).get("rel_l2", 9) for r in rows)})
        log(f"B3 {K}x{R}: median {sps[len(sps) // 2]:.3f} s/step")
    save("B3", res)


# ------------------------------------------------------------------ summary
def summary():
    from equivalence import evaluate
    s = evaluate(OUT)
    save("summary", s)
    (OUT / "SUMMARY.md").write_text(s["markdown"])
    print(s["markdown"])


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    OUT.mkdir(parents=True, exist_ok=True)
    BENCH.mkdir(parents=True, exist_ok=True)
    if what == "summary":
        return summary()
    if what == "e1":                     # production preflight: refuse to run on a non-identical toolchain
        ok = stage_E1(f"E1_preflight_{int(time.time())}")
        sys.exit(0 if ok else 3)
    sampler = Sampler(OUT / "system_samples.csv").start()
    import run_particle_cases as RP
    from lib.common import load_config
    RP.ensure_solver(load_config())
    if not stage_E1():
        log("E1 FAILED: toolchain differs from the Mac reference - benchmark stopped (see E1.json)")
        sys.exit(3)
    p5 = start_B5()
    pf = start_fine()
    sampler.tag = "E2+E3"
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(lambda f: f(), (stage_E2, stage_E3)))
    stage_B2_E5(sampler)
    stage_B6(sampler)
    stage_B3(sampler)
    sampler.tag = "B5-only"
    if p5 is not None:
        log("waiting for the complete medium case (B5) to finish")
        p5.wait()
    if pf is not None:
        sampler.tag = "fine-only"
        log("waiting for the fine-mesh verification case to finish")
        pf.wait()
    summary()
    sampler.stop.set()


if __name__ == "__main__":
    main()
