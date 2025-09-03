# Testing Plan for Refactored .roomodes Configuration

## Testing Strategy

### Phase 1: Variable Parsing Testing

**Test 1: Message Parsing Validation**
```bash
# Test message format parsing
test_message="TASK_ID=ArgumentType|WORKSPACE_PATH=.jj-workspaces/ws-arg-123|ALLOWLIST_CONTENT=app/models.py\napp/services.py|BASE_BOOKMARK=refactor/ai-sdk|REPORT_DIR=./pyright_reports/ArgumentType/|Fix ArgumentType errors in workspace"

# Expected parsing results:
# TASK_ID = "ArgumentType"
# WORKSPACE_PATH = ".jj-workspaces/ws-arg-123"
# ALLOWLIST_CONTENT = ["app/models.py", "app/services.py"] (split on \n)
# BASE_BOOKMARK = "refactor/ai-sdk"
# REPORT_DIR = "./pyright_reports/ArgumentType/"
```

**Test 2: Edge Cases**
- Empty variables
- Special characters in file paths
- Very long allowlists
- Missing variables
- Malformed message format

### Phase 2: Workspace Isolation Testing

**Test 3: Jujutsu Repository Flag Verification**
```bash
# First verify the correct jj flag syntax
jj --help | grep -i repository
jj --help | grep -i "\-R"

# Test workspace isolation
ws=".jj-workspaces/test-ws-$(date +%s)"
mkdir -p "$ws"

# Test various jj commands with isolation
jj --repository="$ws" init  # or whatever the correct syntax is
jj --repository="$ws" status
jj --repository="$ws" log
```

**Test 4: File Modification Isolation**
```bash
# Create test workspace
ws=".jj-workspaces/test-ws-$(date +%s)"
mkdir -p "$ws"
cp -r app/ "$ws/"  # Copy some test files

# Test that modifications only happen within workspace
# Worker should only modify files within $ws
touch "$ws/app/test_file.py"
echo "# Test modification" >> "$ws/app/test_file.py"

# Verify no changes outside workspace
git status  # Should show no changes in main directory
```

### Phase 3: Report Isolation Testing

**Test 5: Report Directory Creation**
```bash
# Test report directory creation for different tasks
tasks=("ArgumentType" "AssignmentType" "ReturnType")

for task in "${tasks[@]}"; do
  report_dir="./pyright_reports/$task/"
  mkdir -p "$report_dir"
  
  # Test report generation
  echo "Test report for $task" > "$report_dir/summary.md"
  echo "Test actions" > "$report_dir/actions.log"
  echo "Test errors" > "$report_dir/errors.log"
  
  # Verify isolation
  ls -la "./pyright_reports/"
done
```

### Phase 4: Parallel Execution Testing

**Test 6: Concurrent Worker Simulation**
```bash
# Simulate multiple workers running in parallel
test_parallel_workers() {
  local max_workers=3
  
  for i in $(seq 1 $max_workers); do
    task_id="TestTask$i"
    ws=".jj-workspaces/ws-$task_id-$(date +%s)"
    report_dir="./pyright_reports/$task_id/"
    
    # Simulate worker spawn (in background)
    (
      echo "Worker $i starting with workspace: $ws"
      mkdir -p "$ws"
      mkdir -p "$report_dir"
      
      # Simulate work
      sleep 2
      echo "Worker $i completed" > "$report_dir/completion.log"
    ) &
  done
  
  # Wait for all workers
  wait
  
  # Verify no conflicts
  ls -la ./pyright_reports/
  ls -la .jj-workspaces/
}
```

### Phase 5: Integration Testing

