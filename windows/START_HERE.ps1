# Airway CFD study - one-click setup and run on Windows 11 (started by START_HERE.bat).
# Safe to run again at any time: every step checks what is already done, and the simulation resumes where it stopped.
#   START_HERE.bat      setup (first time) + start or continue the simulation + live progress
#   SEND_RESULTS.bat    put the results zip on the Desktop (also done automatically at the end of each stage)
param([switch]$PackOnly)

$ErrorActionPreference = "Continue"
$Distro = "Ubuntu-24.04"
$Repo = "https://github.com/Nishanth-S-S/airway-aerosol-delivery.git"
$Proj = "/root/airway-aerosol-delivery"

function Say($m, $c = "White") { Write-Host $m -ForegroundColor $c }
function Step($n, $m) { Write-Host ""; Write-Host "=== Step $n of 7: $m ===" -ForegroundColor Cyan }
function Fail($m) {
    Write-Host ""
    Say $m Red
    Say "Take a screenshot of this window and send it to Nishanth." Yellow
    Read-Host "Press Enter to close"
    exit 1
}
# run a command in Linux as root; output goes to the screen, the exit code is returned
function L([string]$cmd) { & wsl.exe -d $Distro -u root -- bash -lc $cmd | Out-Host; return $LASTEXITCODE }
function LOut([string]$cmd) { $o = & wsl.exe -d $Distro -u root -- bash -lc $cmd 2>$null; return (($o | Select-Object -Last 1) -as [string]).Trim() }
function ToWsl([string]$p) {
    if ($p -notmatch '^[A-Za-z]:\\') { Fail "The folder must be on a drive letter like C: or D: (not a network path): $p" }
    return "/mnt/" + $p.Substring(0, 1).ToLower() + ($p.Substring(2) -replace '\\', '/')
}
function DistroReady {
    try { $l = (& wsl.exe -l -q 2>$null) -join "`n" } catch { return $false }
    return (($l -replace "`0", "") -match [regex]::Escape($Distro))
}
function PackResults([string]$label) {
    $desk = [Environment]::GetFolderPath("Desktop")
    $zip = Join-Path $desk ("airway_results_" + $label + "_" + (Get-Date -Format "yyyyMMdd_HHmm") + ".zip")
    $w = ToWsl $zip
    $null = L "cd $Proj && bash local/run.sh pack-results '$w'"
    if (Test-Path $zip) {
        Say ""
        Say "RESULTS FILE: $zip" Green
        Say "Send this file to Nishanth (Google Drive, WeTransfer or email)." Green
    } else { Say "Could not create the results file." Red }
}

function DataIn([string]$d, [int]$depth) {
    if (-not (Test-Path $d)) { return $null }
    $f = Get-ChildItem -Path $d -Recurse -Depth $depth -ErrorAction SilentlyContinue |
        Where-Object { -not $_.PSIsContainer -and ($_.Name -match '^airway_data\.tar\.part\d+$' -or $_.Name -match '^airway_data.*\.zip$') } |
        Select-Object -First 1
    if ($f) { return $f.DirectoryName } else { return $null }
}
function HasData([string]$d) { return [bool](DataIn $d 4) }
function FindData {
    $home_ = [Environment]::GetFolderPath("UserProfile")
    foreach ($r in @((Join-Path $home_ "Downloads"), [Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("MyDocuments"))) {
        $d = DataIn $r 3
        if (-not $d) { continue }
        if ($d -match '\\_unzipped\\') { return ($d -replace '\\_unzipped\\.*$', '') }   # our own earlier unzip
        $man = Join-Path $d "MANIFEST.json"
        if (Test-Path $man) {
            $n = (Get-Content $man -Raw | ConvertFrom-Json).n_parts
            $have = @(Get-ChildItem -Path $d -Filter "airway_data.tar.part*").Count
            if ($n -and $have -ge $n) { return $d }      # complete bundle in one folder
        }
        $z = @(Get-ChildItem -Path $d -Filter "airway_data*.zip").Count
        if ($z -gt 0) { return $d }                       # Google Drive zips (unzipped below)
        return (Split-Path $d -Parent)                    # parts spread over sibling folders
    }
    return $null
}

# ------------------------------------------------------------------ results only
if ($PackOnly) {
    if (-not (DistroReady)) { Fail "Linux is not installed yet - run START_HERE.bat first." }
    PackResults "manual"
    Read-Host "Press Enter to close"
    exit 0
}

# ------------------------------------------------------------------ administrator rights (needed to install Linux)
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}
$Host.UI.RawUI.WindowTitle = "Airway CFD study - KEEP THIS WINDOW OPEN"
Say "Airway CFD study - setup and run" Cyan
Say "You can run this file again at any time; it continues where it stopped." Gray

