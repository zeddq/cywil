#!/usr/bin/env bash
# pyright_worker_postfix.sh — post-fix validation and commit phase for jj-based linter fixes
# Role: validate changes, run checks, commit, push, and create PR

set -euo pipefail
umask 0022

usage() {
  cat <<'USAGE'
Usage:
  pyright_worker_postfix.sh --workspace PATH [--state-file PATH]
                            [--summary PATH] [--diff PATH] [--log PATH] [--pr-meta PATH]
Inputs:
  - Expects WORKSPACE_READY marker file to exist
  - Reads state from --state-file if provided
  - Validates AI agent changes against allowlist
  - Commits, pushes, and creates PR if changes are valid

Env:
  RUN_TESTS_CMD optional, e.g. "tools/run_tests_periodic.py".
USAGE
}

# -------- arg parse --------
WORKSPACE=""
STATE_FILE=""
SUMMARY=""
DIFF=""
LOG=""
PR_META=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)       WORKSPACE="$2"; shift 2 ;;
    --state-file)      STATE_FILE="$2"; shift 2 ;;
    --summary)         SUMMARY="$2"; shift 2 ;;
    --diff)            DIFF="$2"; shift 2 ;;
    --log)             LOG="$2"; shift 2 ;;
    --pr-meta)         PR_META="$2"; shift 2 ;;
    -h|--help)         usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

[[ -n "$WORKSPACE" ]] || { usage; exit 2; }

mkdir -p "$(dirname "${SUMMARY:-/dev/null}")" \
         "$(dirname "${DIFF:-/dev/null}")" \
         "$(dirname "${LOG:-/dev/null}")" \
         "$(dirname "${PR_META:-/dev/null}")" 2>/dev/null || true

# -------- logging --------
if [[ -n "$LOG" ]]; then
  exec 1> >(tee -a "$LOG") 2>&1
fi

cd "$WORKSPACE"

# -------- validate setup --------
if [[ ! -f "WORKSPACE_READY" ]]; then
  echo "[postfix] ERROR: WORKSPACE_READY marker not found - prefix phase may have failed" >&2
  exit 2
fi

# Load state from prefix phase
BASE_BOOKMARK="main"
BOOKMARK=""
ALLOWLIST_FILE=""
PREFIX_TIMESTAMP=""

if [[ -n "$STATE_FILE" && -f "$STATE_FILE" ]]; then
  echo "[postfix] loading state from: $STATE_FILE"
  # shellcheck disable=SC1090
  source "$STATE_FILE"
else
  echo "[postfix] WARNING: no state file provided or found"
fi

echo "[postfix] ws=$WORKSPACE base=$BASE_BOOKMARK bookmark=$BOOKMARK"
echo "[postfix] allowlist=$ALLOWLIST_FILE"

has_cmd() { command -v "$1" >/dev/null 2>&1; }

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
  [[ -n "$ALLOWLIST_FILE" && -f "$ALLOWLIST_FILE" ]] || {
    echo "[guard] no allowlist file available for validation" >&2
    return 1
  }
  
  local tmp="$(mktemp)"
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

# -------- validation phase --------
echo "[postfix] checking for AI agent changes"

if wc_clean; then
  echo "[postfix] no changes detected; exiting"
  # still write a minimal summary if requested
  if [[ -n "$SUMMARY" ]]; then
    {
      echo "## Summary"
      echo "- Task: ${BOOKMARK:-unknown}"
      echo "- Base: $BASE_BOOKMARK"
      echo "- Result: no changes after AI agent phase"
      echo "- Timestamp: ${PREFIX_TIMESTAMP:-unknown}"
    } > "$SUMMARY"
  fi
  rm -f "WORKSPACE_READY" || true
  exit 0
fi

echo "[postfix] changes detected, validating against allowlist"

# Guardrail: enforce allowlist
if ! check_allowlist; then
  echo "[postfix] ABORTING: AI agent made changes outside allowlist scope" >&2
  exit 3
fi

echo "[postfix] allowlist validation passed"

# -------- refresh reports and run tests --------
# Optional: refresh pyright rule outputs
if [[ -x scripts/pyright_report_by_rule.py ]]; then
  echo "[postfix] running scripts/pyright_report_by_rule.py"
  scripts/pyright_report_by_rule.py || true
elif [[ -f scripts/pyright_report_by_rule.py ]]; then
  echo "[postfix] python scripts/pyright_report_by_rule.py"
  python scripts/pyright_report_by_rule.py || true
fi

# Optional: run tests
if [[ -n "${RUN_TESTS_CMD:-}" ]]; then
  echo "[postfix] tests: $RUN_TESTS_CMD"
  # shellcheck disable=SC2086
  $RUN_TESTS_CMD || true
elif [[ -x tools/run_tests_periodic.py ]]; then
  echo "[postfix] python tools/run_tests_periodic.py"
  python tools/run_tests_periodic.py || true
fi

# -------- commit --------
echo "[postfix] committing changes"
jj commit -m "chore(pyright): ${BOOKMARK:-automated} minimal fixes

AI agent applied fixes for files in allowlist.
Prefix timestamp: ${PREFIX_TIMESTAMP:-unknown}"

# -------- artifacts --------
if [[ -n "$DIFF" ]]; then
  echo "[postfix] generating diff: $DIFF"
  jj diff --git > "$DIFF"
fi

if [[ -n "$SUMMARY" ]]; then
  echo "[postfix] generating summary: $SUMMARY"
  {
    echo "## Summary"
    echo "- Task: ${BOOKMARK:-automated}"
    echo "- Base: $BASE_BOOKMARK"
    echo "- Prefix timestamp: ${PREFIX_TIMESTAMP:-unknown}"
    echo "- Postfix timestamp: $(date -u +%Y%m%dT%H%M%SZ)"
    echo ""
    echo "## Changed files"
    changed_files | sed 's/^/- /'
    echo ""
    echo "## Notes"
    echo "AI agent applied automated minimal fixes."
    echo "Files were validated against allowlist: ${ALLOWLIST_FILE:-unknown}"
  } > "$SUMMARY"
fi

# -------- push + PR --------
if [[ -n "$BOOKMARK" ]]; then
  echo "[postfix] pushing bookmark: $BOOKMARK"
  jj bookmark set "$BOOKMARK" -r @
  jj git push --bookmark "$BOOKMARK" --allow-new

  if has_cmd gh; then
    echo "[postfix] creating PR via gh"
    if gh pr create \
        --head "$BOOKMARK" \
        --title "[pyright] $BOOKMARK" \
        --body "$(printf 'AI agent applied automated minimal fixes for %s\n\nAllowlist: %s\nPrefix: %s\n' "$BOOKMARK" "$ALLOWLIST_FILE" "$PREFIX_TIMESTAMP")" \
        --fill --draft=false; then
      if [[ -n "$PR_META" ]]; then
        gh pr view --json url,number > "$PR_META" || true
      fi
      echo "[postfix] PR created successfully"
    else
      echo "[postfix] gh pr create failed; continuing"
    fi
  else
    echo "[postfix] gh not found; skipping PR creation"
  fi
else
  echo "[postfix] WARNING: no bookmark name available, skipping push"
fi

# cleanup
rm -f "WORKSPACE_READY" || true

echo "[postfix] post-fix phase complete"
