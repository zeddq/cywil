# Pyright Orchestrator with AI Agent Integration

A comprehensive system for automated Pyright linter fixes using Jujutsu workspaces and Claude Code AI agents.

## Overview

The Pyright Orchestrator implements a sophisticated workflow that:
1. **Syncs** the base repository
2. **Builds** a task queue from non-empty pyright report files
3. **Spawns** up to 6 concurrent AI agent workers
4. **Isolates** each task in its own Jujutsu workspace
5. **Applies** AI-driven fixes with guardrails
6. **Validates** changes against allowlists
7. **Creates** PRs for successful fixes
8. **Generates** comprehensive reports

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Orchestrator  │───▶│  Task Queue     │───▶│ Worker Manager  │
│                 │    │ (pyright files) │    │ (Max 6 workers) │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                        │
                    ┌───────────────────────────────────┼───────────────────────────────────┐
                    │                                   ▼                                   │
         ┌─────────────────┐              ┌─────────────────┐              ┌─────────────────┐
         │    Worker 1     │              │    Worker N     │              │    Worker 6     │
         │                 │              │                 │              │                 │
         │ ┌─────────────┐ │              │ ┌─────────────┐ │              │ ┌─────────────┐ │
         │ │   Phase 1   │ │              │ │   Phase 1   │ │              │ │   Phase 1   │ │
         │ │   Setup     │ │              │ │   Setup     │ │              │ │   Setup     │ │
         │ └─────────────┘ │              │ └─────────────┘ │              │ └─────────────┘ │
         │ ┌─────────────┐ │              │ ┌─────────────┐ │              │ ┌─────────────┐ │
         │ │   Phase 2   │ │              │ │   Phase 2   │ │              │ │   Phase 2   │ │
         │ │ AI Agent    │ │              │ │ AI Agent    │ │              │ │ AI Agent    │ │
         │ └─────────────┘ │              │ └─────────────┘ │              │ └─────────────┘ │
         │ ┌─────────────┐ │              │ ┌─────────────┐ │              │ ┌─────────────┐ │
         │ │   Phase 3   │ │              │ │   Phase 3   │ │              │ │   Phase 3   │ │
         │ │Validate/PR  │ │              │ │Validate/PR  │ │              │ │Validate/PR  │ │
         │ └─────────────┘ │              │ └─────────────┘ │              │ └─────────────┘ │
         └─────────────────┘              └─────────────────┘              └─────────────────┘
                    │                                   │                                   │
                    └───────────────────────────────────┼───────────────────────────────────┘
                                                        │
                                                        ▼
                                            ┌─────────────────┐
                                            │ Merged Report   │
                                            │   Generator     │
                                            └─────────────────┘
```

## Components

### 1. Main Orchestrator (`scripts/pyright_orchestrator.sh`)

The main orchestrator script that coordinates the entire process.

**Usage:**
```bash
./scripts/pyright_orchestrator.sh [OPTIONS]

Options:
  --base-bookmark NAME    Base bookmark for all tasks (default: main)
  --max-concurrency N     Maximum parallel workers (default: 6)
  --reports-dir DIR       Pyright reports directory (default: pyright_reports)
  --dry-run              Show what would be done without executing
  --help                 Show this help
```

**Example:**
```bash
# Run with default settings
./scripts/pyright_orchestrator.sh

# Dry run to see what would happen
./scripts/pyright_orchestrator.sh --dry-run

# Custom concurrency and base
./scripts/pyright_orchestrator.sh --max-concurrency 4 --base-bookmark develop
```

### 2. AI Agent Integration (`scripts/spawn_linter_agent.sh`)

Specialized script that spawns Claude Code Task tool sub-agents for linter fixes.

**Features:**
- Uses Claude Code Task tool for proper agent spawning
- Environment variable injection for sub-agents
- Focused error category handling
- Safe change validation

### 3. Worker Scripts

**Phase 1: Setup (`scripts/pyright_worker_prefix.sh`)**
- Creates isolated Jujutsu workspace
- Syncs repository
- Validates allowlist files
- Prepares environment for AI agent

**Phase 3: Validation (`scripts/pyright_worker_postfix.sh`)**
- Validates changes against allowlist
- Runs optional tests
- Commits changes with descriptive messages
- Pushes to remote and creates PRs
- Generates artifacts (diffs, summaries)

### 4. Setup and Monitoring

**Setup (`scripts/setup_periodic_orchestrator.sh`)**
```bash
# Setup daily runs at 2 AM
./scripts/setup_periodic_orchestrator.sh

