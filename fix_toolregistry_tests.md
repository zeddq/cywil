# Sub-Agent Task: Fix Tool Registry Tests

**Model**: Claude 3.5 Sonnet (Sonnet 4)

**Priority**: Medium

**Context**:
The AI Paralegal application has failing tool registry tests in `/workspace/tests/unit/test_tool_registry.py`.

**Failed Tests**:
Multiple tests failing with: `AttributeError: 'ToolRegistry' object has no attribute 'register_tool'`

**Root Cause Analysis**:
The ToolRegistry API has changed. The tests are trying to use a `register_tool` method that doesn't exist. The actual implementation uses a decorator pattern with `@registry.register()`.

**Code Locations**:
- Implementation: `/workspace/app/core/tool_registry.py`
- Tests: `/workspace/tests/unit/test_tool_registry.py`

**Required Fixes**:
1. Update all tests to use the correct API (decorator pattern instead of method calls)
2. Fix the `test_execute_tool_not_found` test that expects `ToolNotFoundError` but gets `ValueError`
3. Ensure test fixtures properly mock the registry behavior

**Example of current vs expected**:
```python
# Current (failing):
registry.register_tool("test", test_tool, "Test", ToolCategory.UTILITY, [])

# Expected (based on actual implementation):
@registry.register(
    name="test",
    description="Test", 
    category=ToolCategory.UTILITY,
    parameters=[]
)
def test_tool():
    pass
```

**Environment Note**:
- Docker commands must be run with `sudo` (e.g., `sudo docker ps`, `sudo docker compose up`)
- The virtual environment is at `.venv` and should be activated before running tests

**Test Command**:
```bash
cd /workspace && source .venv/bin/activate
python -m pytest tests/unit/test_tool_registry.py -v --no-cov
```

**Success Criteria**:
All tool registry tests should pass.

**Instructions**:
1. Read the ToolRegistry implementation in `/workspace/app/core/tool_registry.py` to understand the actual API
2. Update each test to use the decorator pattern or find the correct method names
3. Some tests might need to be restructured to work with the decorator pattern
4. Pay attention to the error types - `ToolNotFoundError` vs `ValueError`
5. Run all tests to ensure your changes work correctly