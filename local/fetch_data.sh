#!/bin/bash
# Download the simulation data (~7 GB) from the GitHub release and unpack it into the project (SHA-256 checked).
#   bash local/fetch_data.sh            exit 0 = data in place, 2 = release not reachable (use a local copy instead)
# Interrupted downloads resume where they stopped; the downloaded parts are deleted after a verified unpack.
set -uo pipefail
cd "$(dirname "$0")/.."
TAG=${AIRWAY_DATA_TAG:-data-v1}
URL=${AIRWAY_DATA_URL:-"https://github.com/Nishanth-S-S/airway-aerosol-delivery/releases/download/$TAG"}   # override: tests
DL=${AIRWAY_DATA_DL:-$HOME/airway_data_download}
mkdir -p "$DL"

get() {   # resumable download with retries; a part already complete (same size as on GitHub) is not fetched again
  local size
  size=$(curl -fsIL "$URL/$1" | tr -d '\r' | awk 'tolower($1)=="content-length:"{n=$2} END{print n}')
  if [ -n "$size" ] && [ -f "$DL/$1" ] && [ "$(stat -c %s "$DL/$1" 2>/dev/null || stat -f %z "$DL/$1")" = "$size" ]; then
    echo "$1 already downloaded"; return 0
  fi
  for i in 1 2 3 4 5; do
    curl -fL --retry 3 --retry-delay 5 -C - -o "$DL/$1" "$URL/$1" && return 0
    echo "download of $1 interrupted - retrying ($i/5)"; sleep 10
  done
  return 1
}

curl -fsIL -o /dev/null "$URL/MANIFEST.json" || { echo "data release '$TAG' not reachable on GitHub"; exit 2; }
rm -f "$DL/MANIFEST.json"
get MANIFEST.json || exit 2
N=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['n_parts'])" "$DL/MANIFEST.json")
echo "downloading $N data parts (about 7 GB; resumes if interrupted)"
for i in $(seq 1 "$N"); do
  f=$(printf "airway_data.tar.part%02d" "$i")
  echo "part $i of $N"
  get "$f" || { echo "could not download $f"; exit 1; }
done
python3 local/bundle.py unpack "$DL" || exit 1
rm -f "$DL"/airway_data.tar.part*            # verified and unpacked: free the disk space
echo "data in place"
