#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/workspace"
VENV="/workspace/.venv-test"
PYTEST_INI="/workspace/tests/pytest.ini"
PERIODIC_SCRIPT="/workspace/tools/run_tests_periodic.py"
REPORTS_DIR="/workspace/reports"

cd "$REPO_DIR"

# Ensure venv exists
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Test venv not found at $VENV. Creating..."
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip setuptools wheel
  "$VENV/bin/python" -m pip install -r "$REPO_DIR/requirements-test.txt"
fi

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
  "$VENV/bin/pytest" -q -c "$PYTEST_INI"
  PYTEST_EXIT=$?
  set -e

  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Running periodic test runner once..."
  set +e
  "$VENV/bin/python" "$PERIODIC_SCRIPT" --once --reports-dir "$REPORTS_DIR"
  PERIODIC_EXIT=$?
  set -e

  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Cycle complete. pytest=$PYTEST_EXIT periodic=$PERIODIC_EXIT"
  # Sleep for one hour
  sleep 3600
done