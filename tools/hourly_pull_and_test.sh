#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/workspace"
VENV="/workspace/.venv-test"
PYTEST_INI="/workspace/tests/pytest.ini"
PERIODIC_SCRIPT="/workspace/tools/run_tests_periodic.py"
PYRIGHT_SCRIPT="/workspace/scripts/pyright_report_by_rule.py"
REPORTS_DIR="/workspace/reports"
FEATURE_BRANCH="cursor/run-tests-hourly-after-pulling-changes-b4fb"
PARENT_BRANCH="refactor/ai-sdk-integration-fix"

cd "$REPO_DIR"

# Ensure venv bin is on PATH so console scripts (pyright) are found
export PATH="$VENV/bin:$PATH"

# Ensure venv exists
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Test venv not found at $VENV. Creating..."
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip setuptools wheel
  "$VENV/bin/python" -m pip install -r "$REPO_DIR/requirements-test.txt"
fi

# Ensure pyright is installed in venv (for pyright_report_by_rule.py)
if ! "$VENV/bin/python" -c "import shutil; import sys; sys.exit(0 if shutil.which('pyright') else 1)"; then
  echo "Installing pyright into test venv..."
  "$VENV/bin/python" -m pip install pyright
fi

# Configure git identity if missing
if ! git config --get user.email >/dev/null; then
  git config user.email "hourly-bot@example.com"
fi
if ! git config --get user.name >/dev/null; then
  git config user.name "Hourly Test Bot"
fi

while true; do
  TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "[$TS] Rebase $FEATURE_BRANCH onto $PARENT_BRANCH (taking parent changes on conflicts) and pull latest..."
  git fetch origin "$PARENT_BRANCH" "$FEATURE_BRANCH" --prune || true
  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD || echo "")
  if [[ "$CURRENT_BRANCH" != "$FEATURE_BRANCH" ]]; then
    git checkout "$FEATURE_BRANCH" || git checkout -B "$FEATURE_BRANCH" "origin/$FEATURE_BRANCH"
  fi
  # Rebase onto parent, preferring parent changes on conflicts; fallback to merge if needed
  set +e
  git rebase -X theirs "origin/$PARENT_BRANCH"
  REBASE_STATUS=$?
  if [[ $REBASE_STATUS -ne 0 ]]; then
    echo "Rebase failed; attempting to abort and merge with -X theirs..."
    git rebase --abort || true
    git merge -X theirs "origin/$PARENT_BRANCH"
  fi
  # Ensure we're up to date with remote feature branch (fast-forward if any)
  git pull --rebase --autostash origin "$FEATURE_BRANCH" || git pull origin "$FEATURE_BRANCH" || true
  set -e

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

  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Running pyright report by rule..."
  set +e
  "$VENV/bin/python" "$PYRIGHT_SCRIPT"
  PYRIGHT_EXIT=$?
  set -e

  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Committing and pushing cycle outputs to $FEATURE_BRANCH..."
  git add -A
  if git diff --cached --quiet; then
    echo "No changes to commit."
  else
    git commit -m "chore(ci): hourly run $TS (pytest=$PYTEST_EXIT periodic=$PERIODIC_EXIT pyright=$PYRIGHT_EXIT)"
    git push origin "$FEATURE_BRANCH" || echo "Push failed (check credentials/remotes)."
  fi

  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Cycle complete. pytest=$PYTEST_EXIT periodic=$PERIODIC_EXIT pyright=$PYRIGHT_EXIT"
  # Sleep for one hour
  sleep 3600
done