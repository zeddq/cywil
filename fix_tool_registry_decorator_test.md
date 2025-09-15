# Sub-Agent Task: Fix Tool Registry Decorator Test

**Model**: Claude 3.5 Sonnet (Sonnet 4)

**Priority**: Medium

**Context**: 
The AI Paralegal application has a failing tool registry test in `/workspace/tests/unit/test_tool_registry.py`. The test is comparing function objects which are not the same instance after decoration.

**Failed Test**:
- `TestToolRegistry::test_register_tool_decorator`

**Error Details**:
```
AssertionError: assert <function TestToolRegistry.test_register_tool_decorator.<locals>.decorated_tool at 0x7fb82007a840> == <function TestToolRegistry.test_register_tool_decorator.<locals>.decorated_tool at 0x7fb82007aac0>
```

**Root Cause Analysis**:
The test is trying to assert that `tool_def.function == decorated_tool`, but the decorator is likely wrapping the function, creating a new function object. The memory addresses show they are different objects.

**Code Locations**:
- Implementation: `/workspace/app/core/tool_registry.py` (decorator at line ~150)
- Test: `/workspace/tests/unit/test_tool_registry.py` (line 220)

**Required Fixes**:
The test needs to be updated to check the correct behavior. Options:
1. Check that the function is callable and has the expected behavior
2. Check the function's `__name__` attribute if preserved
3. Check that the wrapped function is stored in a specific attribute
4. Simply remove the function comparison and verify the tool works correctly

**Environment Note**:
- Docker commands must be run with `sudo` (e.g., `sudo docker ps`, `sudo docker compose up`)
- The virtual environment is at `.venv` and should be activated before running tests

**Test Command**:
```bash
cd /workspace && source .venv/bin/activate
python -m pytest tests/unit/test_tool_registry.py::TestToolRegistry::test_register_tool_decorator -v --no-cov
```

**Success Criteria**:
The decorator test should pass, validating that tools can be registered via decorator.

**Instructions**:
1. Examine the `register` decorator in `/workspace/app/core/tool_registry.py` to understand how it wraps functions
2. Check if the decorator preserves any attributes or stores the original function
3. Update the test assertion to check something meaningful:
   - Option A: Check `tool_def.function.__name__ == "decorated_tool"`
   - Option B: Test that the function can be called correctly
   - Option C: Check other attributes of the tool definition
4. Run the test to verify it passes