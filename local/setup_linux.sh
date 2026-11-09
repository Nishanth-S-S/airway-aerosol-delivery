#!/bin/bash
# One-time setup on the desktop (Ubuntu 24.04, native or inside WSL2). Mirrors cloud/instance/bootstrap.sh:
# Docker + the pinned OpenFOAM image, a Python env with the Mac's exact package versions. Safe to re-run.
#   bash local/setup_linux.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. Docker (Docker Desktop with WSL integration also works: then this step is skipped)
if ! command -v docker >/dev/null; then
  echo "Installing Docker Engine (asks for your password)"
  sudo apt-get update -q
  sudo apt-get install -y -q docker.io
  sudo usermod -aG docker "$USER"
  echo ">>> Docker installed. Close this terminal, open a new one, and run this script again."
  exit 0
fi
docker info >/dev/null 2>&1 || { echo "Docker is installed but not running / not usable by $USER (try: sudo systemctl start docker)"; exit 1; }

# 2. tools used by the scripts
for t in bzip2 curl; do command -v $t >/dev/null || { sudo apt-get install -y -q bzip2 curl; break; }; done

# 3. Python env identical to the Mac's (cloud/toolchain_reference.json; checked again by E1)
export MAMBA_ROOT_PREFIX=$HOME/micromamba
if [ ! -x "$HOME/.local/bin/micromamba" ]; then
  mkdir -p "$HOME/.local/bin"
  curl -sSL https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C "$HOME/.local" bin/micromamba
fi
if [ ! -x "$MAMBA_ROOT_PREFIX/envs/airway/bin/python3" ]; then
  "$HOME/.local/bin/micromamba" create -y -q -n airway -c conda-forge \
    python=3.10.11 numpy=1.26.4 pandas=2.2.3 scipy=1.10.0 matplotlib=3.7.1 pyyaml=6.0.1
fi

# 4. the pinned OpenFOAM image (same digest as the Mac)
IMAGE=$("$MAMBA_ROOT_PREFIX/envs/airway/bin/python3" -c 'import json;print(json.load(open("cloud/toolchain_reference.json"))["docker_image"])')
docker pull "$IMAGE"

# 5. executables (git / zip transfers can drop the executable bit)
chmod +x local/*.sh tools/openfoam/bin/* 2>/dev/null || true

# 6. CPU layout: WSL2 often hides the cache topology -> pin the two CCDs explicitly
PY=$MAMBA_ROOT_PREFIX/envs/airway/bin/python3
GROUPS_FOUND=$("$PY" -c 'import sys;sys.path.insert(0,"cloud/runner");from cloud_runner import core_groups;print(";".join(",".join(map(str,g)) for g in core_groups()))')
echo "core groups detected (one thread per physical core): $GROUPS_FOUND"
if grep -qi microsoft /proc/version && [ ! -f local/desktop.env ]; then
  echo "WSL2 detected: saving the detected layout to local/desktop.env (edit it if 'check' reports a problem)"
  echo "export AIRWAY_CORE_GROUPS=\"$GROUPS_FOUND\"" > local/desktop.env
fi
echo
echo "Setup done. Next: bash local/run.sh check"
