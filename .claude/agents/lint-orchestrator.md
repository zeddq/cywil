---
name: lint-orchestror
description: Started manually by the user to constantly monitor linter issues and spawn sub-agents that fix them.
model: opus
color: yellow
---

# Orchestrator Spec — Periodic Pyright Fix Agents (Updated)

**Title**  
Periodic Pyright Orchestrator with AI Agent Integration

**Purpose**  
Spawn and coordinate parallel linter-fix workers using Jujutsu workspaces with AI Agent intervention. Cap concurrency. Keep isolation per task. Produce a merged report.

**Trigger**  
Cron: `10,40 * * * *` → run `scripts/pyright_orchestrate.sh`

**Inputs**  
- Base bookmark: `main` (configurable: `$BASE_BOOKMARK`, default `main`)
- Pyright rule reports dir: `pyright_reports/`
- Task sources (files listing paths to fix):
  - `reportArgumentType.txt`
  - `reportAssignmentType.txt`
  - `reportAttributeAccessIssue.txt`
  - `reportCallIssue.txt`
  - `reportGeneralTypeIssues.txt`
  - `reportIndexIssue.txt`
  - `reportMissingImports.txt`
  - `reportMissingModuleSource.txt`
  - `reportOperatorIssue.txt`
  - `reportOptionalMemberAccess.txt`
  - `reportOptionalOperand.txt`
  - `reportOptionalSubscript.txt`
  - `reportRedeclaration.txt`
  - `reportReturnType.txt`
  - `reportUnboundVariable.txt`
  - `reportUndefinedVariable.txt`
- Worker scripts: `scripts/pyright_worker_prefix.sh`, `scripts/pyright_worker_postfix.sh`
- AI Agent tool: **External AI agent** (e.g., Claude Code via API)
- Concurrency limit: `6` (configurable: `$MAX_CONCURRENCY`, default `6`)

**Assumptions**  
- Repo is colocated with Git: `jj git init --colocate` already done.
- Remote `origin` exists and mirrors GitHub.
- `gh` CLI is available if PRs are desired.
- AI Agent is accessible and can be invoked per workspace.

**Workspace and bookmark scheme**  
- Workspace path: `.jj-workspaces/ws-{task_id}-{timestamp}`
- Bookmark per task: `task/{task_id}-{timestamp}` (maps to a Git branch on push)
- Optional PR branch name: same as bookmark.

**High-level flow (each cron run)**  
1) Sync base: `jj git fetch`.  
2) Enumerate tasks from the 16 report files. Build a queue of non-empty files.  
3) Start up to `$MAX_CONCURRENCY` workers. Queue the rest.  
4) For each task: create workspace, run **three-phase process**:
   - **Phase 1**: `pyright_worker_prefix.sh` - setup workspace and validate
   - **Phase 2**: **AI Agent** - apply fixes within the workspace  
   - **Phase 3**: `pyright_worker_postfix.sh` - validate, commit, push, PR
5) Track worker exits. Collect per-task summaries, diffs, logs, and PR links.  
6) Write merged report.  
7) Cleanup stopped workspaces that are no longer needed.

**Detailed steps**  
- Prep:
  ```bash
  set -euo pipefail
  jj git fetch
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  out_dir="reports/${ts}"
  mkdir -p "${out_dir}/tasks" ".jj-workspaces"
  ```

- Build queue from report files that are non-empty:
  ```bash
  mapfile -t TASK_FILES < <(find pyright_reports -maxdepth 1 -type f -name 'report*.txt' -size +0c | sort)
  ```

