# Sub-Agent Task: Fix Tool Executor Tests

**Model**: Claude 3.5 Sonnet (Sonnet 4)

**Priority**: High

**Context**:
The AI Paralegal application has failing tool executor tests in `/workspace/tests/unit/test_tool_executor.py`.

**Error Pattern**:
All tests fail during setup with:
```
AttributeError: <module 'app.core.tool_executor' from '/workspace/app/core/tool_executor.py'> does not have the attribute 'get_config'
```

**Root Cause Analysis**:
The test fixtures are trying to patch `app.core.tool_executor.get_config`, but this function doesn't exist in that module. The configuration is likely handled differently now.

**Code Locations**:
- Implementation: `/workspace/app/core/tool_executor.py`
- Tests: `/workspace/tests/unit/test_tool_executor.py` (line 30 in fixture)

**Required Fixes**:
1. Identify how ToolExecutor actually gets its configuration
2. Update the test fixture to properly mock the configuration
3. Ensure all test setups use the correct mocking approach

**Environment Note**:
- Docker commands must be run with `sudo` (e.g., `sudo docker ps`, `sudo docker compose up`)
- The virtual environment is at `.venv` and should be activated before running tests

**Test Command**:
```bash
cd /workspace && source .venv/bin/activate
python -m pytest tests/unit/test_tool_executor.py -v --no-cov
```

**Success Criteria**:
All tool executor tests should pass.

**Instructions**:
1. First, examine `/workspace/app/core/tool_executor.py` to see how it gets configuration
2. Check if it uses dependency injection or imports configuration differently
3. Update the fixture in the test file to mock the correct location
4. The fix might be as simple as changing the patch target from `app.core.tool_executor.get_config` to the actual location
5. Make sure all tests in the file use the updated fixture
6. Run the tests to verify they pass