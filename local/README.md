# Running the study on the desktop (Ryzen 9 9950X3D · RTX 5090 · 64 GB DDR5)

Same Docker image (pinned by digest), solvers, meshes, tolerances, physics, QA and gates as the Mac. The only
differences are the core layout and the scheduler settings. The desktop must pass the same equivalence tests
(`cloud/EQUIVALENCE_CRITERIA.md`, E1–E6) before its results are used.

## How the hardware is used

| Part | Use |
|---|---|
| 16 cores, 2 CCDs of 8 | One CFD case per CCD (7 MPI ranks each), plus 1 core per CCD for the particle solver. The CCD with the 3D V-Cache (the larger L3) runs the longest case. |
| 32 threads (SMT) | Not used: one thread per physical core. CFD is limited by memory bandwidth, so a second thread per core would slow both ranks down. |
| 64 GB DDR5 | Enough for the fine case (8 ranks) and a medium case at the same time. Under WSL2, give Linux 56 GB (step 2). |
| RTX 5090 | Not used. OpenFOAM's pimpleFoam and our airwayParcelFoam run only on the CPU. A GPU solver would change the numerics, which the protocol forbids. |

## Expected time

These are estimates from the Mac's measured run times, assuming the desktop is 1.8–3.2× faster per core than the
2019 MacBook Pro (i9-9880H), less 5–25% when both CCDs share memory bandwidth. Stage 1 measures the real figures
(`cloud/results/desktop_benchmark/SUMMARY.md`).

| Step | Fast | Central | Slow |
|---|---|---|---|
| Setup and data copy (steps 1–5) | 1 h | 1.5 h | 2 h |
| Stage 1: finish the fine-mesh check from t = 0.52 s, plus the benchmark and E1–E6 on the other CCD | 9 h | 12 h | 19 h |
| Production, if the medium mesh is approved | 16 h | 22 h | 33 h |
| Production, if the fine mesh is required | 4 days | 6 days | 10 days |

If the medium mesh passes, the whole study takes about 1–2 days.

## Steps

### On the Mac (once)
1. **Do not resume the fine-mesh run on the Mac.** The desktop continues it from the same saved state.
2. Copy the data (≈ 6.5 GB, which GitHub cannot hold) to a USB drive or a shared folder:
   ```bash
   python3 local/bundle.py make /Volumes/<USB-drive>/airway_bundle
   ```

### On the desktop
1. **Operating system.** Ubuntu 24.04 is best, either native or under WSL2 on Windows 11.
   - For WSL2, in PowerShell: `wsl --install -d Ubuntu-24.04`, then restart.
2. **WSL2 only.** Create `C:\Users\<you>\.wslconfig` containing:
   ```
   [wsl2]
   memory=56GB
   processors=32
   ```
   Then run `wsl --shutdown` in PowerShell.
   Install Docker Desktop and enable *Settings → Resources → WSL integration → Ubuntu-24.04*, or let step 4 install Docker Engine inside Ubuntu.
3. **Get the code.** In the Ubuntu terminal:
   - `git clone <the GitHub repo URL> ~/airway-aerosol-delivery`
   - `cd ~/airway-aerosol-delivery`

   Keep the project in the Linux home folder, not under `/mnt/c`, where disk access is about 10× slower.
4. **Setup:**
   - `bash local/setup_linux.sh`: Docker, the exact Python environment, and the pinned OpenFOAM image.
5. **Data.** Copy `airway_bundle` from the USB drive into Ubuntu, then:
   - `python3 local/bundle.py unpack ~/airway_bundle`. It checks every file's SHA-256 and never overwrites.
6. **Check:**
   - `bash local/run.sh check`. Must end in `CHECK PASSED`.

     It checks the CPU layout (2 groups of 8 physical cores), memory, disk, data, and E1 (toolchain identical to the Mac).
7. **Stage 1:**
   - `bash local/run.sh stage1`. It runs in the background, so the terminal can be closed.
   - Progress: `bash local/run.sh status`.
8. **Mesh decision.** When stage 1 ends, the medium-vs-fine comparison is run against
   `validation/04_mesh_independence/CRITERIA.md`.

   The decision is recorded in `MESH_DECISION.json` (with `production_level`). Coarse v002 results are archived and the config is updated. This step is done with Claude, and is not automated.
9. **Production:**
   - `bash local/run.sh production`. Refused unless the mesh is approved and E1, E2, E4, E5 and E6 all passed.

## During long runs
- **Power and sleep:** set Windows sleep to *Never* while plugged in. Pause Windows Update for a week, because a forced
  restart kills the run (it can be resumed, but the time since the last save is lost).
- **Stop safely:** `bash local/run.sh stop`. Solvers save their state within about a minute. Start the same command again to resume
  exactly where it stopped.
- **After a crash or power cut:** start the same command again. A save that was cut off midway is moved to `quarantine/`
  and the run resumes from the last complete one.
- **Results** stay in the project folder. The small files (`results/`, `validation/`, `cloud/results/desktop_benchmark/`, QA reports)
  can be committed to git; large case folders stay on the desktop's disk.

## CPU layout problems
`check` must show `[[0..7], [8..15]]` (native Linux) or the WSL2 equivalent.
If it doesn't, set the two CCDs by hand in `local/desktop.env`, for example:
```
export AIRWAY_CORE_GROUPS="0-7;8-15"
```
Each group must list one logical CPU per physical core, all on one CCD. `lscpu -e` shows CORE, L3 and CPU numbers.
