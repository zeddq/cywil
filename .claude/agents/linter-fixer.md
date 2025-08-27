---
name: linter-fixer
description: When an orchestrator agent want to create it
model: sonnet
color: blue
---

# Worker Spec — Three-Phase Pyright Fix Process (Updated)

## Overview

**Title**  
Three-Phase Pyright Fix Worker System

**Purpose**  
Process one pyright rule report through a three-phase approach: setup → AI agent fixes → validation/commit. Ensure isolation, safety, and proper git workflow management.

## Architecture

The worker process is now split into **three distinct phases**:

1. **Phase 1: Pre-fix Setup** (`pyright_worker_prefix.sh`)
2. **Phase 2: AI Agent Fixes** (External AI agent tool)
3. **Phase 3: Post-fix Validation** (`pyright_worker_postfix.sh`)

## Phase 1: Pre-fix Setup

**Script**: `scripts/pyright_worker_prefix.sh`

**Purpose**  
Prepare the workspace, sync repository, validate inputs, and create the initial jj change.

**Inputs**
- `--workspace <path>`: Pre-created jj workspace by orchestrator
- `--base <bookmark>`: Base bookmark (default: `main`)
- `--bookmark <name>`: Target bookmark name (e.g., `task/ArgumentType-<timestamp>`)
- `--allowlist-file <path>`: File containing paths allowed for modification
- `--log <path>`: Log file path
- `--state-file <path>`: State file for inter-phase communication

**Preconditions**
- Workspace exists and is accessible
- Repo is colocated with Git (`jj git init --colocate`)
- Remote `origin` available
- Allowlist file exists and is readable

**Process**
1. Change to workspace directory
2. Sync repo: `jj git fetch`
3. Create new change on base: `jj new <base-bookmark>`
4. Validate allowlist file format and readability
5. Write state information for Phase 3
6. Create `WORKSPACE_READY` marker file

**Outputs**
- `WORKSPACE_READY` marker file
- State file with phase 1 metadata
- Prepared jj workspace ready for AI agent

**Exit Codes**
- `0`: Success, workspace ready
- `2`: Invalid arguments or setup failure

## Phase 2: AI Agent Fixes

**Tool**: External AI agent (e.g., Claude Code, custom fixer)

**Purpose**  
Apply focused pyright fixes only to files listed in the allowlist.

**Inputs**
- Workspace path (as working directory)
- Allowlist file (constraint for which files can be modified)
- Task type identifier (for context)
- Log file (for progress tracking)

**Requirements**
- **MUST** only modify files listed in allowlist
- **MUST** focused changes
- **MUST** avoid global reformatting or style changes
- **MUST** log actions to provided log file
- **MUST** work within the provided workspace directory
- **MUST** return appropriate exit codes

**Interface Example**
```bash
ai_agent_apply_fixes \
  --workspace "/path/to/.jj-workspaces/ws-ArgumentType-20250827T120000Z" \
  --allowlist-file "pyright_reports/reportArgumentType.txt" \
  --task-type "pyright-ArgumentType" \
  --log "/path/to/reports/20250827T120000Z/tasks/ArgumentType.log"
```

**Exit Codes**
- `0`: Fixes applied successfully
- Non-zero: Failure, no commit should occur

## Phase 3: Post-fix Validation

**Script**: `scripts/pyright_worker_postfix.sh`

**Purpose**  
Validate AI agent changes, run checks, commit if valid, push bookmark, and create PR.

**Inputs**
- `--workspace <path>`: Workspace path
- `--state-file <path>`: State file from Phase 1
- `--summary <path>`: Summary output file
- `--diff <path>`: Diff output file  
- `--log <path>`: Log file path
- `--pr-meta <path>`: PR metadata output file

**Preconditions**
- `WORKSPACE_READY` marker exists (validates Phase 1 completion)
- State file available with Phase 1 metadata
- AI agent has completed (Phase 2)

**Process**
1. Validate `WORKSPACE_READY` marker exists
2. Load state from Phase 1 (bookmark, allowlist, etc.)
3. Check for changes: `jj diff --quiet`
4. **Validate allowlist compliance**: Ensure all changed files are in allowlist
5. Refresh pyright reports: `scripts/pyright_report_by_rule.py`
6. Run tests (optional and non-blocking on fail): `tools/run_tests_periodic.py`
7. Commit changes with descriptive message
8. Generate artifacts (diff, summary)
9. Push bookmark: `jj git push --bookmark <bookmark> --allow-new`
10. Create GitHub PR using `gh pr create`
11. Clean up marker files

**Validation Rules**
- **Allowlist enforcement**: All changed files MUST be in allowlist
- **Non-empty changes**: Skip if no changes detected
- **Test stability**: Tests should not regress (non-fatal)

**Outputs**
- Summary markdown file
- Unified diff patch file
- PR metadata JSON file
- Pushed git branch/bookmark

**Exit Codes**
- `0`: Success, changes committed and pushed
- `3`: Allowlist violation, changes rejected
- Other: General failure

## Integration Flow

**Orchestrator sequence per task**:
```bash
# Phase 1: Setup
if scripts/pyright_worker_prefix.sh \
  --workspace "${ws}" \
  --base "${BASE_BOOKMARK:-main}" \
  --bookmark "${BOOKMARK}" \
  --allowlist-file "${TASK_FILE}" \
  --log "${LOG}" \
  --state-file "${STATE_FILE}"; then
  
  # Phase 2: AI Agent
  if ai_agent_apply_fixes \
    --workspace "${ws}" \
    --allowlist-file "${TASK_FILE}" \
    --task-type "pyright-${TASK_ID}" \
    --log "${LOG}"; then
    
    # Phase 3: Validation & Commit
    scripts/pyright_worker_postfix.sh \
      --workspace "${ws}" \
      --state-file "${STATE_FILE}" \
      --summary "${SUMMARY}" \
      --diff "${DIFF}" \
      --log "${LOG}" \
      --pr-meta "${PR_META}"
  fi
fi
```

## Safety Mechanisms

**Isolation**
- Each phase operates only within its designated workspace
- Allowlist validation prevents cross-task contamination
- State files ensure clean hand-offs between phases

**Validation**
- Pre-fix: Validate inputs and setup
- Post-fix: Enforce allowlist compliance
- Marker files prevent out-of-order execution

**Failure Handling**
- Each phase can fail independently
- Failed workspaces are cleaned up by orchestrator
- Logs capture full execution trace for debugging

**Git Safety**
- No force-pushes
- Only push new bookmarks/branches
- Changes validated before commit

## State Management

**State File Format** (Phase 1 → Phase 3):
```bash
WORKSPACE=/path/to/workspace
BASE_BOOKMARK=main
BOOKMARK=task/ArgumentType-20250827T120000Z
ALLOWLIST_FILE=pyright_reports/reportArgumentType.txt
PREFIX_TIMESTAMP=20250827T120000Z
```

**Marker Files**:
- `WORKSPACE_READY`: Indicates Phase 1 completion
- Removed after Phase 3 completion

## Error Recovery

**Phase 1 Failure**:
- Workspace creation issues → Skip task
- Allowlist problems → Skip task
- Repository sync issues → Retry or skip

**Phase 2 Failure**:
- AI agent errors → Skip to cleanup
- Allowlist violations → Detected in Phase 3

**Phase 3 Failure**:
- Allowlist violations → Abort, log, cleanup
- Push failures → Log, continue (manual intervention may be needed)
- PR creation failures → Continue (non-fatal)

This three-phase approach provides clear separation of concerns, robust error handling, and ensures the AI agent operates within well-defined constraints while maintaining git workflow integrity.
