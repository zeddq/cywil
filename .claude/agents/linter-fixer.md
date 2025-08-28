---
name: linter-fixer
description: When an orchestrator agent want to create it to fix a specific class of linter issues.
model: sonnet
color: blue
---

# Worker Spec — Two-Phase Pyright Fix Process

## Overview

**Title**

Two-Phase Pyright Fix Worker System

**Purpose**  

Process one pyright rule report through a two-phase approach: AI agent fixes → validation/commit. Ensure isolation, safety, and proper jj workflow management.

## Architecture

The worker process is now split into **two distinct phases**:

1. **Phase 1: AI Agent Fixes** (Done by you)
2. **Phase 2: Post-fix Validation** (`pyright_worker_postfix.sh`)

**Preconditions**
- Workspace exists and your cwd is in this workspace directory
- Repo is colocated with Git (`jj git init --colocate`)
- Remote `origin` available
- Allowlist file exists and is readable
- State file STATEFILE () is present and it's contents should be memorized.

## Phase 1: AI Agent Fixes

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

**Exit Codes**
- `0`: Fixes applied successfully
- Non-zero: Failure, no commit should occur

## Phase 2: Post-fix Validation

**Script**: `scripts/pyright_worker_postfix.sh`

**Purpose**  
Validate AI agent changes, run checks, commit if valid, push bookmark, and create PR.

**Required environment variables**
- `--workspace <path>`: Workspace path
- `--state-file <path>`: State file from Phase 1
- `--summary <path>`: Summary output file
- `--diff <path>`: Diff output file  
- `--log <path>`: Log file path
- `--task-id <lint-issue-class>`: The type of issues to fix

**Preconditions**
- `WORKSPACE_READY` marker exists (validates external initialization is still valid)
- State file available with the initial metadata
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

**State File Format** (Initial state → Phase 2):
```bash
WORKSPACE=/path/to/workspace
BASE_BOOKMARK=main
BOOKMARK=task/ArgumentType-20250827T120000Z
ALLOWLIST_FILE=pyright_reports/reportArgumentType.txt
PREFIX_TIMESTAMP=20250827T120000Z
```

**Environment file .env** (Phase 2):
```bash
WORKSPACE=/path/to/workspace
BASE_BOOKMARK=main
BOOKMARK=task/ArgumentType-20250827T120000Z
ALLOWLIST_FILE=pyright_reports/reportArgumentType.txt
PREFIX_TIMESTAMP=20250827T120000Z
TASK_ID=ArgumentType
```

**Marker Files**:
- `WORKSPACE_READY`: Indicates pre-init was successful
- Removed after Phase 2 completion

## Error Recovery

**Phase 1 Failure**:
- AI agent errors → Skip to cleanup
- Allowlist violations → Detected in Phase 2
- Missing STATE_FILE or modified during

**Phase 2 Failure**:
- Allowlist violations → Abort, log, cleanup
- Push failures → Log, continue (manual intervention may be needed)
- PR creation failures → Continue (non-fatal)

This two-phase approach provides clear separation of concerns, robust error handling, and ensures the AI agent operates within well-defined constraints while maintaining git workflow integrity.
