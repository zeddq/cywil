#!/usr/bin/env bash
# pyright_orchestrate.sh — orchestrate pyright fixes for multiple tasks
# Role: run inside one jj workspace created by the orchestrator.

set -euo pipefail
umask 0077  # More restrictive permissions

# Cleanup trap for interrupted executions
cleanup() {
  local exit_code=$?
  if [[ -n "${WORKSPACE:-}" ]] && [[ -d "$WORKSPACE" ]]; then
    cd "$WORKSPACE" 2>/dev/null || true
    # Clean up any uncommitted changes if script fails
    if [[ $exit_code -ne 0 ]] && ! jj diff --quiet 2>/dev/null; then
      echo "[cleanup] reverting uncommitted changes due to failure" >&2
      jj restore 2>/dev/null || true
    fi
  fi
  exit $exit_code
}
trap cleanup EXIT INT TERM

# Logging with timestamps
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

error() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
}

usage() {
  cat <<'USAGE'
Usage:
  pyright_worker.sh --workspace PATH --bookmark NAME --allowlist-file FILE
                    [--base BOOKMARK] [--summary PATH] [--diff PATH]
                    [--log PATH] [--pr-meta PATH] [--agent-cmd CMD]
                    [--dry-run] [--timeout SECONDS]
Env:
  BASE_BOOKMARK defaults to "main" if --base not provided.
  RUN_TESTS_CMD optional, e.g. "tools/run_tests_periodic.py".
Notes:
  - Runs jj in colocated repo.
  - Edits outside allowlist are blocked.
  - No change => no commit, no push.
  - Use --dry-run to test without making commits.
USAGE
}

# -------- arg parse --------
WORKSPACE=""
BASE_BOOKMARK="${BASE_BOOKMARK:-main}"
BOOKMARK=""
ALLOWLIST_FILE=""
SUMMARY=""
DIFF=""
LOG=""
PR_META=""
AGENT_CMD="${AGENT_CMD:-}"   # optional external fixer
DRY_RUN=false
TIMEOUT=1800  # 30 minutes default

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)       WORKSPACE="$2"; shift 2 ;;
    --base)            BASE_BOOKMARK="$2"; shift 2 ;;
    --bookmark)        BOOKMARK="$2"; shift 2 ;;
    --allowlist-file)  ALLOWLIST_FILE="$2"; shift 2 ;;
    --summary)         SUMMARY="$2"; shift 2 ;;
    --diff)            DIFF="$2"; shift 2 ;;
    --log)             LOG="$2"; shift 2 ;;
    --pr-meta)         PR_META="$2"; shift 2 ;;
    --agent-cmd)       AGENT_CMD="$2"; shift 2 ;;
    --dry-run)         DRY_RUN=true; shift ;;
    --timeout)         TIMEOUT="$2"; shift 2 ;;
    -h|--help)         usage; exit 0 ;;
    *) error "unknown arg: $1"; usage; exit 1 ;;
  esac
done

# -------- validation --------
[[ -n "$WORKSPACE" && -n "$BOOKMARK" && -n "$ALLOWLIST_FILE" ]] || { 
  error "missing required arguments"
  usage
  exit 1
}

# Validate workspace path (prevent path traversal)
if [[ ! "$WORKSPACE" =~ ^[a-zA-Z0-9/_.-]+$ ]] || [[ "$WORKSPACE" =~ \.\. ]]; then
  error "invalid workspace path: $WORKSPACE"
  exit 1
fi

if [[ ! -d "$WORKSPACE" ]]; then
  error "workspace directory not found: $WORKSPACE"
  exit 1
fi

if [[ ! -f "$ALLOWLIST_FILE" ]]; then
  error "allowlist not found: $ALLOWLIST_FILE"
  exit 1
fi

# Validate timeout is a number
if ! [[ "$TIMEOUT" =~ ^[0-9]+$ ]]; then
  error "timeout must be a positive integer: $TIMEOUT"
  exit 1
fi

# Create output directories safely
for dir in "$(dirname "${SUMMARY:-/dev/null}")" \
           "$(dirname "${DIFF:-/dev/null}")" \
           "$(dirname "${LOG:-/dev/null}")" \
           "$(dirname "${PR_META:-/dev/null}")"; do
  if [[ "$dir" != "/dev" ]] && [[ ! -d "$dir" ]]; then
    mkdir -p "$dir" || {
      error "failed to create directory: $dir"
      exit 1
    }
  fi