# Custom schedule (every 6 hours)
./scripts/setup_periodic_orchestrator.sh --cron-schedule "0 */6 * * *"

# Remove cron job
./scripts/setup_periodic_orchestrator.sh --remove
```

**Status Monitoring (`scripts/orchestrator_status.sh`)**
```bash
# Show current status
./scripts/orchestrator_status.sh

# Show workspace details
./scripts/orchestrator_status.sh --workspaces

# Clean up old files
./scripts/orchestrator_status.sh --cleanup

# Watch mode (refreshes every 30s)
./scripts/orchestrator_status.sh --watch
```

## Supported Pyright Error Types

The orchestrator handles 16 categories of Pyright errors:

1. **reportArgumentType** - Function argument type mismatches
2. **reportAssignmentType** - Assignment type incompatibilities  
3. **reportAttributeAccessIssue** - Attribute access on wrong types
4. **reportCallIssue** - Function call problems
5. **reportGeneralTypeIssues** - General type system violations
6. **reportIndexIssue** - Index access type problems
7. **reportMissingImports** - Missing import statements
8. **reportMissingModuleSource** - Missing module sources
9. **reportOperatorIssue** - Operator usage type problems
10. **reportOptionalMemberAccess** - Optional member access issues
11. **reportOptionalOperand** - Optional operand problems
12. **reportOptionalSubscript** - Optional subscript issues
13. **reportRedeclaration** - Variable redeclaration problems
14. **reportReturnType** - Function return type mismatches
15. **reportUnboundVariable** - Unbound variable references
16. **reportUndefinedVariable** - Undefined variable usage

## Workflow Details

### Three-Phase Worker Process

Each worker follows a strict three-phase process:

#### Phase 1: Setup and Validation
- Creates isolated Jujutsu workspace: `.jj-workspaces/ws-{task_id}-{timestamp}`
- Syncs with base bookmark (default: `main`)
- Validates allowlist file exists and is readable
- Creates workspace bookmark: `task/{task_id}-{timestamp}`
- Writes state information for Phase 3

#### Phase 2: AI Agent Fixes
- Spawns linter-fixer or paralegal-linter-fixer sub-agent via Claude Code Task tool
- Provides environment variables:
  - `TASK_ID`: Error type being fixed
  - `WORKSPACE_PATH`: Workspace directory
  - `ALLOWLIST_FILE`: Path to allowlist file
  - `ALLOWLIST_CONTENT`: Contents of allowlist
- Agent applies focused fixes only to allowlisted files
- Preserves existing functionality and code structure

#### Phase 3: Validation and Publishing
- Validates all changes are within allowlist scope
- Runs optional tests if configured
- Commits changes with descriptive messages
- Pushes bookmark to remote as Git branch
- Creates GitHub PR using `gh` CLI
- Generates artifacts: summary, diff, PR metadata

### Concurrency Control

- Maximum 6 concurrent workers by default (configurable)
- Workers process independent task queues
- Isolated workspaces prevent conflicts
- Cleanup on completion or failure

### Isolation and Safety

**Workspace Isolation:**
- Each task gets its own Jujutsu workspace
- Workspace path: `.jj-workspaces/ws-{task_id}-{timestamp}`
- No cross-task interference

**File Allowlist Guardrails:**
- Each task has a specific allowlist of modifiable files
- AI agents can only modify allowlisted files
- Changes outside allowlist cause worker failure
- Preserves repository integrity

**Change Validation:**
- Pre-commit validation of allowlist compliance
- Optional test execution
- Automated rollback on validation failure

## Configuration

### Environment Variables

```bash
# Base bookmark for all tasks (default: main)
export BASE_BOOKMARK=main