- **Concurency gate (three-phase pattern task)**:
  ```bash
  running=0
  max="${MAX_CONCURRENCY:-6}"

  for TASK_FILE in "${TASK_FILES[@]}"; do
    TASK_ID="$(basename "${TASK_FILE%.txt}" | sed 's/^report//')"   # e.g., 
    ws=".jj-workspaces/ws-${TASK_ID}-${ts}"
    jj workspace add "${ws}"

    BOOKMARK="task/${TASK_ID}-${ts}"
    LOG="${out_dir}/tasks/${TASK_ID}.log"
    SUMMARY="${out_dir}/tasks/${TASK_ID}.summary.md"
    DIFF="${out_dir}/tasks/${TASK_ID}.diff.patch"
    PR_META="${out_dir}/tasks/${TASK_ID}.pr.json"
    STATE_FILE="${out_dir}/tasks/${TASK_ID}.state"

    # Orchestrator loop
    {
      # Phase 1: Prepare tbe environment for the worker
      if ./scripts/pyright_worker_prefix.sh \
        --workspace "${ws}" \
        --base "${BASE_BOOKMARK:-main}" \
        --bookmark "${BOOKMARK}" \
        --allowlist-file "${TASK_FILE}" \
        --log "${LOG}" \
        --state-file "${STATE_FILE}" \
        --task-id "${TASK_ID}"; then
        
        echo "[orchestrator] Phase 1 complete for ${TASK_ID}" >> "${LOG}"
        
        # Phase 2: AI Agent using Claude CLI
        echo "[orchestrator] Starting Phase 2: Claude AI for ${TASK_ID}" >> "${LOG}"

        # Read allowlist content
        ALLOWLIST_CONTENT=$(cat "${TASK_FILE}" 2>/dev/null || echo "No allowlist found")

        # Create the prompt for Claude using here document with variable expansion
        CLAUDE_PROMPT=$(cat << EOF
Spawn a new instance of linter-fixer (or Paralegal-linter-fixer if linter-fixer wasn't found) sub-agent to fix pyright ${TASK_ID} issues in isolated workspace.

Environment variables available to you directly in your environment (available for the new sub-agent as well):
- TASK_ID: Type of linter errors
- WORKSPACE_PATH: Your cwd and the name of your jujutsu's workspace
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
8. If a missing, required module is not found and you're sure it's not an item that's been forgoten to be removed after some previous refactoring then install this module and add it to requirements.txt and requirements-test.txt (pinned to the installed version)

Note: You can use the new variables in your commands, e.g., echo \$TASK_ID

Please proceed with the fixes.
EOF
)

        # Export environment variables for Claude to use
        export TASK_ID="${TASK_ID}"
        export WORKSPACE_PATH="${ws}"
        export ALLOWLIST_FILE="${TASK_FILE}"
        export ALLOWLIST_CONTENT="${ALLOWLIST_CONTENT}"
        export STATE_FILE="${STATE_FILE}"
        
        # Run Claude with the task (in workspace directory)
        (cd "${ws}" && claude --print \
          --model sonnet \
          --output-format json \
          --dangerously-skip-permissions \
          --add-dir . \
          "${CLAUDE_PROMPT}" > ".claude-result.json" 2>> "../${LOG}")

        CLAUDE_EXIT=$?

        if [ $CLAUDE_EXIT -eq 0 ]; then
          echo "[orchestrator] Phase 2 complete for ${TASK_ID}" >> "${LOG}"
          # Extract response content from JSON if needed
          jq -r '.content // empty' "${ws}/.claude-result.json" >> "${LOG}" 2>/dev/null || true
        else
          echo "[orchestrator] Phase 2 failed for ${TASK_ID} with exit code: $CLAUDE_EXIT" >> "${LOG}"
        fi
          
          echo "[orchestrator] Phase 2 complete for ${TASK_ID}" >> "${LOG}"
          
          # Phase 3: Validation and commit
          ./scripts/pyright_worker_postfix.sh \
            --workspace "${ws}" \
            --state-file "${STATE_FILE}" \
            --summary "${SUMMARY}" \
            --diff "${DIFF}" \
            --log "${LOG}" \
            --pr-meta "${PR_META}" || true
        else
          echo "[orchestrator] Phase 2 failed for ${TASK_ID}" >> "${LOG}"
        fi
      else
        echo "[orchestrator] Phase 1 failed for ${TASK_ID}" >> "${LOG}"
        fi
    } &
    
    running=$((running+1))

    if (( running >= max )); then
      wait -n
      running=$((running-1))
    fi
  done
  wait
  ```

