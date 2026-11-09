#!/usr/bin/env python3
"""Production scheduler for the cloud instance (one c7a.24xlarge). Restart-safe; never oversubscribes cores.

    python3 cloud/runner/cloud_runner.py --ranks 8 --particle-cores 8 [--co1-ranks 16] [--dry-run]

Stages (dependencies enforced here and inside the project scripts):
  1. mesh every geometry needed at the approved production level (gated snappyHexMesh, 1 core each)
  2. airflow cases (scripts/run_study_v002.airflow_specs, minus those already PASSED), longest first, each pinned to
     its own block of cores (aligned to the CPU's shared-L3 groups); V_CO1 may use more ranks (critical path)
  3. particle queue (response maps + 144 baseline, scripts/run_study_v002.py particles) on a reserved core pool,
     starting maps as soon as each airflow case PASSES
  4. after ALL airflow has passed: scripts/analysis_pipeline.py (audit G1, recheck S2, map gate G2, training-only
     FREEZE S3, held-out evaluation S5, verification maps S4v, reports S6) on all free cores
Every finished case is copied to S3 at once (cloud/instance/sync.sh). A file /data/DRAIN (written by the guard on a
Spot interruption notice or at the budget/time cutoff) stops new work, asks running airflow cases to write their
state and exit, and lets the runner exit 75 so a later instance resumes exactly where this one stopped.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
DRAIN = Path(os.environ.get("AIRWAY_DRAIN_FILE", "/data/DRAIN"))
STATUS = ROOT / "logs" / "cloud_status.json"
LOG = ROOT / "logs" / "cloud_runner.log"


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} RUNNER {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(line + "\n")


# ------------------------------------------------------------------ cores
def _cpu_list(s):
    out = []
    for part in s.replace(" ", "").split(","):
        if part:
            a, _, b = part.partition("-")
            out += list(range(int(a), int(b or a) + 1))
    return out


def core_groups():
    """CPU ids grouped by shared L3 cache (8 cores per group on AMD Zen 4/5), ONE logical CPU per physical core.

    With SMT (e.g. Ryzen 9 9950X3D: 16 cores / 32 threads) the sibling threads are left out, so two MPI ranks never
    share a physical core (c7a has no SMT: unchanged there). AIRWAY_CORE_GROUPS="0-7;8-15" overrides the detection
    (needed when the OS hides the cache topology, e.g. some WSL2 kernels). Falls back to blocks of 8 physical cores."""
    env = os.environ.get("AIRWAY_CORE_GROUPS", "").strip()
    if env:
        return [_cpu_list(g) for g in env.split(";") if g.strip()]
    sysd = Path(os.environ.get("AIRWAY_SYSFS_CPU", "/sys/devices/system/cpu"))     # override: tests only
    cpus = sorted(int(p.name[3:]) for p in sysd.glob("cpu[0-9]*")) if sysd.exists() else []
    online = sysd / "online"
    if online.exists():
        cpus = [c for c in cpus if c in set(_cpu_list(online.read_text().strip()))]
    phys, seen = [], set()
    for c in cpus:
        f = sysd / f"cpu{c}" / "topology" / "thread_siblings_list"
        sib = tuple(_cpu_list(f.read_text().strip())) if f.exists() else (c,)
        if sib not in seen:
            seen.add(sib)
            phys.append(c)                              # first thread of each physical core
    groups = {}
    for i, c in enumerate(phys):
        f = sysd / f"cpu{c}" / "cache" / "index3" / "shared_cpu_list"
        key = f.read_text().strip() if f.exists() else f"blk{i // 8:03d}"
        groups.setdefault(key, []).append(c)
    if not groups:
        n = os.cpu_count() or 8
        groups = {str(i): list(range(i, min(i + 8, n))) for i in range(0, n, 8)}
    return [sorted(v) for _, v in sorted(groups.items(), key=lambda kv: min(kv[1]))]


def group_l3_kb(groups):
    """L3 size (KiB) seen by each core group, or None if unknown (used to put the longest case on the 3D V-Cache CCD)."""
    out = []
    for g in groups:
        f = Path(os.environ.get("AIRWAY_SYSFS_CPU", "/sys/devices/system/cpu")) / f"cpu{g[0]}" / "cache" / "index3" / "size"
        try:
            s = f.read_text().strip().upper()
            out.append(int(s.rstrip("KMB")) * (1024 if s.endswith("M") or s.endswith("MB") else 1))
        except (OSError, ValueError):
            out.append(None)
    return out


class Cores:
    def __init__(self, groups):
        self.groups = groups
        self.free = set(c for g in groups for c in g)

    def take(self, n, spread=False):
        """n free cores. n >= group size: whole free groups first. n < group size: best-fit group (fewest free cores
        that still fit), so small jobs do not fragment the L3 groups that whole airflow cases need.
        spread=True (small particle pool on a 2-group desktop): the highest free core of each group in turn, so every
        group keeps an equal block for one airflow case (16 cores = 2 x 7 airflow ranks + 2 particle cores)."""
        if len(self.free) < n:
            return None
        gsize = max(len(g) for g in self.groups)
        chosen = []
        if spread and n <= len(self.groups):
            order = sorted(self.groups, key=lambda g: -sum(c in self.free for c in g))
            for g in order[:n]:
                fr = [c for c in g if c in self.free]
                if fr:
                    chosen.append(fr[-1])
            if len(chosen) < n:
                chosen += [c for c in sorted(self.free, reverse=True) if c not in chosen][: n - len(chosen)]
        elif n >= gsize:
            for g in sorted(self.groups, key=lambda g: -sum(c in self.free for c in g)):
                chosen += [c for c in g if c in self.free][: n - len(chosen)]
                if len(chosen) == n:
                    break
        else:
            fits = [g for g in self.groups if sum(c in self.free for c in g) >= n]
            if fits:
                g = min(fits, key=lambda g: sum(c in self.free for c in g))
                chosen = [c for c in g if c in self.free][:n]
            else:
                chosen = sorted(self.free)[:n]
        self.free -= set(chosen)
        return sorted(chosen)

    def give(self, cs):
        self.free |= set(cs)


def cpuset(cs):
    return ",".join(str(c) for c in cs)


# ------------------------------------------------------------------ jobs
class Job:
    def __init__(self, name, cmd, cores, kind, sync_paths=(), env=None, after=None, priority=0, ranks=None):
        self.name, self.cmd, self.cores_needed, self.kind = name, cmd, cores, kind
        self.sync_paths, self.env, self.after, self.priority, self.ranks = list(sync_paths), env or {}, after, priority, ranks
        self.proc = self.cores = self.t0 = None
        self.rc = None


def sync(paths, dry):
    if dry or not paths or os.environ.get("AIRWAY_NO_SYNC") == "1":      # desktop: results stay on the local disk
        return
    subprocess.Popen(["bash", str(ROOT / "cloud" / "instance" / "sync.sh"), *[str(p) for p in paths]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ranks", type=int, default=8, help="MPI ranks per airflow case (from the benchmark)")
    ap.add_argument("--co1-ranks", type=int, default=None, help="ranks for the Courant-1 case (longest)")
    ap.add_argument("--particle-cores", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true", help="scheduler test: jobs are 'sleep'")
    ap.add_argument("--cores", type=int, default=None, help="limit cores (testing)")
    ap.add_argument("--spread-particles", action="store_true",
                    help="take the particle cores one per L3 group (desktop: --ranks 7 --particle-cores 2)")
    a = ap.parse_args()
    global LOG, STATUS
    if a.dry_run:      # never touch the project's real logs during a scheduler test
        scratch = Path(os.environ.get("AIRWAY_DRYRUN_DIR", "/tmp/airway_dryrun"))
        scratch.mkdir(parents=True, exist_ok=True)
        LOG, STATUS = scratch / "cloud_runner.log", scratch / "cloud_status.json"
    import run_study_v002 as S
    from lib.common import load_config
    cfg = load_config()
    md = S.MESH_DECISION
    if not a.dry_run and not (md.exists() and json.loads(md.read_text()).get("approved") is True):
        sys.exit(f"production mesh not approved ({md}); run the benchmark plan instead")
    level = cfg["mesh"]["level"]
    groups = core_groups()
    if a.cores:
        flat = [c for g in groups for c in g][:a.cores]
        groups = [[c for c in g if c in flat] for g in groups]
        groups = [g for g in groups if g]
    pool = Cores(groups)
    image = os.environ.get("AIRWAY_DOCKER_IMAGE", "")
    py = sys.executable
    specs = [s for s in S.airflow_specs(cfg) if s["aid"] != "V_MESH_medium_T_N40_SYM"]
    todo = [s for s in specs if not S.airflow_passed(s["aid"])]
    geos = sorted({s["c"]["geometry"] for s in todo})
    log(f"start: level {level}, {sum(len(g) for g in groups)} cores in {len(groups)} L3 groups, "
        f"{len(todo)} airflow cases to run, geometries {geos}, ranks {a.ranks}")

    def fake(sec):
        return ["bash", "-c", f"sleep {sec}"]

    jobs = []
    import mesh_geometry
    for g in geos:
        if not mesh_geometry.mesh_ready(g, level):
            jobs.append(Job(f"mesh:{g}", fake(3) if a.dry_run else [py, str(ROOT / "cloud/runner/job_mesh.py"), g, level], 1, "mesh",
                            sync_paths=[f"cases/mesh/{g}_{level}"], priority=100))
    # airflow, longest first (relative costs from cloud/tools/plan_workload.py)
    cost = {"V_CO1_T_N40_SYM": 2.0}
    for s in todo:
        r = (a.co1_ranks or a.ranks) if s["aid"] == "V_CO1_T_N40_SYM" else a.ranks
        c = s["c"]
        w = cost.get(s["aid"], {"healthy": .85, "n20": .88, "n30": .94}.get(c["geometry"], 1.0) * (0.31 + 0.69 * c["flow_lpm"] / 2))
        cmd = fake(int(20 * w)) if a.dry_run else [py, str(ROOT / "cloud/runner/job_airflow.py"), s["aid"], "--ranks", str(r)]
        jobs.append(Job(f"airflow:{s['aid']}", cmd, r, "airflow", sync_paths=[f"cases/airflow/{s['aid']}", "logs", "results/run_status.csv"],
                        after=f"mesh:{c['geometry']}", priority=10 + w, ranks=r))
    pc = a.particle_cores
    jobs.append(Job("particles:queue", fake(30) if a.dry_run else [py, str(ROOT / "scripts/run_study_v002.py"), "particles", "--jobs", str(pc)],
                    pc, "particles", sync_paths=["cases/particles", "logs", "results"], priority=50))
    jobs.append(Job("analysis:pipeline", fake(10) if a.dry_run else [py, str(ROOT / "scripts/analysis_pipeline.py")],
                    -1, "pipeline", sync_paths=["cases/particles", "results", "validation", "docs", "logs"], after="ALL_AIRFLOW", priority=0))
    names_mesh = {j.name for j in jobs if j.kind == "mesh"}
    running, done, failed = [], {}, {}
    t_start = time.time()
    airflow_closed = False

    def ready(j):
        if j.after is None:
            return True
        if j.after == "ALL_AIRFLOW":
            return all(done.get(x.name) == 0 for x in jobs if x.kind == "airflow")
        if j.after in names_mesh:
            return done.get(j.after) == 0
        return True

    def write_status(state="running"):
        st = {"state": state, "updated": time.strftime("%Y-%m-%d %H:%M:%S"), "elapsed_h": round((time.time() - t_start) / 3600, 3),
              "cores_total": sum(len(g) for g in groups), "cores_busy": sum(len(j.cores) for j in running if j.cores),
              "running": [{"job": j.name, "cores": len(j.cores), "since_min": round((time.time() - j.t0) / 60, 1)} for j in running],
              "done": sorted(k for k, v in done.items() if v == 0), "failed": failed,
              "pending": [j.name for j in jobs if j.proc is None and j.name not in done and j.name not in failed]}
        STATUS.write_text(json.dumps(st, indent=2))

    while True:
        draining = DRAIN.exists()
        # start ready jobs (priority order) while cores allow
        if not draining:
            for j in sorted([j for j in jobs if j.proc is None and j.name not in done and j.name not in failed and ready(j)],
                            key=lambda j: -j.priority):
                n = len(pool.free) if j.cores_needed == -1 else j.cores_needed
                if j.cores_needed == -1 and n < 8:
                    continue
                cs = pool.take(n, spread=(j.kind == "particles" and a.spread_particles))
                if cs is None:
                    if j.kind == "airflow":
                        break          # reserve: no lower-priority case may take the cores this one is waiting for
                    continue
                env = dict(os.environ)
                env.update(j.env)
                env["AIRWAY_DOCKER_ARGS"] = f"--cpuset-cpus={cpuset(cs)}"
                if image:
                    env["AIRWAY_DOCKER_IMAGE"] = image
                if j.kind == "pipeline":
                    env["AIRWAY_PARTICLE_JOBS"] = str(len(cs))
                j.cores, j.t0 = cs, time.time()
                out = open(LOG.parent / f"cloud_{j.name.replace(':', '_')}.out", "a")
                j.proc = subprocess.Popen(j.cmd, cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT)
                running.append(j)
                log(f"started {j.name} on cores {cpuset(cs)}")
        else:
            # airflow jobs see the same DRAIN file themselves and write their state (stopAt writeNow), exit 75
            if a.dry_run:
                for j in running:
                    if j.kind == "airflow" and j.proc.poll() is None and not getattr(j, "terminated", False):
                        j.proc.terminate(); j.terminated = True       # fake jobs cannot checkpoint
            if not any(j.kind == "airflow" for j in running):
                # particle work is short and restart-safe (a case without results.json is simply re-run)
                for j in running:
                    if j.proc.poll() is None and not getattr(j, "terminated", False):
                        j.proc.terminate()
                        j.terminated = True
                        log(f"stopping {j.name} for drain (incomplete particle cases re-run on resume)")
        # reap
        for j in list(running):
            rc = j.proc.poll()
            if rc is None:
                continue
            running.remove(j)
            pool.give(j.cores)
            mins = (time.time() - j.t0) / 60
            if rc == 0:
                done[j.name] = 0
                log(f"finished {j.name} in {mins:.1f} min")
            elif rc == 75 or getattr(j, "terminated", False):
                log(f"checkpointed {j.name} after {mins:.1f} min (resume on next start)")
                j.proc = None
            else:
                failed[j.name] = rc
                log(f"FAILED {j.name} (exit {rc}) after {mins:.1f} min")
            sync(j.sync_paths, a.dry_run)
        if not airflow_closed and all(done.get(x.name) == 0 or x.name in failed for x in jobs if x.kind == "airflow"):
            airflow_closed = True
            if not a.dry_run:
                S.log("airflow queue finished")      # lets the particle queue exit once nothing is left
            log("all airflow cases finished" + (f"; failed: {[k for k in failed if k.startswith('airflow')]}" if failed else ""))
        write_status("draining" if draining else "running")
        if draining and not running:
            write_status("drained")
            sync(["cases", "logs", "results", "validation", "docs"], a.dry_run)
            log("drained: all running work checkpointed or finished")
            return 75
        if not running and all(j.name in done or j.name in failed for j in jobs):
            write_status("finished")
            sync(["cases", "logs", "results", "validation", "docs"], a.dry_run)
            log(f"all work finished in {(time.time() - t_start) / 3600:.2f} h; failed: {failed or 'none'}")
            return 0 if not failed else 2
        if not running and not any(ready(j) for j in jobs if j.proc is None and j.name not in done and j.name not in failed):
            write_status("blocked")
            log(f"blocked: nothing runnable; failed {failed}")
            return 2
        time.sleep(1 if a.dry_run else 15)


if __name__ == "__main__":
    sys.exit(main())
