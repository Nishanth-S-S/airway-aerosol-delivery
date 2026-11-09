#!/usr/bin/env python3
"""Resume an interrupted parallel airflow case on the Mac from its last complete saved time, then finish it.

    nohup caffeinate -i -s python3 scripts/resume_airflow_mac.py V_MESH_fine_T_N40_SYM --condition T_N40_SYM \
        --then "scripts/run_fine_mesh_check.py" > logs/resume_fine.out 2>&1 &

1. checks the latest processor time is complete in every processor (else moves it to <case>/quarantine/)
2. keeps the earlier solver log (logs/pimpleFoam.partN.log) and restarts pimpleFoam (startFrom latestTime: exact restart,
   the 2nd-order time scheme's old-time fields U_0/phi_0 are stored with every write)
3. battery guard: if the Mac runs on battery below --battery-min %, the solver is told to write its state and stop
   (stopAt writeNow) so it can be resumed again later instead of dying with the machine
4. off-schedule save times are moved to quarantine/ (the snapshot set stays exactly the 0.02 s schedule), then the standard
   finisher reconstructs, checks completeness and runs QA; optional follow-up script (e.g. the fine-mesh maps)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "cloud" / "runner"))
from lib.common import foam_cmd, load_config  # noqa: E402
import job_airflow as J  # noqa: E402  (complete_time, quarantine, set_stop, on_grid, proc_times)


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(ROOT / "logs" / "study_v002.log", "a") as fh:
        fh.write(line + "\n")


def battery():
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    m = re.search(r"(\d+)%", out)
    return ("Battery Power" in out), (int(m.group(1)) if m else 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case"); ap.add_argument("--condition", required=True)
    ap.add_argument("--ranks", type=int, default=8); ap.add_argument("--battery-min", type=int, default=35)
    ap.add_argument("--then", default=None, help="python script to run after a PASSED finish")
    a = ap.parse_args()
    d = ROOT / "cases" / "airflow" / a.case
    times = J.proc_times(d)
    if not times:
        sys.exit("no saved processor times - nothing to resume")
    _, last = times[-1]
    if not J.complete_time(d, last, a.ranks):
        J.quarantine(d, last, a.ranks, "incomplete write at interruption")
        _, last = J.proc_times(d)[-1]
    logs = d / "logs"
    n = 1
    while (logs / f"pimpleFoam.part{n}.log").exists():
        n += 1
    (logs / "pimpleFoam.log").rename(logs / f"pimpleFoam.part{n}.log")
    J.set_stop(d, "endTime")
    log(f"resume {a.case} from t = {last} ({a.ranks} ranks); earlier log kept as pimpleFoam.part{n}.log")
    cfg = load_config()
    with open(logs / "pimpleFoam.log", "w") as fh:
        proc = subprocess.Popen(foam_cmd(cfg, d, f"mpirun -np {a.ranks} --oversubscribe pimpleFoam -parallel"),
                                stdout=fh, stderr=subprocess.STDOUT)
        stopped = {"battery": False}

        def guard():
            while proc.poll() is None:
                on_batt, pct = battery()
                if on_batt and pct < a.battery_min:
                    J.set_stop(d, "writeNow")
                    stopped["battery"] = True
                    log(f"{a.case}: on battery at {pct} % -> solver told to save and stop (resume later)")
                    return
                time.sleep(30)
        threading.Thread(target=guard, daemon=True).start()
        rc = proc.wait()
    J.set_stop(d, "endTime")
    times = J.proc_times(d)
    if not times or abs(times[-1][0] - 3.0) > 1e-6:
        log(f"{a.case}: solver stopped at t = {times[-1][1] if times else '?'} (rc {rc}, battery stop {stopped['battery']}) - "
            "NOT finished; run this script again to resume")
        sys.exit(75)
    for t, name in times:
        if not J.on_grid(t):
            J.quarantine(d, name, a.ranks, "off-schedule save (battery stop); not a scheduled snapshot")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "finish_airflow_case.py"), a.case, "--condition", a.condition,
                        "--finished-by", f"scripts/resume_airflow_mac.py (resumed after power loss; {n + 1} solver parts)"])
    if r.returncode != 0:
        sys.exit(2)
    if a.then:
        subprocess.run([sys.executable, str(ROOT / a.then)])


if __name__ == "__main__":
    main()