# Maximum concurrent workers (default: 6)
export MAX_CONCURRENCY=6

# Optional test command for validation
export RUN_TESTS_CMD="tools/run_tests_periodic.py"
```

### Directory Structure

```
project/
├── scripts/
│   ├── pyright_orchestrator.sh          # Main orchestrator
│   ├── spawn_linter_agent.sh            # AI agent integration
│   ├── pyright_worker_prefix.sh         # Phase 1 worker
│   ├── pyright_worker_postfix.sh        # Phase 3 worker
│   ├── setup_periodic_orchestrator.sh   # Cron setup
│   └── orchestrator_status.sh           # Monitoring
├── pyright_reports/
│   ├── reportArgumentType.txt            # Error allowlists
│   ├── reportMissingImports.txt
│   └── ...                             # Other report files
├── reports/
│   └── {timestamp}/
│       ├── merged_report.md             # Consolidated report
│       └── tasks/
│           ├── {task_id}.log           # Worker logs
│           ├── {task_id}.summary.md    # Task summaries
│           ├── {task_id}.diff.patch    # Change diffs
│           └── {task_id}.pr.json       # PR metadata
├── .jj-workspaces/                      # Temporary workspaces
└── logs/
    └── orchestrator_cron.log           # Cron execution logs
```

## Output Artifacts

### Per-Task Artifacts

For each processed task, the following artifacts are generated:

- **`.log`** - Complete worker execution log
- **`.summary.md`** - Markdown summary with task details
- **`.diff.patch`** - Git-format diff of all changes
- **`.pr.json`** - GitHub PR metadata (URL, number)
- **`.state`** - Worker state information

### Merged Report

A comprehensive report combining all task results:

```markdown
# Pyright Orchestrator Run Report

**Timestamp:** 20250829T020722Z
**Base Bookmark:** main
**Max Concurrency:** 6
**Tasks Processed:** 7

## Task Summary

### ArgumentType
- Status: Completed successfully
- Files changed: 12
- PR: https://github.com/user/repo/pull/123

### MissingImports  
- Status: Completed successfully
- Files changed: 8
- PR: https://github.com/user/repo/pull/124

...
```

## Prerequisites

### Required Tools

1. **Jujutsu (`jj`)** - Version control system
   ```bash
   # Install via Homebrew (macOS)
   brew install jj
   
   # Initialize colocated Git repo
   jj git init --colocate
   ```

2. **Claude Code CLI (`claude`)**
   ```bash
   # Install Claude Code CLI
   # Follow installation instructions from Anthropic
   ```

3. **GitHub CLI (`gh`)** - For PR creation
   ```bash
   # Install via Homebrew
   brew install gh
   
   # Authenticate
   gh auth login
   ```

4. **jq** - JSON processing
   ```bash
   brew install jq
   ```

### Repository Setup

The repository must be configured as a colocated Jujutsu/Git repository:

```bash
# Initialize colocated repository
jj git init --colocate

# Add remote origin
git remote add origin https://github.com/user/repo.git

# Verify setup
jj root  # Should show repository root
```

### Pyright Reports

The orchestrator expects pyright report files in the `pyright_reports/` directory. Generate these using the existing `scripts/pyright_report_by_rule.py` script:

```bash
# Generate pyright reports by rule
python scripts/pyright_report_by_rule.py
```

## Usage Examples

### Basic Usage

```bash
# Run orchestrator once
./scripts/pyright_orchestrator.sh

# Dry run to preview
./scripts/pyright_orchestrator.sh --dry-run
```

### Setup Periodic Runs

```bash
# Setup daily runs at 2 AM
./scripts/setup_periodic_orchestrator.sh

# Custom schedule - every 4 hours
./scripts/setup_periodic_orchestrator.sh --cron-schedule "0 */4 * * *"

# Remove cron job
./scripts/setup_periodic_orchestrator.sh --remove
```

### Monitoring

```bash
# Show current status
./scripts/orchestrator_status.sh

