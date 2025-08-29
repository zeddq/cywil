#!/usr/bin/env bash

set -euo pipefail
jj git fetch
ts="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_DIR="reports/${ts}"
mkdir -p "${REPORT_DIR}/tasks" ".jj-workspaces"
mapfile -t TASK_FILES < <(find pyright_reports -maxdepth 1 -type f -name 'report*.txt' -size +0c | sort)

# --- config and guards ---
: "${MAX_CONCURRENCY:=6}"
: "${BASE_BOOKMARK:=refactor/ai-sdk-integration-fix}"
: "${REPORT_DIR:=out}"              # original script used REPORT_DIR; normalize to REPORT_DIR
: "${TASK_FILES:?TASK_FILES must be a bash array of allowlist files}"

if ! command -v jj >/dev/null; then echo "jj not found"; exit 1; fi
if ! command -v jq >/dev/null; then echo "jq not found"; exit 1; fi
if ! command -v claude >/dev/null; then echo "claude CLI not found"; exit 1; fi

mkdir -p "${REPORT_DIR}/tasks" ".jj-workspaces"

running=0
max="${MAX_CONCURRENCY}"

# Ensure TASK_FILES is an array
if [[ "$(declare -p TASK_FILES 2>/dev/null)" != declare\ -a* ]]; then
  echo "TASK_FILES must be a bash array" >&2
  exit 1
fi

# Reap background jobs on exit
trap 'jobs -p >/dev/null && wait' EXIT

for TASK_FILE in "${TASK_FILES[@]}"; do
  # Skip non-existent allowlists
  [[ -f "$TASK_FILE" ]] || { echo "Skip missing allowlist: $TASK_FILE"; continue; }

  TASK_BASENAME="$(basename "${TASK_FILE}")"
  TASK_ID="$(basename "${TASK_BASENAME%.txt}" | sed 's/^report//')"

  ws=".jj-workspaces/ws-${TASK_ID}-${ts}"
  jj workspace add "${ws}"

  BOOKMARK="task/${TASK_ID}-${ts}"
  LOG="${REPORT_DIR}/tasks/${TASK_ID}.log"
  SUMMARY="${REPORT_DIR}/tasks/${TASK_ID}.summary.md"
  DIFF="${REPORT_DIR}/tasks/${TASK_ID}.diff.patch"
  PR_META="${REPORT_DIR}/tasks/${TASK_ID}.pr.json"
  STATE_FILE="${REPORT_DIR}/tasks/${TASK_ID}.state"

  # Orchestrator - run in isolated background job
  (
    # Ensure each background job has its own error handling
    set +e  # Disable errexit for this subshell
    
    # Phase 1 - run prefix script from within the workspace
    if "./scripts/pyright_worker_prefix.sh" \
      --workspace "${ws}" \
      --base "${BASE_BOOKMARK}" \
      --bookmark "${BOOKMARK}" \
      --allowlist-file "${TASK_FILE}" \
      --log "${LOG}" \
      --state-file "${STATE_FILE}"
    then
      echo "[orchestrator] Phase 1 complete for ${TASK_ID}" >> "${LOG}"

      # Phase 2
      echo "[orchestrator] Starting Phase 2: Claude AI for ${TASK_ID}" >> "${LOG}"

      ALLOWLIST_CONTENT="$(cat "${TASK_FILE}" 2>/dev/null || echo "No allowlist found")"

      # Set variables before export
      WORKSPACE_PATH="${ws}"
      ALLOWLIST_FILE="${TASK_FILE}"
      export TASK_ID WORKSPACE_PATH ALLOWLIST_FILE ALLOWLIST_CONTENT STATE_FILE

      # Run claude in a subshell with proper environment
      (
        # cd "${ws}" || { echo "[orchestrator] Failed to cd to ${ws}" >> "${LOG}"; exit 1; }

      CLAUDE_PROMPT="$(cat <<EOF
Spawn a new instance of linter-fixer (or Paralegal-linter-fixer if linter-fixer wasn't found) sub-agent to fix pyright ${TASK_ID} issues in isolated workspace.

Environment variables available to you directly in your environment (available for the new sub-agent as well):
- TASK_ID: Type of linter errors
- WORKSPACE_PATH: Your workspace path (which is the same as your jujutsu's workspace), which you can use to change your working directory to the workspace path.
- ALLOWLIST_FILE: File with a whitelist of files you are allowed to modify
- ALLOWLIST_CONTENT: Whitelist of files you are allowed to modify
- STATE_FILE: Path to the file with the sub-agent's state variables

Files allowed for modification:
${ALLOWLIST_CONTENT}

Instructions:
1. You are in workspace: ${ws}
2. Only modify files listed above
3. Fix pyright type errors for the ${TASK_ID} category
4. Make focused, reasonable changes
5. Preserve existing functionality
6. Add type annotations where needed
7. Import necessary types and modules
8. If a missing, required module is not found (and it isn't leftover code), add it via Poetry:
   - \`poetry add <pkg>\` for runtime deps, or \`poetry add --group dev <pkg>\` for dev-only
   - The lockfile will capture versions; no requirements.txt edits needed

Note: You can use the new variables in your commands, e.g., echo \$TASK_ID

Please proceed with the fixes.
EOF
)"

       echo "${CLAUDE_PROMPT}" >> "${LOG}"

        # Debug: log environment for troubleshooting
        echo "[orchestrator] Running Claude in workspace: $(pwd)" >> "${LOG}"
        echo "[orchestrator] TASK_ID=${TASK_ID}, WORKSPACE_PATH=${WORKSPACE_PATH}" >> "${LOG}"
        
        # Run claude command
        echo "${CLAUDE_PROMPT}" | claude --print \
          --model opus \
          --output-format stream-json \
          --dangerously-skip-permissions \
          --verbose \
          --add-dir . \
          > ".claude-result.json" 2>> "${LOG}"
      )
      CLAUDE_EXIT=$?

      if [[ $CLAUDE_EXIT -eq 0 ]]; then
        echo "[orchestrator] Phase 2 complete for ${TASK_ID}" >> "${LOG}"
        jq -r '.content // empty' "${ws}/.claude-result.json" >> "${LOG}" 2>/dev/null || true
      else
        echo "[orchestrator] Phase 2 failed for ${TASK_ID} with exit code: ${CLAUDE_EXIT}" >> "${LOG}"
      fi

      # Phase 3 - run postfix script with absolute paths
      ./scripts/pyright_worker_postfix.sh \
        --workspace "${ws}" \
        --state-file "${STATE_FILE}" \
        --summary "${SUMMARY}" \
        --diff "${DIFF}" \
        --log "${LOG}" \
        --pr-meta "${PR_META}" || true
    else
      echo "[orchestrator] Phase 1 failed for ${TASK_ID}" >> "${LOG}"
    fi
  ) &

  running=$((running+1))
  if (( running >= max )); then
    wait -n
    running=$((running-1))
  fi
done

wait