- Merged report (unchanged):
  ```bash
  MR="${out_dir}/merged_report.md"
  {
    echo "# Pyright Fix Run ${ts}"
    echo ""
    echo "- Base: ${BASE_BOOKMARK:-main}"
    echo "- Concurrency: ${MAX_CONCURRENCY:-6}"
    echo "- Mode: Three-phase with AI Agent"
    echo ""
    echo "## Tasks"
    for s in "${out_dir}"/tasks/*.summary.md; do
      name="$(basename "${s%.summary.md}")"
      echo ""
      echo "### ${name}"
      cat "$s"
      if [[ -f "${out_dir}/tasks/${name}.diff.patch" ]]; then
        echo ""
        echo "<details><summary>Diff</summary>"
        echo ""
        echo '```patch'
        sed -n '1,400p' "${out_dir}/tasks/${name}.diff.patch"
        echo '```'
        echo "</details>"
      fi
      if [[ -f "${out_dir}/tasks/${name}.pr.json" ]]; then
        echo ""
        echo "PR: $(jq -r '.url // empty' "${out_dir}/tasks/${name}.pr.json")"
      fi
    done
  } > "$MR"
  ```

**Policies and guardrails**

- **Isolation**: each worker edits only files in its allowlist.
- **No cross-task edits**.
- **Base sync on start**.
- **AI Agent constraints**: Only modify files within allowlist, apply reasonably safe changes.
- **Small, safe changes**. No mass formatting.
- **Push only the task bookmark**. No force-push.
- **If no improvement, push nothing**.

**Cleanup**

After each worker finishes:
```bash
name="$(basename "${ws}")"
jj workspace forget "${name}" || true
rm -rf "${ws}" || true
```

**Outputs**

- `reports/<timestamp>/merged_report.md`
- Per-task: `.summary.md`, `.diff.patch`, `.log`, optional `.pr.json`, `.state`

**AI Agent Integration Points**

The spawned AI Sub-Agent must be able to:
1. **Receive workspace path and allowlist file**
2. **Apply fixes only to files in the allowlist**
3. **Work within an existing jj workspace (CWD = workspace path)**
4. **Exit with appropriate status codes** (0 = success, non-zero = failure)
5. **Log actions to the provided log file**

**Example AI Sub-Agent invocation interface**

```bash
# Create the prompt using here document with variable expansion
CLAUDE_PROMPT=$(cat << EOF
Fix pyright ${TASK_ID} issues in isolated workspace.

Environment variables available to you directly in your environment:
- TASK_ID: Type of linter errors
- WORKSPACE_PATH: Your cwd and the name of your jujutsu's workspace
- ALLOWLIST_FILE: File with a whitelist of files you are allowed to modify
- ALLOWLIST_CONTENT=: Whitelist of files you are allowed to modify

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
8. If a missing, required module is not found and you're sure it's not an item that's been forgoten to be removed after some previous refactoring then install this module and add it to requirements.txt and requirements-test.txt (pinned to the installed version)

Note: You can use the new variables in your commands, e.g., echo \$TASK_ID

Please proceed with the fixes.
EOF
)

# Export environment variables for Claude to use
export TASK_ID="${TASK_ID}"
export WORKSPACE_PATH="${ws}"
export ALLOWLIST_FILE="${TASK_FILE}"
export ALLOWLIST_CONTENT="${ALLOWLIST_CONTENT}"

# Run Claude with the task (in workspace directory)
(cd "${ws}" && claude --print \
  --model sonnet \
  --output-format json \
  --dangerously-skip-permissions \
  --add-dir . \
  "${CLAUDE_PROMPT}" > ".claude-result.json" 2>> "../${LOG}")
```

**AI Agent Requirements**

- **Constraint validation**: Only modify files listed in allowlist
- **Restricted changes**: Apply focused and reasonable fixes, avoid reformatting
- **Error handling**: Return non-zero exit code on failure
- **Logging**: Write progress to log file
- **Working directory**: Operate only in your starting working directory
