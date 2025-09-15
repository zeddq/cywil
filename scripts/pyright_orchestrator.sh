#!/usr/bin/env bash
# pyright_orchestrator.sh — orchestrate parallel pyright fix workers with AI agent integration
# Role: spawn and coordinate multiple linter-fix workers using Jujutsu workspaces with concurrency control

set -euo pipefail
umask 0022

# Cleanup trap for interrupted executions
cleanup() {
  local exit_code=$?
  echo "[orchestrator] cleanup triggered with exit code: $exit_code"
  
  # Kill any remaining background jobs
  jobs -p | xargs -r kill 2>/dev/null || true
  
  # Clean up any temporary workspaces if needed
  if [[ -d ".jj-workspaces" ]]; then
    for ws in .jj-workspaces/ws-*; do
      if [[ -d "$ws" ]]; then
        local ws_name
        ws_name="$(basename "$ws")"
        jj workspace forget "$ws_name" 2>/dev/null || true
        rm -rf "$ws" 2>/dev/null || true
      fi
    done
  fi
  
  exit $exit_code
}
trap cleanup EXIT INT TERM

# Logging with timestamps
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [orchestrator] $*"
}

error() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [orchestrator] ERROR: $*" >&2
}

usage() {
  cat <<'USAGE'
Usage:
  pyright_orchestrator.sh [--base BOOKMARK] [--max-concurrency N] [--reports-dir DIR]
                          [--dry-run] [--help]

Options:
  --base BOOKMARK         Base bookmark to work from (default: main)
  --max-concurrency N     Maximum concurrent workers (default: 6)
  --reports-dir DIR       Directory containing pyright reports (default: pyright_reports)
  --dry-run               Don't make actual commits or pushes
  --help                  Show this help message

Environment:
  BASE_BOOKMARK           Default base bookmark if --base not provided
  MAX_CONCURRENCY         Default concurrency if --max-concurrency not provided

Description:
  Orchestrates parallel pyright fix workers using Jujutsu workspaces.
  Each worker processes one pyright report file through a three-phase process:
  1. Prefix phase: Setup workspace and validate
  2. AI Agent phase: Apply fixes using Claude Code
  3. Postfix phase: Validate, commit, push, and create PR

Output:
  Creates reports/{timestamp}/ directory with:
  - merged_report.md: Combined report of all tasks
  - tasks/{task_id}.{summary.md,diff.patch,log,pr.json,state}: Per-task artifacts
USAGE
}

# -------- argument parsing --------
BASE_BOOKMARK="${BASE_BOOKMARK:-main}"
MAX_CONCURRENCY="${MAX_CONCURRENCY:-6}"
REPORTS_DIR="pyright_reports"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)                BASE_BOOKMARK="$2"; shift 2 ;;
    --max-concurrency)     MAX_CONCURRENCY="$2"; shift 2 ;;
    --reports-dir)         REPORTS_DIR="$2"; shift 2 ;;
    --dry-run)             DRY_RUN=true; shift ;;
    -h|--help)             usage; exit 0 ;;
    *) error "unknown argument: $1"; usage; exit 1 ;;
  esac
done

# -------- validation --------
if ! [[ "$MAX_CONCURRENCY" =~ ^[0-9]+$ ]] || [[ "$MAX_CONCURRENCY" -lt 1 ]]; then
  error "invalid max concurrency: $MAX_CONCURRENCY"
  exit 1
fi

if [[ ! -d "$REPORTS_DIR" ]]; then
  error "reports directory not found: $REPORTS_DIR"
  exit 1
fi

# Check for required tools
for tool in jj gh claude; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    error "required tool not found: $tool"
    exit 1
  fi
done

# Verify jj repository
if ! jj root >/dev/null 2>&1; then
  error "not a jj repository or jj command failed"
  exit 1
fi

# -------- preparation --------
log "starting orchestration run"
log "base=$BASE_BOOKMARK max_concurrency=$MAX_CONCURRENCY reports_dir=$REPORTS_DIR dry_run=$DRY_RUN"

# Sync base
log "syncing repository"
if ! jj git fetch; then
  error "git fetch failed"
  exit 1
fi

# Check if base bookmark exists
if ! jj log -r "$BASE_BOOKMARK" --no-graph -T 'empty' >/dev/null 2>&1; then
  error "base bookmark not found: $BASE_BOOKMARK"
  exit 1
fi

# Create timestamp and output directory
ts="$(date -u +%Y%m%dT%H%M%SZ)"
out_dir="reports/${ts}"
mkdir -p "${out_dir}/tasks" ".jj-workspaces"

log "output directory: $out_dir"

# Build task queue from non-empty report files
mapfile -t TASK_FILES < <(find "$REPORTS_DIR" -maxdepth 1 -type f -name 'report*.txt' -size +0c | sort)

