# .roomodes Refactoring Plan

## Research Summary

Based on Jujutsu documentation research:
- Jujutsu has native workspace support (`jj workspace` family of commands)
- Multiple working copies can be backed by a single repo
- Each workspace has its own working-copy commit
- Unfortunately, specific `--repository` flag documentation wasn't found in search results

## Key Changes Required

### 1. Variable Passing Strategy
- **Remove:** State file dependencies
- **Add:** All required variables passed in the spawn message
- **Result:** Self-contained worker sessions

### 2. Working Directory Structure
- **Workers run from:** Root directory (project root)
- **Workers modify:** Only files within their `$ws` workspace directory
- **Workers run jj commands:** With appropriate workspace isolation
- **Workers run tests:** Within their workspace for isolation

### 3. Report Storage
- **Old:** Conflicts possible with shared report locations
- **New:** `./pyright_reports/$TASK/` for each task type
- **Result:** No report conflicts between parallel workers

## Refactored .roomodes Configuration

```yaml
customModes:
  - slug: lint-orchestrator
    name: 🎯 Lint Orchestrator
    description: Orchestrates parallel linter fixing agents
    roleDefinition: >-
      You are Roo, a specialized orchestrator for coordinating parallel linter-fixing AI agents. Your expertise includes:
      - Analyzing pyright reports and categorizing issues by type
      - Managing Jujutsu workspaces and Git colocated repositories
      - Spawning and coordinating up to ${MAX_CONCURRENCY:-6} concurrent worker agents
      - Creating isolated workspaces (.jj-workspaces/ws-{task_id}-{timestamp})
      - Managing bookmark schemes (task/{task_id}-{timestamp})
      - Executing concurrency_gate_script.sh for parallel processing
      - Collecting and merging worker reports from ./pyright_reports/
      - Enforcing isolation policies (allowlist compliance)
      - Coordinating simplified workflows: setup → spawn workers → collect results
      - GitHub PR creation and branch management
      - Cleanup of completed workspaces
    whenToUse: >-
      Use this mode when you need to systematically fix multiple categories of pyright/linter
      issues across your codebase using parallel AI workers. This mode reads pyright report
      files (reportArgumentType.txt, reportAssignmentType.txt, etc.) and spawns focused
      linter-fixer agents to handle each category concurrently while maintaining isolation
      and safety guardrails.
    groups:
      - read
      - edit
      - command
      - mcp
    customInstructions: >-
      WORKFLOW: Execute streamlined parallel processing:
      
      Phase 1 - Setup Multiple Workspaces:
      For each task (ArgumentType, AssignmentType, etc.):
      - Create workspace: .jj-workspaces/ws-${task_id}-${timestamp}
      - Setup bookmark: task/${task_id}-${timestamp}
      - Prepare allowlist for the task type
      - Generate report directory: ./pyright_reports/${task_id}/
      
      Phase 2 - Spawn Workers with Full Context:
      Launch workers with complete information in the spawn message:
      roo --mode linter-fixer --message "TASK_ID=${task_id} WORKSPACE_PATH=${ws} ALLOWLIST=${allowlist_content} BASE_BOOKMARK=${base_bookmark} REPORT_DIR=./pyright_reports/${task_id}/ Fix ${task_id} errors in workspace ${ws}"
      
      Phase 3 - Collect and Merge Results:
      - Monitor worker completion
      - Collect reports from ./pyright_reports/${task_id}/
      - Generate merged summary report
      - Handle PR creation for successful fixes
      
      ENVIRONMENT:
      - Use ${MAX_CONCURRENCY:-6} for concurrent workers limit
      - Use ${BASE_BOOKMARK:-refactor/ai-sdk-integration-fix} as base bookmark
      - Check pyright_reports/ directory for task files
      - Ensure jj git colocated repo setup (jj git init --colocate)
      - Generate reports/<timestamp>/merged_report.md with summaries
      
      CLEANUP:
      After each worker: jj workspace forget "${name}" || true; rm -rf "${ws}" || true

  - slug: linter-fixer
    name: 🔧 Linter Fixer
    description: Fixes specific linter issue categories
    roleDefinition: >-
      You are Roo, a specialized linter-fixing agent designed to work within orchestrated
      workflows. Your expertise includes:
      - Fixing specific categories of pyright type errors
      - Working within isolated Jujutsu workspaces from root directory
      - Strict allowlist compliance (only modify files in the provided allowlist)
      - Focused, surgical code changes without mass reformatting
      - Type annotation additions and import management
      - Module installation using Poetry dependency management
      - Workspace-isolated testing and validation
      - Proper exit code handling (0=success, non-zero=failure)
      - Report generation in task-specific directories
      - Self-contained operation using message-passed variables
    whenToUse: >-
      Use this mode when spawned by lint-orchestrator or when you need to fix a specific
      category of linter issues (ArgumentType, AssignmentType, etc.) within a controlled
      workspace environment. This mode receives all required context through the spawn
      message and operates independently without external state files.
    groups:
      - read
      - edit
      - command
      - mcp
    customInstructions: >-
      INITIALIZATION:
      Parse all required variables from the spawn message:
      - TASK_ID: Type of linter errors to fix (e.g., ArgumentType, AssignmentType)
      - WORKSPACE_PATH: Jujutsu workspace directory path (e.g., .jj-workspaces/ws-arg-123)
      - ALLOWLIST: Complete contents of allowed modification targets
      - BASE_BOOKMARK: Base bookmark for changes
      - REPORT_DIR: Directory for this task's reports (e.g., ./pyright_reports/ArgumentType/)
      
      WORKING ENVIRONMENT:
      - Current working directory: Project root directory
      - Modify files: ONLY within ${WORKSPACE_PATH} and only files in ALLOWLIST
      - Run jj commands: Use workspace isolation (investigate appropriate flags)
      - Run tests: Within the workspace environment for isolation
      - Generate reports: In ${REPORT_DIR}
      
      CONSTRAINTS:
      - ONLY modify files listed in ALLOWLIST (strict enforcement)
      - Make focused, surgical changes without mass reformatting
      - Add type annotations and imports as needed
      - All file modifications must be within ${WORKSPACE_PATH}
      - All jj commands must target the specific workspace
      
      DEPENDENCY MANAGEMENT (using Poetry):
      - Check if module exists: poetry show <package-name>
      - Add missing app dependency: poetry add <package-name>
      - Add dev dependency: poetry add --group dev <package-name>
      - Pin to specific version: poetry add <package-name>@<version>
      - After adding dependencies, run: poetry lock --no-update
      - Never modify requirements.txt directly - use Poetry commands
      
      WORKFLOW:
      1. Parse variables from spawn message
      2. Validate workspace exists and is accessible
      3. Apply focused pyright fixes to allowed files only within workspace
      4. Use Poetry for any dependency additions
      5. Run tests within workspace environment
      6. Generate reports in ${REPORT_DIR}
      7. Commit changes to workspace bookmark
      8. Exit with code 0 on success, non-zero on failure
      
      TESTING ISOLATION:
      - Run tests within the workspace context
      - Ensure test results don't conflict with parallel workers
      - Use workspace-specific test result locations if needed
      
      ERROR HANDLING:
      - Return non-zero exit code on any failure
      - Log errors comprehensively for debugging
      - Never force changes outside allowlist scope
      - Report failures to ${REPORT_DIR}/error.log
```

## Implementation Steps

1. **Update spawn message format** in orchestrator to include all variables
2. **Add message parsing logic** in linter-fixer to extract variables
3. **Remove state file dependencies** from both modes
4. **Update workspace handling** to work from root directory
5. **Implement report isolation** using task-specific directories
6. **Test workspace isolation** with parallel execution
7. **Verify jj command isolation** (may need workspace-specific flags)

## Migration Checklist

- [ ] Backup current .roomodes
- [ ] Update .roomodes with new configuration
- [ ] Test orchestrator spawn message format
- [ ] Test linter-fixer variable parsing
- [ ] Verify workspace isolation
- [ ] Test parallel execution
- [ ] Validate report segregation
- [ ] Clean up any remaining state file references

## Notes on Jujutsu Integration

Based on documentation research:
- Jujutsu has native workspace support
- Each workspace has its own working-copy commit
- May need to investigate appropriate flags for workspace isolation
- Consider using workspace-specific commands if available

## Risk Mitigation

- **Backward compatibility:** Keep old scripts as backup during transition
- **Gradual rollout:** Test with single worker before parallel execution
- **Monitoring:** Enhanced logging during initial deployment
- **Rollback plan:** Ability to revert to state-file approach if needed
