#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/workspace"
PYTEST_INI="/workspace/tests/pytest.ini"
PERIODIC_SCRIPT="/workspace/tools/run_tests_periodic.py"
REPORTS_DIR="/workspace/reports"

cd "$REPO_DIR"

if ! command -v poetry >/dev/null 2>&1; then
  echo "[hourly:test] Poetry not found; installing local user copy"
  python3 -m pip install --user "poetry>=1.8,<2.0"
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "[hourly:test] Ensuring dev dependencies are installed via Poetry"
cd "$REPO_DIR"
poetry config virtualenvs.in-project true
poetry install --with dev --no-ansi

while true; do
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Pulling latest changes..."
  git fetch --all --prune || true
  # Rebase onto origin/HEAD if possible; fallback to pull
  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD || echo "HEAD")
  if [[ "$CURRENT_BRANCH" != "HEAD" ]]; then
    git pull --rebase --autostash || git pull || true
  else
    git pull || true
  fi

  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Running pytest..."
  set +e
  poetry run pytest -q -c "$PYTEST_INI"
  PYTEST_EXIT=$?
  set -e

  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Running periodic test runner once..."
  set +e
  poetry run python "$PERIODIC_SCRIPT" --once --reports-dir "$REPORTS_DIR"
  PERIODIC_EXIT=$?
  set -e

  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Cycle complete. pytest=$PYTEST_EXIT periodic=$PERIODIC_EXIT"
  # Sleep for one hour
  sleep 3600
done