# ------------------------------------------------------------------ 1. Linux (WSL2 + Ubuntu)
Step 1 "Linux (WSL2 + Ubuntu 24.04)"
if (-not (DistroReady)) {
    Say "Installing Linux. This takes 5-15 minutes..."
    & wsl.exe --install -d $Distro --no-launch
    Start-Sleep 5
    if (-not (DistroReady)) {
        Say ""
        Say "Windows must RESTART to finish installing Linux." Yellow
        Say "After the restart, double-click START_HERE.bat again." Yellow
        Say "(If it still fails after a restart: turn on 'SVM Mode' / virtualization in the BIOS.)" Gray
        $r = Read-Host "Restart now? Type Y and press Enter (or just close this window to restart later)"
        if ($r -match '^[Yy]') { Restart-Computer -Force }
        exit 0
    }
}
$ok = LOut "echo ready"
if ($ok -ne "ready") {
    $launcher = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\ubuntu2404.exe"
    if (Test-Path $launcher) { & $launcher install --root | Out-Host }
    $ok = LOut "echo ready"
}
if ($ok -ne "ready") {
    Fail "Linux is installed but does not start. Restart the PC and run START_HERE.bat again. If that does not help: enable 'SVM Mode' (virtualization) in the BIOS."
}
Say "Linux is ready." Green

# ------------------------------------------------------------------ 2. Linux memory / CPU limits
Step 2 "Linux memory and CPU settings"
$cfg = Join-Path $env:USERPROFILE ".wslconfig"
$want = "[wsl2]`r`nmemory=56GB`r`nprocessors=32`r`n"
$have = if (Test-Path $cfg) { Get-Content $cfg -Raw } else { "" }
if ($have -notmatch 'memory=56GB') {
    if ($have) { Copy-Item $cfg "$cfg.backup" -Force }
    Set-Content -Path $cfg -Value $want -Encoding ASCII
    & wsl.exe --shutdown
    Start-Sleep 5
    Say "Linux may use 56 GB of memory and all 32 threads (restarted Linux to apply)." Green
} else { Say "Already set." Green }

# ------------------------------------------------------------------ 3. code
Step 3 "Download / update the study code"
$null = L "command -v git >/dev/null || (apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q git)"
$rc = L "if [ -d $Proj/.git ]; then cd $Proj && git config core.fileMode false && git fetch -q origin && (git merge --ff-only -q origin/main 2>/dev/null || git reset -q --keep origin/main || echo 'Note: code not updated, continuing with the current version'); else git clone -q $Repo $Proj && git -C $Proj config core.fileMode false; fi"
if ($rc -ne 0) { Fail "Could not download the code from GitHub. Check the internet connection and run START_HERE.bat again." }
Say "Code is up to date." Green
# keep these Windows files (START_HERE, STATUS, STOP, ...) up to date too, then restart once with the new version
if ($PSScriptRoot -match '^[A-Za-z]:\\' -and -not $env:AIRWAY_SELF_UPDATED) {
    $before = (Get-FileHash $PSCommandPath).Hash
    $wd = ToWsl $PSScriptRoot
    $null = L "cp -f $Proj/windows/*.ps1 $Proj/windows/*.bat $Proj/windows/*.md '$wd/' 2>/dev/null; true"
    if ((Get-FileHash $PSCommandPath).Hash -ne $before) {
        Say "This program was updated - restarting it..." Yellow
        $env:AIRWAY_SELF_UPDATED = "1"
        Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
        exit
    }
}

# ------------------------------------------------------------------ 4. tools
Step 4 "Install the simulation tools (first time: 10-20 minutes, later: seconds)"
$rc = L "cd $Proj && bash local/setup_linux.sh"
if ($rc -ne 0) { Fail "Tool installation failed (see the messages above)." }
Say "Tools are ready." Green