if [[ ${#TASK_FILES[@]} -eq 0 ]]; then
  log "no non-empty report files found in $REPORTS_DIR"
  exit 0
fi

log "found ${#TASK_FILES[@]} non-empty report files to process"

# -------- worker orchestration --------
running=0
max="$MAX_CONCURRENCY"
worker_pids=()

# Function to process a single task (runs in background)
process_task() {
  local task_file="$1"
  local task_id="$2"
  local workspace="$3"
  local bookmark="$4"
  local log_file="$5"
  local summary_file="$6"
  local diff_file="$7"
  local pr_meta_file="$8"
  local state_file="$9"
  
  # Redirect all output to log file
  exec 1>> "$log_file" 2>&1
  
  echo "[worker-$task_id] starting at $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  echo "[worker-$task_id] task_file=$task_file"
  echo "[worker-$task_id] workspace=$workspace"
  echo "[worker-$task_id] bookmark=$bookmark"
  
  # Create workspace
  echo "[worker-$task_id] creating jj workspace"
  if ! jj workspace add "$workspace"; then
    echo "[worker-$task_id] ERROR: failed to create workspace: $workspace"
    return 1
  fi
  
  # Phase 1: Setup workspace and validate
  echo "[worker-$task_id] Phase 1: Running prefix script"
  # Save current directory for absolute paths
  local orig_dir
  orig_dir="$(pwd)"
  if (cd "$workspace" && "$orig_dir/scripts/pyright_worker_prefix.sh" \
    --workspace "$orig_dir/$workspace" \
    --base "$BASE_BOOKMARK" \
    --bookmark "$bookmark" \
    --allowlist-file "$orig_dir/$task_file" \
    --state-file "$orig_dir/$state_file" \
    --task-id "$task_id"); then
    
    echo "[worker-$task_id] Phase 1 complete"
    
    # Phase 2: AI Agent using Claude CLI
    echo "[worker-$task_id] Phase 2: Starting Claude AI agent"
    
    # Read allowlist content
    local allowlist_content
    allowlist_content=$(cat "$task_file" 2>/dev/null || echo "No allowlist found")
    
    # Create the prompt for Claude
    local claude_prompt
    read -r -d '' claude_prompt << EOF || true
Spawn a new instance of linter-fixer (or Paralegal-linter-fixer if linter-fixer wasn't found) sub-agent to fix pyright ${task_id} issues in isolated workspace.

Environment variables available to you directly in your environment (available for the new sub-agent as well):
- TASK_ID: Type of linter errors
- WORKSPACE_PATH: Your cwd and the name of your jujutsu's workspace
- ALLOWLIST_FILE: File with a whitelist of files you are allowed to modify
- ALLOWLIST_CONTENT: Whitelist of files you are allowed to modify
- STATE_FILE: Path to the file with the sub-agent's state variables

Files allowed for modification:
${allowlist_content}

Instructions:
1. You are in workspace: ${workspace}
2. Only modify files listed above
3. Fix pyright type errors for the ${task_id} category
4. Make focused, reasonable changes
5. Preserve existing functionality
6. Add type annotations where needed
7. Import necessary types and modules
8. If a missing, required module is not found and you're sure it's not an item that's been forgotten to be removed after some previous refactoring then install this module and add it to requirements.txt and requirements-test.txt (pinned to the installed version)

Note: You can use the new variables in your commands, e.g., echo \$TASK_ID

Please proceed with the fixes.
EOF

    # Export environment variables for Claude to use
    export TASK_ID="$task_id"
    export WORKSPACE_PATH="$workspace"
    export ALLOWLIST_FILE="$task_file"
    export ALLOWLIST_CONTENT="$allowlist_content"
    export STATE_FILE="$state_file"
    
    # Run Claude with the task (in workspace directory)
    local claude_exit=0
    if [[ "$DRY_RUN" == "true" ]]; then
      echo "[worker-$task_id] DRY-RUN: would run Claude CLI with task"
      echo '{"content": "DRY-RUN mode - no actual fixes applied"}' > "$workspace/.claude-result.json"
    else
      (cd "$workspace" && claude --print \
        --model sonnet \
        --output-format json \
        --dangerously-skip-permissions \
        --add-dir . \
        "$claude_prompt" > ".claude-result.json" 2>> "$log_file") || claude_exit=$?
    fi
    
    if [[ $claude_exit -eq 0 ]]; then
      echo "[worker-$task_id] Phase 2 complete"
      # Extract response content from JSON if available
      if [[ -f "$workspace/.claude-result.json" ]]; then
        jq -r '.content // empty' "$workspace/.claude-result.json" 2>/dev/null || true
      fi
    else
      echo "[worker-$task_id] Phase 2 failed with exit code: $claude_exit"
    fi
    
    # Phase 3: Validation and commit
    echo "[worker-$task_id] Phase 3: Running postfix script"
    if [[ "$DRY_RUN" == "true" ]]; then
      echo "[worker-$task_id] DRY-RUN: would run postfix script"
    else
      ./scripts/pyright_worker_postfix.sh \
        --workspace "$workspace" \
        --state-file "$state_file" \
        --summary "$summary_file" \
        --diff "$diff_file" \
        --pr-meta "$pr_meta_file" || true
    fi
    
  else
    echo "[worker-$task_id] Phase 1 failed"
  fi
  
  # Cleanup workspace
  echo "[worker-$task_id] cleaning up workspace"
  local ws_name
  ws_name="$(basename "$workspace")"
  jj workspace forget "$ws_name" 2>/dev/null || true
  rm -rf "$workspace" 2>/dev/null || true
  
  echo "[worker-$task_id] completed at $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
}

# Process each task with concurrency control
for task_file in "${TASK_FILES[@]}"; do
  # Extract task ID from filename (e.g., reportArgumentType.txt -> ArgumentType)
  task_id="$(basename "${task_file%.txt}" | sed 's/^report//')"
  
  # Define paths
  workspace=".jj-workspaces/ws-${task_id}-${ts}"
  bookmark="task/${task_id}-${ts}"
  log_file="${out_dir}/tasks/${task_id}.log"
  summary_file="${out_dir}/tasks/${task_id}.summary.md"
  diff_file="${out_dir}/tasks/${task_id}.diff.patch"
  pr_meta_file="${out_dir}/tasks/${task_id}.pr.json"
  state_file="${out_dir}/tasks/${task_id}.state"
  
  log "starting task: $task_id (file: $task_file)"
  
  # Ensure the task output directory exists before starting the worker
  mkdir -p "$(dirname "$log_file")" "$(dirname "$state_file")"
  
  # Start worker in background
  process_task "$task_file" "$task_id" "$workspace" "$bookmark" \
               "$log_file" "$summary_file" "$diff_file" "$pr_meta_file" "$state_file" &
  
  worker_pids+=($!)
  running=$((running + 1))
  
  # Concurrency control
  if (( running >= max )); then
    log "reached max concurrency ($max), waiting for worker to complete"
    wait -n
    running=$((running - 1))
  fi
done

# Wait for remaining workers
log "waiting for remaining $running workers to complete"
wait

log "all workers completed"

# -------- generate merged report --------
log "generating merged report"

merged_report="${out_dir}/merged_report.md"
{
  echo "# Pyright Fix Run $ts"
  echo ""
  echo "- Base: $BASE_BOOKMARK"
  echo "- Concurrency: $MAX_CONCURRENCY"
  echo "- Mode: Three-phase with AI Agent"
  echo "- Dry run: $DRY_RUN"
  echo "- Tasks processed: ${#TASK_FILES[@]}"
  echo ""
  echo "## Tasks"
  
  for task_file in "${TASK_FILES[@]}"; do
    task_id="$(basename "${task_file%.txt}" | sed 's/^report//')"
    summary_file="${out_dir}/tasks/${task_id}.summary.md"
    diff_file="${out_dir}/tasks/${task_id}.diff.patch"
    pr_meta_file="${out_dir}/tasks/${task_id}.pr.json"
    
    echo ""
    echo "### $task_id"
    
    if [[ -f "$summary_file" ]]; then
      cat "$summary_file"
    else
      echo "- Result: summary not available"
      echo "- Status: likely failed during processing"
    fi
    
    if [[ -f "$diff_file" && -s "$diff_file" ]]; then
      echo ""
      echo "<details><summary>Diff</summary>"
      echo ""
      echo '```patch'
      # Limit diff size to first 400 lines
      sed -n '1,400p' "$diff_file"
      echo '```'
      echo "</details>"
    fi
    
    if [[ -f "$pr_meta_file" ]]; then
      pr_url=$(jq -r '.url // empty' "$pr_meta_file" 2>/dev/null || echo "")
      if [[ -n "$pr_url" ]]; then
        echo ""
        echo "PR: $pr_url"
      fi
    fi
  done
  
  echo ""
  echo "## Summary Statistics"
  echo ""
  
  completed=0
  with_changes=0
  with_prs=0
  
  for task_file in "${TASK_FILES[@]}"; do
    task_id="$(basename "${task_file%.txt}" | sed 's/^report//')"
    summary_file="${out_dir}/tasks/${task_id}.summary.md"
    diff_file="${out_dir}/tasks/${task_id}.diff.patch"
    pr_meta_file="${out_dir}/tasks/${task_id}.pr.json"
    
    if [[ -f "$summary_file" ]]; then
      completed=$((completed + 1))
    fi
    
    if [[ -f "$diff_file" && -s "$diff_file" ]]; then
      with_changes=$((with_changes + 1))
    fi
    
    if [[ -f "$pr_meta_file" ]]; then
      with_prs=$((with_prs + 1))
    fi
  done
  
  echo "- Total tasks: ${#TASK_FILES[@]}"
  echo "- Completed: $completed"
  echo "- With changes: $with_changes"
  echo "- With PRs: $with_prs"
  echo ""
  echo "Generated at: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  
} > "$merged_report"

log "merged report written to: $merged_report"

# -------- final cleanup --------
log "performing final cleanup"

# Remove any remaining workspace directories
if [[ -d ".jj-workspaces" ]]; then
  for ws in .jj-workspaces/ws-*-"$ts"; do
    if [[ -d "$ws" ]]; then
      ws_name="$(basename "$ws")"
      jj workspace forget "$ws_name" 2>/dev/null || true
      rm -rf "$ws" 2>/dev/null || true
    fi
  done
fi

log "orchestration run completed successfully"
log "results available in: $out_dir"