done

# -------- logging setup --------
if [[ -n "$LOG" ]]; then
  exec 1> >(tee -a "$LOG") 2>&1
fi

log "worker starting: ws=$WORKSPACE base=$BASE_BOOKMARK bookmark=$BOOKMARK"
log "allowlist=$ALLOWLIST_FILE dry_run=$DRY_RUN timeout=${TIMEOUT}s"

cd "$WORKSPACE" || {
  error "failed to change to workspace: $WORKSPACE"
  exit 1
}

# Verify jj repository
if ! timeout 10 jj root >/dev/null 2>&1; then
  error "not a jj repository or jj command failed: $WORKSPACE"
  exit 1
fi

has_cmd() { command -v "$1" >/dev/null 2>&1; }

# -------- helpers --------
# return 0 if working-copy has no diff vs parent
wc_clean() { 
  timeout 30 jj diff --quiet 2>/dev/null || return 1
}

# list changed files from current change vs parent
changed_files() {
  # Parse git-style diff headers from jj with better error handling
  if ! timeout 60 jj diff --git 2>/dev/null; then
    error "failed to get diff"
    return 1
  fi | awk '
    /^rename to / { print $3; next }
    /^\+\+\+ b\// { 
      sub(/^\+\+\+ b\//, ""); 
      # Remove any trailing carriage returns
      gsub(/\r$/, "");
      if (length($0) > 0) print
    }
  ' | sort -u
}

# verify all changed files are in allowlist
check_allowlist() {
  local tmp
  tmp="$(mktemp)" || {
    error "failed to create temporary file"
    return 1
  }
  
  # Fixed grep pattern to filter out comments and empty lines
  if ! grep -v '^[[:space:]]*#' "$ALLOWLIST_FILE" | grep -v '^[[:space:]]*$' | sed 's|\r$||' | sort -u > "$tmp"; then
    error "failed to process allowlist file"
    rm -f "$tmp"
    return 1
  fi
  
  local violations=0
  local changed_file_list
  
  if ! changed_file_list="$(changed_files)"; then
    error "failed to get changed files list"
    rm -f "$tmp"
    return 1
  fi
  
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    if ! grep -Fx -- "$f" "$tmp" >/dev/null; then
      error "blocked change outside allowlist: $f"
      violations=$((violations + 1))
    fi
  done <<< "$changed_file_list"
  
  rm -f "$tmp"
  return $violations
}

# Execute command with timeout and error handling
run_with_timeout() {
  local cmd_timeout="$1"
  shift
  log "executing: $*"
  if ! timeout "$cmd_timeout" "$@"; then
    error "command failed or timed out: $*"
    return 1
  fi
}

# -------- start --------
log "fetching latest changes"
if ! run_with_timeout 300 jj git fetch; then
  error "git fetch failed"
  exit 1
fi

# Check if base bookmark exists
if ! jj log -r "$BASE_BOOKMARK" --no-graph -T 'empty' >/dev/null 2>&1; then
  error "base bookmark not found: $BASE_BOOKMARK"
  exit 1
fi

# Start a new change on top of base
log "creating new change on top of $BASE_BOOKMARK"
if ! run_with_timeout 30 jj new "$BASE_BOOKMARK"; then
  error "failed to create new change"
  exit 1
fi

