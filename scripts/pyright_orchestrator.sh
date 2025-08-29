#!/usr/bin/env bash
# Periodic Pyright Orchestrator with AI Agent Integration
# Spawns and coordinates parallel linter-fix workers using Jujutsu workspaces
# Implements the full orchestrator specification with proper AI agent integration

set -euo pipefail
umask 0022

# Configuration with defaults
: "${BASE_BOOKMARK:=main}"
: "${MAX_CONCURRENCY:=6}"
: "${PYRIGHT_REPORTS_DIR:=pyright_reports}"

# Expected task source files (16 as per specification)
EXPECTED_TASK_FILES=(
    "reportArgumentType.txt"
    "reportAssignmentType.txt"
    "reportAttributeAccessIssue.txt"
    "reportCallIssue.txt"
    "reportGeneralTypeIssues.txt"
    "reportIndexIssue.txt"
    "reportMissingImports.txt"
    "reportMissingModuleSource.txt"
    "reportOperatorIssue.txt"
    "reportOptionalMemberAccess.txt"
    "reportOptionalOperand.txt"
    "reportOptionalSubscript.txt"
    "reportRedeclaration.txt"
    "reportReturnType.txt"
    "reportUnboundVariable.txt"
    "reportUndefinedVariable.txt"
)

usage() {
    cat <<'EOF'
Periodic Pyright Orchestrator with AI Agent Integration

Usage:
  pyright_orchestrator.sh [OPTIONS]

Options:
  --base-bookmark NAME    Base bookmark for all tasks (default: main)
  --max-concurrency N     Maximum parallel workers (default: 6)
  --reports-dir DIR       Pyright reports directory (default: pyright_reports)
  --dry-run              Show what would be done without executing
  --help                 Show this help

Environment Variables:
  BASE_BOOKMARK          Base bookmark name (default: main)
  MAX_CONCURRENCY        Maximum concurrent workers (default: 6)

The orchestrator will:
1. Sync base repository
2. Build task queue from non-empty report files
3. Spawn up to MAX_CONCURRENCY workers
4. Each worker runs 3 phases:
   - Phase 1: Setup workspace (pyright_worker_prefix.sh)
   - Phase 2: AI Agent fixes
   - Phase 3: Validate, commit, push, PR (pyright_worker_postfix.sh)
5. Generate merged report
6. Cleanup workspaces

EOF
}

# Parse command line arguments
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --base-bookmark)  BASE_BOOKMARK="$2"; shift 2 ;;
        --max-concurrency) MAX_CONCURRENCY="$2"; shift 2 ;;
        --reports-dir)    PYRIGHT_REPORTS_DIR="$2"; shift 2 ;;
        --dry-run)        DRY_RUN=true; shift ;;
        --help|-h)        usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

# Validation
if ! command -v jj >/dev/null; then
    echo "ERROR: jj command not found" >&2
    exit 1
fi

if ! command -v jq >/dev/null; then
    echo "ERROR: jq command not found" >&2
    exit 1
fi

if ! command -v claude >/dev/null; then
    echo "ERROR: claude CLI not found" >&2
    exit 1
fi

if [[ ! -d "$PYRIGHT_REPORTS_DIR" ]]; then
    echo "ERROR: Reports directory not found: $PYRIGHT_REPORTS_DIR" >&2
    exit 1
fi

# Setup output directories
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="reports/${TIMESTAMP}"
TASKS_DIR="${OUT_DIR}/tasks"
WORKSPACES_DIR=".jj-workspaces"

echo "=== Pyright Orchestrator Starting ==="
echo "Timestamp: $TIMESTAMP"
echo "Base bookmark: $BASE_BOOKMARK"
echo "Max concurrency: $MAX_CONCURRENCY"
echo "Reports directory: $PYRIGHT_REPORTS_DIR"
echo "Output directory: $OUT_DIR"

if $DRY_RUN; then
    echo "=== DRY RUN MODE - No actual changes will be made ==="
fi

# Create directories
mkdir -p "$TASKS_DIR" "$WORKSPACES_DIR"

# Step 1: Sync base repository
echo "=== Step 1: Syncing base repository ==="
if ! $DRY_RUN; then
    jj git fetch
    echo "Repository synced with remote"
else
    echo "Would sync repository: jj git fetch"
fi

# Step 2: Build task queue from non-empty report files
echo "=== Step 2: Building task queue ==="
declare -a TASK_QUEUE=()

