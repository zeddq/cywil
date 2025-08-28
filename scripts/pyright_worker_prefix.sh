#!/usr/bin/env bash
# pyright_worker_prefix.sh — pre-fix setup phase for jj-based linter fixes
# Role: prepare workspace, sync repo, validate allowlist, set up environment

set -euo pipefail
umask 0022

usage() {
  cat <<'USAGE'
Usage:
  pyright_worker_prefix.sh --workspace PATH --bookmark NAME --allowlist-file FILE
                           [--base BOOKMARK] [--log PATH] [--state-file PATH]
                           [--task-id TASK_ID]
Outputs:
  - Sets up jj workspace and creates new change
  - Validates allowlist file exists and is readable
  - Writes state information for postfix script
  - Exits 0 on success, creates WORKSPACE_READY marker file

Env:
  BASE_BOOKMARK defaults to "main" if --base not provided.
USAGE
}

# -------- arg parse --------
WORKSPACE=""
BASE_BOOKMARK="${BASE_BOOKMARK:-main}"
BOOKMARK=""
ALLOWLIST_FILE=""
LOG=""
STATE_FILE=""
TASK_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)       WORKSPACE="$2"; shift 2 ;;
    --base)            BASE_BOOKMARK="$2"; shift 2 ;;
    --bookmark)        BOOKMARK="$2"; shift 2 ;;
    --allowlist-file)  ALLOWLIST_FILE="$2"; shift 2 ;;
    --log)             LOG="$2"; shift 2 ;;
    --state-file)      STATE_FILE="$2"; shift 2 ;;
    --task-id)         TASK_ID="$2"; shift 2 ;;
    -h|--help)         usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

[[ -n "$WORKSPACE" && -n "$BOOKMARK" && -n "$ALLOWLIST_FILE" ]] || { usage; exit 2; }
[[ -f "$ALLOWLIST_FILE" ]] || { echo "allowlist not found: $ALLOWLIST_FILE" >&2; exit 2; }

mkdir -p "$(dirname "${LOG:-/dev/null}")" \
         "$(dirname "${STATE_FILE:-/dev/null}")" 2>/dev/null || true

# -------- logging --------
if [[ -n "$LOG" ]]; then
  exec 1> >(tee -a "$LOG") 2>&1
fi

echo "[prefix] ws=$WORKSPACE base=$BASE_BOOKMARK bookmark=$BOOKMARK"
echo "[prefix] allowlist=$ALLOWLIST_FILE"

# The orchestrator should run this script in the workspace directory
# We verify we are in a jj workspace rather than trying to cd
if ! jj root >/dev/null 2>&1; then
  echo "[prefix] ERROR: not in a jj workspace or jj command failed" >&2
  exit 2
fi

# Verify we are in the expected workspace directory
if [[ "$(pwd)" != "$WORKSPACE" ]]; then
  echo "[prefix] ERROR: expected to be in $WORKSPACE, but in $(pwd)" >&2
  exit 2
fi

# -------- helpers --------
# return 0 if working-copy has no diff vs parent
wc_clean() { jj diff --quiet; }

# list changed files from current change vs parent
changed_files() {
  # Parse git-style diff headers from jj
  jj diff --git | awk '
    /^rename to / { print $3; next }
    /^\+\+\+ b\// { sub(/^(\+\+\+ b\/)/,""); print }
  ' | sed 's|\r$||' | sort -u
}

# verify all changed files are in allowlist
check_allowlist() {
  local tmp
  tmp="$(mktemp)"
  grep -v '^[[:space:]]*$' "$ALLOWLIST_FILE" | sed 's|\r$||' | sort -u > "$tmp"
  local ok=0
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    if ! grep -Fx -- "$f" "$tmp" >/dev/null; then
      echo "[guard] blocked change outside allowlist: $f"
      ok=1
    fi
  done < <(changed_files)
  rm -f "$tmp"
  return $ok
}

# -------- setup phase for the sub-agent --------
echo "[prefix] syncing repo"
jj git fetch

echo "[prefix] creating new change on base: $BASE_BOOKMARK"
jj new "$BASE_BOOKMARK"

# Validate we can read the allowlist
echo "[prefix] validating allowlist file"
if ! mapfile -t ALLOW_FILES < <(grep -v '^[[:space:]]*$' "$ALLOWLIST_FILE" | sed 's/\r$//'); then
  echo "[prefix] failed to read allowlist file" >&2
  exit 2
fi

echo "[prefix] allowlist contains ${#ALLOW_FILES[@]} files"

# Write state file for postfix script
if [[ -n "$STATE_FILE" ]]; then
  # Ensure directory exists
  mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null || true
  cat > "$STATE_FILE" <<EOF
WORKSPACE=$WORKSPACE
BASE_BOOKMARK=$BASE_BOOKMARK
BOOKMARK=$BOOKMARK
ALLOWLIST_FILE=$ALLOWLIST_FILE
PREFIX_TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
EOF
  echo "[prefix] state written to: $STATE_FILE"
fi

# Create ready marker
echo "[prefix] workspace ready for AI agent fixes"
# We are already in the workspace directory, so create the marker here
touch "WORKSPACE_READY"

echo "[prefix] setup complete - ready for AI agent phase"