# -------- fixer phase --------
if [[ -n "$AGENT_CMD" ]]; then
  log "running agent command: $AGENT_CMD"
  
  # Parse command safely to prevent injection
  read -ra cmd_array <<< "$AGENT_CMD"
  
  if [[ ${#cmd_array[@]} -eq 0 ]]; then
    error "empty agent command"
    exit 1
  fi
  
  # Verify first element is a valid command
  if ! has_cmd "${cmd_array[0]}"; then
    error "agent command not found: ${cmd_array[0]}"
    exit 1
  fi
  
  # Execute with timeout
  if ! run_with_timeout "$TIMEOUT" "${cmd_array[@]}"; then
    error "agent command failed: $AGENT_CMD"
    exit 1
  fi
else
  log "no --agent-cmd provided; proceeding without automated edits"
fi

# Optional: refresh pyright rule outputs
if [[ -x scripts/pyright_report_by_rule.py ]]; then
  log "running scripts/pyright_report_by_rule.py"
  run_with_timeout 300 scripts/pyright_report_by_rule.py || {
    error "pyright_report_by_rule.py failed, but continuing"
  }
elif [[ -f scripts/pyright_report_by_rule.py ]] && has_cmd python; then
  log "running python scripts/pyright_report_by_rule.py"
  run_with_timeout 300 python scripts/pyright_report_by_rule.py || {
    error "pyright_report_by_rule.py failed, but continuing"
  }
fi

# Optional: run tests
if [[ -n "${RUN_TESTS_CMD:-}" ]]; then
  log "running tests: $RUN_TESTS_CMD"
  read -ra test_cmd_array <<< "$RUN_TESTS_CMD"
  run_with_timeout "$TIMEOUT" "${test_cmd_array[@]}" || {
    error "tests failed, but continuing"
  }
elif [[ -x tools/run_tests_periodic.py ]]; then
  log "running python tools/run_tests_periodic.py"
  run_with_timeout "$TIMEOUT" python tools/run_tests_periodic.py || {
    error "tests failed, but continuing"
  }
fi

# -------- evaluate --------
if wc_clean; then
  log "no changes detected; exiting"
  # still write a minimal summary if requested
  if [[ -n "$SUMMARY" ]]; then
    {
      echo "## Summary"
      echo "- Task: $BOOKMARK"
      echo "- Base: $BASE_BOOKMARK"
      echo "- Result: no changes"
      echo "- Timestamp: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    } > "$SUMMARY"
  fi
  exit 0
fi

# Guardrail: enforce allowlist
log "checking allowlist compliance"
if ! check_allowlist; then
  error "aborting due to out-of-scope edits"
  exit 2
fi

log "allowlist check passed"

# -------- commit --------
if [[ "$DRY_RUN" == "true" ]]; then
  log "dry-run mode: would commit changes but skipping actual commit"
else
  log "committing changes"
  if ! run_with_timeout 60 jj commit -m "chore(pyright): ${BOOKMARK} minimal fixes"; then
    error "commit failed"
    exit 1
  fi
fi

# -------- artifacts --------
if [[ -n "$DIFF" ]]; then
  log "generating diff output"
  if ! run_with_timeout 60 jj diff --git > "$DIFF"; then
    error "failed to generate diff"
  fi
fi

if [[ -n "$SUMMARY" ]]; then
  log "generating summary"
  {
    echo "## Summary"
    echo "- Task: $BOOKMARK"
    echo "- Base: $BASE_BOOKMARK"
    echo "- Dry run: $DRY_RUN"
    echo "- Timestamp: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo ""
    echo "## Changed files"
    if changed_file_list="$(changed_files)"; then
      echo "${changed_file_list//^/- }"
    else
      echo "- (failed to get file list)"
    fi
    echo ""
    echo "## Notes"
    echo "Automated minimal fixes for files listed in: $ALLOWLIST_FILE"
    if [[ -n "$AGENT_CMD" ]]; then
      echo "Agent command: $AGENT_CMD"
    fi
  } > "$SUMMARY"
fi

# -------- push + PR --------
if [[ "$DRY_RUN" == "true" ]]; then
  log "dry-run mode: would push and create PR but skipping"
  exit 0
fi

log "setting bookmark and pushing"
if ! run_with_timeout 60 jj bookmark set "$BOOKMARK" -r @; then
  error "failed to set bookmark"
  exit 1
fi

if ! run_with_timeout 300 jj git push --bookmark "$BOOKMARK" --allow-new; then
  error "git push failed"
  exit 1
fi

if has_cmd gh; then
  log "creating PR via gh"
  pr_body=$(printf 'Automated minimal fixes for %s\n\nReport: %s\nTimestamp: %s\n' \
    "$BOOKMARK" "$ALLOWLIST_FILE" "$(date -u '+%Y-%m-%d %H:%M:%S UTC')")
  
  if run_with_timeout 120 gh pr create \
      --head "$BOOKMARK" \
      --title "[pyright] $BOOKMARK" \
      --body "$pr_body" \
      --fill --draft=false; then
    log "PR created successfully"
    if [[ -n "$PR_META" ]]; then
      if ! run_with_timeout 30 gh pr view --json url,number > "$PR_META"; then
        error "failed to save PR metadata"
      fi
    fi
  else
    error "gh pr create failed; continuing"
  fi
else
  log "gh not found; skipping PR creation"
fi

log "worker completed successfully"
