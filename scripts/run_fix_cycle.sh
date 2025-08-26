#!/usr/bin/env bash
set -euo pipefail
BRANCH_FEATURE="cursor/pull-and-fix-linter-issues-periodically-af86"
BRANCH_PARENT="refactor/ai-sdk-integration-fix"
REPO_DIR="/workspace"
LOG="/workspace/branch_watcher.log"
cd "$REPO_DIR"
{
  echo "[$(date -Iseconds)] Start fix cycle"
  git fetch origin --prune
  # Ensure feature branch is checked out locally
  if git rev-parse --verify "$BRANCH_FEATURE" >/dev/null 2>&1; then
    git checkout "$BRANCH_FEATURE"
  else
    if git show-ref --verify --quiet refs/remotes/origin/$BRANCH_FEATURE; then
      git checkout -B "$BRANCH_FEATURE" "origin/$BRANCH_FEATURE"
    else
      # create from parent if feature branch missing on remote
      git checkout -B "$BRANCH_FEATURE" "origin/$BRANCH_PARENT"
      git push -u origin "$BRANCH_FEATURE" || true
    fi
  fi
  # Merge parent into feature preferring parent on conflicts
  set +e
  git merge -X theirs --no-edit "origin/$BRANCH_PARENT"
  merge_status=$?
  set -e
  if [ $merge_status -ne 0 ]; then
    echo "Merge reported conflicts, attempting hard reset to parent per policy"
    git reset --hard "origin/$BRANCH_PARENT"
  fi
  # Run pyright and commit results
  if [ -x "/workspace/.venv/bin/pyright" ]; then
    /workspace/.venv/bin/pyright -p pyrightconfig.json --outputjson > pyright-output.json || true
  else
    echo "pyright not found at /workspace/.venv/bin/pyright" >&2
  fi
  git add -A
  if ! git diff --cached --quiet; then
    git commit -m "chore: scheduled pyright run and sync with $BRANCH_PARENT"
    git push origin "$BRANCH_FEATURE"
  else
    echo "No changes to commit"
  fi
  echo "[$(date -Iseconds)] End fix cycle"
} >>"$LOG" 2>&1
