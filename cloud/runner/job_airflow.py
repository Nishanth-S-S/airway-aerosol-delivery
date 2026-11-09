#!/usr/bin/env python3
"""Run (or resume) ONE v002 airflow case on the cloud instance, interruption-safe.

    python3 cloud/runner/job_airflow.py <aid> --ranks 8 [--level medium] [--allow-unapproved]

Exit codes: 0 PASSED, 2 FAILED (QA / completion checks), 75 checkpointed and stopped on request (resume later).

Identical to the Mac path (scripts/run_study_v002.py -> run_airflow_cases.run_airflow) in every numerical respect:
same case generator, same mesh, same dictionaries, same OpenFOAM image (pinned by digest), same commands
(decomposePar -force; mpirun -np R --oversubscribe pimpleFoam -parallel; reconstructPar -newTimes), same QA.
Differences are operational only:
  * the case is pinned to its own cores (AIRWAY_DOCKER_ARGS=--cpuset-cpus=..., set by the runner);
  * a stop request (file <case>/STOP_REQUEST, written on Spot interruption notice or budget cutoff) makes the solver
    write its current state and exit (controlDict stopAt writeNow); the case is later resumed from that state
    (startFrom latestTime, with U_0/phi_0 old-time fields, i.e. an exact restart of the 2nd-order backward scheme);
  * after the run, any off-schedule checkpoint time is moved to <case>/quarantine/ so the stored snapshots are
    exactly the 150 scheduled write times used by the particle solver (verified before QA).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.common import load_config, run_foam, update_status  # noqa: E402
from lib.foam_case import airflow_case_dir  # noqa: E402

GRID = 0.02          # writeInterval of every v002 airflow case
DRAIN = Path(os.environ.get("AIRWAY_DRAIN_FILE", "/data/DRAIN"))   # instance-wide stop signal (guard / runner)


def stop_requested(d: Path) -> bool:
    return DRAIN.exists() or (d / "STOP_REQUEST").exists()
END = 3.0


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} JOB {msg}"
    print(line, flush=True)
    with open(ROOT / "logs" / "cloud_runner.log", "a") as fh:
        fh.write(line + "\n")


def is_time(name):
    try:
        float(name)
        return True
    except ValueError:
        return False


def on_grid(t):
    return abs(t / GRID - round(t / GRID)) < 1e-6


def proc_times(d: Path):
    """[(time value, directory name)] of processor0, sorted (names kept exactly as OpenFOAM wrote them)."""
    p0 = d / "processor0"
    if not p0.exists():
        return []
    return sorted((float(p.name), p.name) for p in p0.iterdir() if p.is_dir() and is_time(p.name) and float(p.name) > 0)


def complete_time(d: Path, tname: str, nprocs: int):
    for i in range(nprocs):
        td = d / f"processor{i}" / tname
        if not all((td / f).exists() and (td / f).stat().st_size > 0 for f in ("U", "p", "phi", "U_0", "phi_0")):
            return False
        if not (td / "uniform" / "time").exists():
            return False
    return True


def quarantine(d: Path, tname: str, nprocs: int, why: str):
    q = d / "quarantine" / f"{tname}_{int(time.time())}"
    q.mkdir(parents=True, exist_ok=True)
    for i in range(nprocs):
        src = d / f"processor{i}" / tname
        if src.exists():
            shutil.move(str(src), str(q / f"processor{i}"))
    (q / "WHY.txt").write_text(why + "\n")
    log(f"{d.name}: moved time {tname} to {q.relative_to(ROOT)} ({why})")


def set_stop(d: Path, mode: str):
    cd = d / "system" / "controlDict"
    t = cd.read_text()
    t2 = re.sub(r"^stopAt\s+\w+;", f"stopAt          {mode};", t, flags=re.M)
    if t2 != t:
        cd.write_text(t2)


def watch_stop_request(d: Path, proc: subprocess.Popen):
    """Background poll: STOP_REQUEST -> stopAt writeNow (read by the running solver, runTimeModifiable yes)."""
    import threading

    def run():
        while proc.poll() is None:
            if stop_requested(d):
                set_stop(d, "writeNow")
                log(f"{d.name}: stop requested -> stopAt writeNow")
                return
            time.sleep(2)
    threading.Thread(target=run, daemon=True).start()


def solve(cfg, d: Path, ranks: int, part: int) -> int:
    from lib.common import foam_cmd
    logs = d / "logs"
    logs.mkdir(exist_ok=True)
    if (logs / "pimpleFoam.log").exists():
        (logs / "pimpleFoam.log").rename(logs / f"pimpleFoam.part{part - 1}.log")
    set_stop(d, "endTime")
    cmd = foam_cmd(cfg, d, f"mpirun -np {ranks} --oversubscribe pimpleFoam -parallel")
    with open(logs / "pimpleFoam.log", "w") as fh:
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)
        watch_stop_request(d, proc)
        rc = proc.wait()
    set_stop(d, "endTime")
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("aid")
    ap.add_argument("--ranks", type=int, required=True)
    ap.add_argument("--level", default=None, help="override mesh level (benchmark only)")
    ap.add_argument("--allow-unapproved", action="store_true", help="benchmark/equivalence runs only")
    ap.add_argument("--as", dest="as_", default=None, help="case id to write to (equivalence runs, e.g. C_EQ_medium_T_N40_SYM)")
    a = ap.parse_args()
    import run_airflow_cases as R
    import run_study_v002 as S
    cfg = load_config()
    spec = {s["aid"]: s for s in S.airflow_specs(cfg)}.get(a.aid)
    if spec is None:
        sys.exit(f"unknown airflow case {a.aid}")
    if a.as_ and not a.allow_unapproved:
        sys.exit("--as is for benchmark/equivalence runs only (use with --allow-unapproved)")
    base = a.aid
    a.aid = a.as_ or a.aid
    d = airflow_case_dir(a.aid)
    if S.airflow_passed(a.aid):
        log(f"{a.aid}: already PASSED")
        return 0
    if spec["need_mesh_approval"] and not a.allow_unapproved:
        md = S.MESH_DECISION
        if not (md.exists() and json.loads(md.read_text()).get("approved") is True):
            sys.exit(f"{a.aid}: production mesh not approved ({md})")
    ck = d / "cloud_checkpoint.json"
    state = json.loads(ck.read_text()) if ck.exists() else None
    c = spec["c"]
    level = a.level or spec["level"]
    if state and state.get("ranks") != a.ranks:
        sys.exit(f"{a.aid}: checkpoint was decomposed for {state.get('ranks')} ranks; resume with --ranks {state.get('ranks')}")
    if state is None or not proc_times(d):
        # ---------- fresh start (same functions as the Mac path)
        import mesh_geometry
        k0 = S.cfg_for(cfg, c)
        if spec["cfg_mod"]:
            spec["cfg_mod"](k0)
        lvl = level or k0["mesh"]["level"]
        if not mesh_geometry.mesh_ready(c["geometry"], lvl):
            sys.exit(f"{a.aid}: mesh {c['geometry']}/{lvl} not ready (mesh stage must run first)")
        k, lvl = S.build_condition_case(cfg, c, a.aid, lvl, spec["edit"], spec["cfg_mod"])
        R.prepare_fresh(a.aid, c["geometry"], S.wave_name(c), a.ranks, lvl)
        rc = run_foam(k, d, "decomposePar -force", "decomposePar")
        if rc != 0:
            log(f"{a.aid}: decomposePar exit {rc}")
            return 2
        state = {"ranks": a.ranks, "level": lvl, "parts": 0, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "host": os.uname().nodename}
        ck.write_text(json.dumps(state, indent=2))
        log(f"{a.aid}: fresh start, {a.ranks} ranks, mesh {lvl}")
    else:
        # ---------- resume: drop an incomplete latest time (killed mid-write), never touch complete ones
        _, tname = proc_times(d)[-1]
        if not complete_time(d, tname, a.ranks):
            quarantine(d, tname, a.ranks, "incomplete write at interruption")
        if not proc_times(d):
            sys.exit(f"{a.aid}: no complete checkpoint left; start fresh by moving {ck} aside")
        log(f"{a.aid}: resuming from t = {proc_times(d)[-1][1]} ({a.ranks} ranks)")
    k = S.cfg_for(cfg, c)
    if spec["cfg_mod"]:
        spec["cfg_mod"](k)
    state["parts"] += 1
    ck.write_text(json.dumps(state, indent=2))
    (d / "STOP_REQUEST").unlink(missing_ok=True)       # stale request from an earlier instance
    if DRAIN.exists():
        log(f"{a.aid}: drain in progress - not starting the solver (exit 75)")
        return 75
    t0 = time.time()
    rc = solve(k, d, a.ranks, state["parts"])
    state.setdefault("solver_wall_s", []).append(round(time.time() - t0, 1))
    ck.write_text(json.dumps(state, indent=2))
    times = proc_times(d)
    reached = bool(times) and abs(times[-1][0] - END) < 1e-6
    last = times[-1][1] if times else "0"
    if not reached:
        if stop_requested(d):
            log(f"{a.aid}: checkpointed at t = {last} (exit 75, resume later)")
            return 75
        log(f"{a.aid}: solver stopped at t = {last} without reaching {END} (rc {rc})")
        update_status(a.aid, solver_status="FAILED", qa_status="FAILED", notes=f"cloud: solver rc {rc}")
        return 2
    # ---------- off-schedule checkpoint times out of the snapshot set
    for t, name in times:
        if not on_grid(t):
            quarantine(d, name, a.ranks, "off-schedule checkpoint write (stopAt writeNow); not a scheduled snapshot")
    mp = d / "postProcessing" / "midPlane"
    if mp.exists():
        for p in mp.iterdir():
            if is_time(p.name) and not on_grid(float(p.name)):
                (d / "quarantine" / "midPlane").mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(d / "quarantine" / "midPlane" / p.name))
    # ---------- completion checks + reconstruct + QA (same finisher used for the Mac medium case)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "finish_airflow_case.py"), a.aid, "--condition", c["id"],
                        "--finished-by", f"cloud/runner/job_airflow.py ({a.ranks} ranks, {state['parts']} part(s))"])
    if r.returncode != 0:
        return 2
    grid = sorted(round(float(p.name), 9) for p in d.iterdir() if p.is_dir() and is_time(p.name) and float(p.name) > 0)
    expect = [round(GRID * i, 9) for i in range(1, int(round(END / GRID)) + 1)]
    ok = grid == expect
    cc = json.loads((d / "completion_check.json").read_text())
    cc["snapshot_times_exactly_scheduled_grid"] = ok
    cc["cloud_parts"] = state["parts"]
    (d / "completion_check.json").write_text(json.dumps(cc, indent=2, default=float))
    if not ok:
        q = json.loads((d / "qa_report.json").read_text())
        q["status"] = "FAILED"
        q.setdefault("problems", []).append("stored snapshot times differ from the 0.02 s schedule")
        (d / "qa_report.json").write_text(json.dumps(q, indent=2))
        log(f"{a.aid}: FAILED snapshot-grid check")
        return 2
    q = json.loads((d / "qa_report.json").read_text())
    log(f"{a.aid}: {q['status']} split {q.get('target_branch_ventilation_percent')} wall {q.get('wallclock_min')} min")
    return 0 if q["status"] == "PASSED" else 2


if __name__ == "__main__":
    sys.exit(main())
