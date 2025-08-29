#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

# Poetry-based build; ensure lockfile exists and then delegate
if [[ ! -f poetry.lock ]]; then
  echo "[build-fix] poetry.lock missing. Run 'poetry lock' locally and commit the file." >&2
  exit 1
fi

./deployment/scripts/build-and-deploy.sh "$@"
