#!/usr/bin/env bash
# AI Agent Integration Script for Pyright Orchestrator
# Spawns linter-fixer or paralegal-linter-fixer sub-agent using Claude Code Task tool

set -euo pipefail

usage() {
    cat <<'EOF'
AI Agent Integration Script

Usage:
  spawn_linter_agent.sh --task-id TASK_ID --workspace PATH --allowlist FILE [OPTIONS]

Required:
  --task-id TASK_ID       Type of pyright errors to fix
  --workspace PATH        Workspace directory path  
  --allowlist FILE        File containing allowlist of modifiable files

Options:
  --log FILE             Log file path
  --output FILE          Output file for agent results
  --model MODEL          Claude model to use (default: sonnet)
  --help                 Show this help

Environment:
  This script will export environment variables for the sub-agent:
  - TASK_ID, WORKSPACE_PATH, ALLOWLIST_FILE, ALLOWLIST_CONTENT
EOF
}

# Parse arguments
TASK_ID=""
WORKSPACE=""
ALLOWLIST_FILE=""
LOG=""
OUTPUT=""
MODEL="sonnet"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --task-id)      TASK_ID="$2"; shift 2 ;;
        --workspace)    WORKSPACE="$2"; shift 2 ;;
        --allowlist)    ALLOWLIST_FILE="$2"; shift 2 ;;
        --log)          LOG="$2"; shift 2 ;;
        --output)       OUTPUT="$2"; shift 2 ;;
        --model)        MODEL="$2"; shift 2 ;;
        --help|-h)      usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

# Validation
if [[ -z "$TASK_ID" || -z "$WORKSPACE" || -z "$ALLOWLIST_FILE" ]]; then
    echo "ERROR: Missing required arguments" >&2
    usage; exit 1
fi

if [[ ! -d "$WORKSPACE" ]]; then
    echo "ERROR: Workspace directory not found: $WORKSPACE" >&2
    exit 1
fi

if [[ ! -f "$ALLOWLIST_FILE" ]]; then
    echo "ERROR: Allowlist file not found: $ALLOWLIST_FILE" >&2
    exit 1
fi

# Read allowlist content
ALLOWLIST_CONTENT="$(cat "$ALLOWLIST_FILE" 2>/dev/null || echo "No allowlist found")"

# Setup logging
if [[ -n "$LOG" ]]; then
    exec 2>> "$LOG"
fi

echo "[agent-spawn] Starting AI agent for task: $TASK_ID" >&2
echo "[agent-spawn] Workspace: $WORKSPACE" >&2
echo "[agent-spawn] Allowlist: $ALLOWLIST_FILE ($(echo "$ALLOWLIST_CONTENT" | wc -l) files)" >&2

# Export environment variables for the sub-agent
export TASK_ID
export WORKSPACE_PATH="$WORKSPACE"  
export ALLOWLIST_FILE
export ALLOWLIST_CONTENT

# Change to workspace directory
cd "$WORKSPACE"

# Create the agent task prompt
AGENT_PROMPT="Spawn a linter-fixer sub-agent (or paralegal-linter-fixer if linter-fixer not found) to fix pyright ${TASK_ID} issues in this isolated workspace.

Environment variables available to the sub-agent:
- TASK_ID: ${TASK_ID}
- WORKSPACE_PATH: ${WORKSPACE_PATH}
- ALLOWLIST_FILE: ${ALLOWLIST_FILE}
- ALLOWLIST_CONTENT: (allowlisted files content)

Files allowed for modification:
${ALLOWLIST_CONTENT}

Task Instructions for Sub-Agent:
1. You are working in workspace: ${WORKSPACE}
2. ONLY modify files listed in the allowlist above  
3. Fix pyright type errors for the ${TASK_ID} category specifically
4. Make focused, reasonable changes that preserve existing functionality
5. Add type annotations where needed
6. Import necessary types and modules
7. If a required module is genuinely missing (not leftover code):
   - Add it with Poetry: \`poetry add <pkg>\` (or \`poetry add --group dev <pkg>\` for dev-only)
   - The lockfile will track exact versions; no requirements.txt changes needed

Guidelines for Sub-Agent:
- Make minimal, safe changes
- No mass formatting or style changes  
- Focus only on the specific ${TASK_ID} error category
- Preserve existing code structure and logic
- Validate that changes don't break functionality
- Use the Task tool to spawn the appropriate sub-agent type

Please spawn the linter-fixer sub-agent to proceed with the fixes."

echo "[agent-spawn] Spawning Claude Code Task..." >&2

# Run Claude Code with Task tool to spawn sub-agent
if claude --print \
    --model "$MODEL" \
    --output-format json \
    --dangerously-skip-permissions \
    --add-dir . \
    "$AGENT_PROMPT" \
    > "${OUTPUT:-.claude-result.json}" 2>&1; then
    
    echo "[agent-spawn] Sub-agent task completed successfully" >&2
    
    # Log the result if output file specified
    if [[ -n "$OUTPUT" && -f "$OUTPUT" ]]; then
        echo "[agent-spawn] Results written to: $OUTPUT" >&2
        if command -v jq >/dev/null; then
            jq -r '.content // empty' "$OUTPUT" 2>/dev/null | head -10 >&2 || true
        fi
    fi
    
    exit 0
else
    echo "[agent-spawn] ERROR: Sub-agent task failed" >&2
    exit 1
fi