# Watch live status (refreshes every 30s)
./scripts/orchestrator_status.sh --watch

# Show detailed logs
./scripts/orchestrator_status.sh --logs 200

# Clean up old files
./scripts/orchestrator_status.sh --cleanup
```

### Manual Task Testing

Test individual components:

```bash
# Test worker scripts manually
cd .jj-workspaces/test-workspace
./scripts/pyright_worker_prefix.sh --workspace $(pwd) --bookmark test-branch --allowlist-file pyright_reports/reportMissingImports.txt

# Test AI agent integration
./scripts/spawn_linter_agent.sh --task-id MissingImports --workspace $(pwd) --allowlist pyright_reports/reportMissingImports.txt
```

## Troubleshooting

### Common Issues

1. **"jj command not found"**
   - Install Jujutsu: `brew install jj`
   - Verify installation: `jj --version`

2. **"claude CLI not found"**
   - Install Claude Code CLI from Anthropic
   - Verify installation: `claude --version`

3. **Workspace creation fails**
   - Ensure you're in a Jujutsu repository: `jj root`
   - Check `.jj` directory exists
   - Verify Git remote is configured

4. **AI agent fails**
   - Check Claude Code authentication
   - Verify allowlist file exists and is readable
   - Check workspace has proper permissions

5. **PR creation fails**
   - Authenticate with GitHub: `gh auth login`
   - Verify remote repository access
   - Check branch push permissions

### Log Analysis

**Worker logs** (`.log` files) contain:
- Phase execution details
- AI agent output
- Error messages and stack traces
- Change validation results

**Cron logs** (`logs/orchestrator_cron.log`):
- Scheduled run timestamps
- Overall orchestrator success/failure
- Environment and PATH information

### Recovery Procedures

**Clean up stuck workspaces:**
```bash
# List all workspaces
jj workspace list

# Remove specific workspace
jj workspace forget ws-TaskName-timestamp

# Remove workspace directory
rm -rf .jj-workspaces/ws-TaskName-timestamp
```

**Reset failed runs:**
```bash
# Clean up old reports
./scripts/orchestrator_status.sh --cleanup

# Remove abandoned workspaces
find .jj-workspaces -name "ws-*" -mtime +1 -exec rm -rf {} \;
```

## Security Considerations

### Access Control

- AI agents only modify files in their allowlist
- Workspace isolation prevents cross-task interference
- Changes validated before commit
- PR creation requires authenticated GitHub access

### Safe Practices

- Allowlist enforcement prevents unauthorized changes
- Changes are reviewed in PR format before merge
- Test execution validates functionality
- Rollback capability through Git/Jujutsu history

### Sensitive Data

- Logs may contain file paths and code snippets
- PR descriptions include allowlist information
- Environment variables exported to AI agents

## Performance Tuning

### Concurrency Settings

```bash
# Adjust for available resources
export MAX_CONCURRENCY=4  # Reduce for limited resources
export MAX_CONCURRENCY=8  # Increase for powerful machines
```

### Resource Usage

- Each worker uses ~100MB RAM
- Workspace directories: ~50MB per task
- Network I/O for Git operations and AI API calls

### Optimization Tips

- Use SSD storage for workspace directories
- Ensure adequate RAM for concurrent workers
- Monitor network bandwidth for AI API calls
- Clean up old reports regularly

## Contributing

### Adding New Error Types

1. Add report file to `EXPECTED_TASK_FILES` array in orchestrator
2. Generate corresponding `report{ErrorType}.txt` file
3. Test with single task before full orchestration

### Extending Worker Phases

- **Phase 1**: Modify `pyright_worker_prefix.sh` for setup changes
- **Phase 2**: Update AI agent prompts in `spawn_linter_agent.sh`
- **Phase 3**: Extend `pyright_worker_postfix.sh` for validation logic

### Monitoring Enhancements

Add new metrics to `orchestrator_status.sh`:
- Success/failure rates
- Performance timing
- Resource usage statistics

## License

This orchestrator system is part of the AI Paralegal POC project and follows the same licensing terms.