# ------------------------------------------------------------------ 5. data
Step 5 "Simulation data (about 7 GB, downloaded automatically)"
$rc = L "test -f $Proj/cases/airflow/V_MESH_fine_T_N40_SYM/processor7/0.52/U_0"
if ($rc -ne 0) {
    Say "Downloading the simulation data from GitHub (about 7 GB; 10-40 minutes depending on the internet)..." Yellow
    Say "(If it is interrupted, run START_HERE.bat again - it continues the download.)" Gray
    $rc = L "cd $Proj && bash local/fetch_data.sh"
    if ($rc -eq 1) { Fail "The data download failed (see above). Check the internet connection and run START_HERE.bat again - it continues where it stopped." }
}
if ($rc -ne 0) {
    # not on GitHub (or no internet): use a copy downloaded by hand (Google Drive / USB)
    $src = FindData
    if ($src) { Say "Found the data in: $src" Green }
    for ($try = 1; (-not $src) -and $try -le 3; $try++) {
        Say "Could not find the data automatically. A window will open: choose the folder where you saved" Yellow
        Say "the files from Nishanth's Google Drive link (NOT the program folder)." Yellow
        Say "(Files named MANIFEST.json and airway_data.tar.part01, part02, ... - or airway_data_for_friend-....zip)" Gray
        Add-Type -AssemblyName System.Windows.Forms
        $owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true }
        $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
        $dlg.Description = "Choose the folder with the data from Nishanth's Google Drive (airway_data.tar.part01 ... or airway_data...zip)"
        if ($dlg.ShowDialog($owner) -ne [System.Windows.Forms.DialogResult]::OK) {
            Fail "No folder chosen. Download the data from Nishanth's Google Drive link (about 7 GB), then run START_HERE.bat again."
        }
        if (HasData $dlg.SelectedPath) { $src = $dlg.SelectedPath }
        else { Say ""; Say "That folder does not contain the data: $($dlg.SelectedPath)" Red; Say "" }
    }
    if (-not $src) { Fail "Could not find the data. Download it from Nishanth's Google Drive link (about 7 GB) into Downloads, then run START_HERE.bat again." }
    $zips = Get-ChildItem -Path $src -Filter "airway_data*.zip" -Recurse -Depth 3 -ErrorAction SilentlyContinue
    foreach ($z in $zips) {
        $to = Join-Path $src ("_unzipped\" + $z.BaseName)
        if (-not (Test-Path $to)) { Say "Unzipping $($z.Name) (a few minutes)..."; Expand-Archive -Path $z.FullName -DestinationPath $to -Force }
    }
    $w = ToWsl $src
    Say "Copying and checking the data (5-15 minutes)..."
    $rc = L "cd $Proj && python3 local/bundle.py unpack '$w'"
    if ($rc -ne 0) { Fail "Could not unpack the data (reason above). If a part is missing, ask Nishanth to check the Google Drive folder has all 5 files, download again, and run START_HERE.bat again." }
}
Say "Data is in place." Green

# ------------------------------------------------------------------ 6. checks
Step 6 "Check the PC (CPU layout, memory, disk, identical software)"
$rc = L "set -o pipefail; cd $Proj && bash local/run.sh check | tail -n 25"
if ($rc -ne 0) { Fail "The PC check failed (see the 'problems' list above)." }
$next = LOut "cd $Proj && bash local/run.sh next"

# ------------------------------------------------------------------ 7. run
Step 7 "Run the simulation"
if ($next -eq "waiting") {
    Say "Stage 1 is FINISHED. Nothing to run until Nishanth sends the go-ahead." Green
    PackResults "stage1"
    Say "When Nishanth says the next stage is ready, double-click START_HERE.bat again." Yellow
    Read-Host "Press Enter to close"
    exit 0
}
if ($next -eq "done") {
    Say "The whole study is FINISHED. Thank you!" Green
    PackResults "final"
    Read-Host "Press Enter to close"
    exit 0
}
if ($next -ne "stage1" -and $next -ne "production") { Fail "Could not work out the next step (got '$next')." }

Say "Keep the PC awake while it runs (recommended):" Yellow
$r = Read-Host "Turn off sleep and hibernation while plugged in? Type Y and press Enter (or N)"
if ($r -match '^[Yy]') {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    Say "Sleep is off while plugged in." Green
}
Say "Please also pause Windows Update: Settings > Windows Update > Pause updates (1 week)." Yellow

$null = L "cd $Proj && bash local/run.sh $next"
$label = if ($next -eq "stage1") { "stage 1 (about 9-19 hours)" } else { "the main study (about 16-33 hours)" }
while ($true) {
    Start-Sleep 5
    $running = L "pgrep -f '[l]ocal/desktop.py $next' >/dev/null"
    Clear-Host
    Say "AIRWAY CFD STUDY - running $label" Cyan
    Say "KEEP THIS WINDOW OPEN (minimizing is fine). Closing it pauses the simulation;" Yellow
    Say "double-click START_HERE.bat to continue it. To stop safely: STOP.bat" Yellow
    Say ("Last update: " + (Get-Date -Format "yyyy-MM-dd HH:mm") + "   (refreshes every 5 minutes)") Gray
    Say ""
    $null = L "cd $Proj && bash local/run.sh status 2>/dev/null | tail -n 30"
    if ($running -ne 0) { break }
    Start-Sleep 295
}

$after = LOut "cd $Proj && bash local/run.sh next"
Say ""
if ($after -eq "waiting" -or $after -eq "done") {
    Say "FINISHED." Green
    PackResults $(if ($after -eq "done") { "final" } else { "stage1" })
} else {
    Say "The simulation stopped before finishing (stopped on purpose, or an error)." Yellow
    Say "Double-click START_HERE.bat to continue from where it stopped." Yellow
    Say "If it stops again with the same error, run SEND_RESULTS.bat and send the file to Nishanth." Yellow
    $null = L "cd $Proj && tail -n 15 logs/desktop_$next.out"
}
Read-Host "Press Enter to close"