for report_file in "${EXPECTED_TASK_FILES[@]}"; do
    full_path="${PYRIGHT_REPORTS_DIR}/${report_file}"
    if [[ -f "$full_path" && -s "$full_path" ]]; then
        TASK_QUEUE+=("$full_path")
        echo "Added to queue: $report_file ($(wc -l < "$full_path") lines)"
    else
        echo "Skipped (empty or missing): $report_file"
    fi
done

echo "Task queue built: ${#TASK_QUEUE[@]} tasks"

if [[ ${#TASK_QUEUE[@]} -eq 0 ]]; then
    echo "No tasks to process. Exiting."
    exit 0
fi

if $DRY_RUN; then
    echo "=== DRY RUN: Would process these tasks ==="
    for task in "${TASK_QUEUE[@]}"; do
        echo "  - $(basename "$task")"
    done
    exit 0
fi

# Step 3: Worker management with concurrency control
echo "=== Step 3: Starting worker management ==="

# Track running jobs and cleanup function
declare -a RUNNING_PIDS=()
declare -a WORKSPACE_PATHS=()

cleanup_workspaces() {
    echo "=== Cleanup: Removing workspaces ==="
    for ws in "${WORKSPACE_PATHS[@]}"; do
        if [[ -d "$ws" ]]; then
            name="$(basename "$ws")"
            echo "Cleaning up workspace: $name"
            jj workspace forget "$name" 2>/dev/null || true
            rm -rf "$ws" || true
        fi
    done
}

# Ensure cleanup on exit
trap 'wait; cleanup_workspaces' EXIT

# Worker function - runs three phases for each task
spawn_worker() {
    local task_file="$1"
    local task_basename task_id workspace bookmark
    
    task_basename="$(basename "$task_file")"
    task_id="$(basename "${task_basename%.txt}" | sed 's/^report//')"
    workspace="${WORKSPACES_DIR}/ws-${task_id}-${TIMESTAMP}"
    bookmark="task/${task_id}-${TIMESTAMP}"
    
    # Output files
    local log="${TASKS_DIR}/${task_id}.log"
    local summary="${TASKS_DIR}/${task_id}.summary.md"
    local diff="${TASKS_DIR}/${task_id}.diff.patch"
    local pr_meta="${TASKS_DIR}/${task_id}.pr.json"
    local state_file="${TASKS_DIR}/${task_id}.state"
    
    echo "Starting worker for task: $task_id (PID: $$)"
    WORKSPACE_PATHS+=("$workspace")
    
    # Create workspace
    jj workspace add "$workspace"
    
    # Run worker in background
    (
        set +e  # Disable errexit for worker subshell
        
        echo "[worker-$task_id] Starting three-phase process" > "$log"
        
        # PHASE 1: Setup workspace and validate
        echo "[worker-$task_id] Phase 1: Workspace setup" >> "$log"
        if (cd "$workspace" && 
            "${PWD}/scripts/pyright_worker_prefix.sh" \
                --workspace "$workspace" \
                --base "$BASE_BOOKMARK" \
                --bookmark "$bookmark" \
                --allowlist-file "${PWD}/${task_file}" \
                --log "${PWD}/${log}" \
                --state-file "${PWD}/${state_file}"); then
            
            echo "[worker-$task_id] Phase 1 completed successfully" >> "$log"
            
            # PHASE 2: AI Agent fixes using Task tool integration
            echo "[worker-$task_id] Phase 2: AI Agent fixes" >> "$log"
            
            # Use the specialized agent spawning script
            if "${PWD}/scripts/spawn_linter_agent.sh" \
                --task-id "$task_id" \
                --workspace "$workspace" \
                --allowlist "${PWD}/${task_file}" \
                --log "${PWD}/${log}" \
                --output "$workspace/.claude-result.json" \
                --model sonnet; then
                
                echo "[worker-$task_id] Phase 2 completed successfully" >> "$log"
                
                # Log AI agent output
                if [[ -f "$workspace/.claude-result.json" ]]; then
                    echo "[worker-$task_id] AI Agent output:" >> "$log"
                    jq -r '.content // empty' "$workspace/.claude-result.json" >> "$log" 2>/dev/null || true
                fi
            else
                echo "[worker-$task_id] Phase 2 failed - AI agent error" >> "$log"
            fi
            
            # PHASE 3: Validate, commit, push, PR
            echo "[worker-$task_id] Phase 3: Validation and publishing" >> "$log"
            "${PWD}/scripts/pyright_worker_postfix.sh" \
                --workspace "$workspace" \
                --state-file "$state_file" \
                --summary "$summary" \
                --diff "$diff" \
                --log "$log" \
                --pr-meta "$pr_meta" || true
            
            echo "[worker-$task_id] Phase 3 completed" >> "$log"
            
        else
            echo "[worker-$task_id] Phase 1 failed - workspace setup error" >> "$log"
        fi
        
        echo "[worker-$task_id] Worker completed" >> "$log"
        
    ) &
    
    local worker_pid=$!
    RUNNING_PIDS+=("$worker_pid")
    echo "Worker spawned for $task_id (PID: $worker_pid)"
    
    return 0
}

# Process task queue with concurrency control
running_count=0

for task_file in "${TASK_QUEUE[@]}"; do
    # Wait if we've reached max concurrency
    while (( running_count >= MAX_CONCURRENCY )); do
        echo "Max concurrency ($MAX_CONCURRENCY) reached. Waiting for worker to complete..."
        wait -n  # Wait for any background job to complete
        running_count=$((running_count - 1))
    done
    
    # Spawn new worker
    spawn_worker "$task_file"
    running_count=$((running_count + 1))
done

# Wait for all remaining workers to complete
echo "=== Waiting for all workers to complete ==="
wait

echo "=== Step 4: All workers completed ==="

# Step 5: Generate merged report
echo "=== Step 5: Generating merged report ==="

MERGED_REPORT="${OUT_DIR}/merged_report.md"

{
    echo "# Pyright Orchestrator Run Report"
    echo ""
    echo "**Timestamp:** $TIMESTAMP"
    echo "**Base Bookmark:** $BASE_BOOKMARK"
    echo "**Max Concurrency:** $MAX_CONCURRENCY"
    echo "**Tasks Processed:** ${#TASK_QUEUE[@]}"
    echo ""
    echo "## Task Summary"
    echo ""
    
    for task_file in "${TASK_QUEUE[@]}"; do
        task_basename="$(basename "$task_file")"
        task_id="$(basename "${task_basename%.txt}" | sed 's/^report//')"
        
        echo "### $task_id"
        echo ""
        
        # Include individual task summary if it exists
        summary_file="${TASKS_DIR}/${task_id}.summary.md"
        if [[ -f "$summary_file" ]]; then
            cat "$summary_file"
        else
            echo "- Status: No summary generated (possible failure)"
        fi
        echo ""
        
        # Include PR information if available
        pr_file="${TASKS_DIR}/${task_id}.pr.json"
        if [[ -f "$pr_file" ]]; then
            pr_url="$(jq -r '.url // empty' "$pr_file" 2>/dev/null || true)"
            if [[ -n "$pr_url" ]]; then
                echo "- PR: [$pr_url]($pr_url)"
            fi
        fi
        echo ""
    done
    
    echo "## Artifacts"
    echo ""
    echo "All task artifacts are stored in: \`$OUT_DIR/tasks/\`"
    echo ""
    echo "- \`.log\` - Worker execution logs"
    echo "- \`.summary.md\` - Task summaries"
    echo "- \`.diff.patch\` - Change diffs"
    echo "- \`.pr.json\` - PR metadata"
    echo "- \`.state\` - Worker state information"
    echo ""
    echo "## Orchestrator Configuration"
    echo ""
    echo "- Base Bookmark: $BASE_BOOKMARK"
    echo "- Max Concurrency: $MAX_CONCURRENCY"
    echo "- Reports Directory: $PYRIGHT_REPORTS_DIR"
    echo "- Output Directory: $OUT_DIR"
    echo ""
    echo "---"
    echo "*Generated by Pyright Orchestrator at $(date -u +%Y-%m-%dT%H:%M:%SZ)*"
    
} > "$MERGED_REPORT"

echo "Merged report generated: $MERGED_REPORT"

# Step 6: Final summary
echo "=== Orchestrator Run Complete ==="
echo "Total tasks processed: ${#TASK_QUEUE[@]}"
echo "Output directory: $OUT_DIR"
echo "Merged report: $MERGED_REPORT"

# List any remaining workspace directories for manual cleanup if needed
remaining_workspaces=$(find "$WORKSPACES_DIR" -maxdepth 1 -type d -name "ws-*-$TIMESTAMP" 2>/dev/null | wc -l)
if (( remaining_workspaces > 0 )); then
    echo "Warning: $remaining_workspaces workspace directories may need manual cleanup"
fi

echo "Orchestrator completed successfully!"