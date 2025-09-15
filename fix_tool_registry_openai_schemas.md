# Sub-Agent Task: Fix Tool Registry OpenAI Schemas Test

**Model**: Claude 3.5 Sonnet (Sonnet 4)

**Priority**: Low

**Context**: 
The AI Paralegal application has a failing test for getting OpenAI schemas in `/workspace/tests/unit/test_tool_registry.py`. The test is failing because the decorator validates that function parameters match the defined parameters.

**Failed Test**:
- `TestToolRegistry::test_get_openai_schemas`

**Error Details**:
```
ValueError: Tool 'tool1' parameter mismatch. Defined: {'arg'}, Function has: set()
```

**Root Cause Analysis**:
The test is defining a tool with a parameter named 'arg', but the decorated function has no parameters. The decorator at line 156 in tool_registry.py validates that the function signature matches the defined parameters.

**Code Locations**:
- Implementation: `/workspace/app/core/tool_registry.py` (line 156 - parameter validation)
- Test: `/workspace/tests/unit/test_tool_registry.py` (line 328)

**The Problem**:
The test defines:
```python
params1 = [ToolParameter("arg", "string", "Argument", required=True)]
```

But then decorates a function with no parameters:
```python
@registry.register(name="tool1", ..., parameters=params1)
async def tool1() -> str:
    return "result1"
```

**Required Fixes**:
Update the test functions to have parameters matching their ToolParameter definitions:
1. `tool1` should have an `arg` parameter
2. `tool2` should have a `num` parameter with default value 10

**Environment Note**:
- Docker commands must be run with `sudo` (e.g., `sudo docker ps`, `sudo docker compose up`)
- The virtual environment is at `.venv` and should be activated before running tests

**Test Command**:
```bash
cd /workspace && source .venv/bin/activate
python -m pytest tests/unit/test_tool_registry.py::TestToolRegistry::test_get_openai_schemas -v --no-cov
```

**Success Criteria**:
The OpenAI schemas test should pass, correctly generating schemas for the registered tools.

**Instructions**:
1. Look at the test function starting around line 328
2. Update the function signatures:
   - `async def tool1(arg: str) -> str:`
   - `async def tool2(num: int = 10) -> str:`
3. Make sure the function parameters match the ToolParameter definitions
4. Run the test to verify it passes