**Test 7: Full Orchestrator Simulation**
```bash
# Test complete orchestrator -> worker flow
simulate_orchestrator() {
  # Phase 1: Setup
  task_id="IntegrationTest"
  timestamp=$(date +%s)
  ws=".jj-workspaces/ws-$task_id-$timestamp"
  report_dir="./pyright_reports/$task_id/"
  allowlist="app/models.py\napp/services.py"
  base_bookmark="refactor/test"
  
  # Create workspace and reports
  mkdir -p "$ws"
  mkdir -p "$report_dir"
  
  # Phase 2: Construct message
  message="TASK_ID=$task_id|WORKSPACE_PATH=$ws|ALLOWLIST_CONTENT=$allowlist|BASE_BOOKMARK=$base_bookmark|REPORT_DIR=$report_dir|Integration test message"
  
  echo "Orchestrator would spawn with message: $message"
  
  # Phase 3: Simulate worker processing
  echo "Parsing variables from: $message"
  # (Manual parsing simulation for testing)
  
  echo "Worker would:"
  echo "- Work in directory: $(pwd)"
  echo "- Modify files in: $ws"
  echo "- Generate reports in: $report_dir"
  echo "- Use jj commands with: --repository=$ws"
  
  # Phase 4: Cleanup test
  echo "Cleanup test:"
  echo "rm -rf $ws"
  echo "ls -la .jj-workspaces/"
}
```

## Validation Checklist

### Variable Passing ✓
- [ ] Message format correctly parsed
- [ ] All variables extracted properly
- [ ] Edge cases handled gracefully
- [ ] Error messages clear for malformed input

### Workspace Isolation ✓
- [ ] Workers run from root directory
- [ ] File modifications only within workspace
- [ ] Jujutsu commands isolated to workspace
- [ ] No interference between parallel workers

### Report Isolation ✓
- [ ] Each task has separate report directory
- [ ] No conflicts between parallel report generation
- [ ] Reports contain expected content
- [ ] Error logging works correctly

### State Independence ✓
- [ ] No state file dependencies
- [ ] Workers are self-contained
- [ ] All context passed in spawn message
- [ ] No shared state between workers

### Dependency Management ✓
- [ ] Poetry commands work from root directory
- [ ] Dependencies installed correctly
- [ ] Lock file updates don't conflict

### Test Isolation ✓
- [ ] Tests run within workspace context
- [ ] Test results don't conflict
- [ ] Test failures reported correctly

## Test Environment Setup

```bash
# Create test environment
setup_test_env() {
  # Backup current .roomodes
  cp .roomodes .roomodes.backup
  
  # Create test directories
  mkdir -p .jj-workspaces
  mkdir -p pyright_reports
  
  # Create test files
  mkdir -p test_files/app
  echo "# Test file 1" > test_files/app/models.py
  echo "# Test file 2" > test_files/app/services.py
  
  # Initialize test repository if needed
  if [ ! -d .jj ]; then
    jj git init --colocate
  fi
}

cleanup_test_env() {
  # Remove test artifacts
  rm -rf .jj-workspaces/test-*
  rm -rf pyright_reports/Test*
  rm -rf test_files/
  
  # Restore original .roomodes
  cp .roomodes.backup .roomodes
}
```

## Expected Outcomes

After successful testing:

1. **Variable parsing works correctly** - All spawn message variables are extracted properly
2. **Workspace isolation is maintained** - Workers only modify files within their workspace
3. **Reports are isolated** - Each task generates reports in separate directories
4. **Parallel execution works** - Multiple workers can run simultaneously without conflicts
5. **No state file dependencies** - Workers are completely self-contained
6. **Jujutsu commands are isolated** - All jj commands target specific workspace

## Risk Areas to Monitor

1. **Jujutsu flag syntax** - Verify `--repository` flag exists and works as expected
2. **File path handling** - Ensure paths with spaces/special characters work
3. **Message parsing robustness** - Handle malformed messages gracefully
4. **Resource conflicts** - Monitor for any remaining shared resources
5. **Test isolation** - Ensure parallel test runs don't interfere

## Next Steps After Testing

1. Deploy refactored configuration
2. Monitor initial runs closely
3. Adjust based on real-world usage
4. Document any additional findings
5. Update scripts that interact with the modes
