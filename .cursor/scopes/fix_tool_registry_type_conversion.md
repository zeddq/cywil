# Sub-Agent Task: Fix Tool Registry Type Conversion

**Model**: Claude 3.5 Sonnet (Sonnet 4)

**Priority**: Medium

**Context**: 
The AI Paralegal application has a failing type conversion test in the tool registry. The issue is that the Pydantic model is expecting a string for `float_param` but receiving a float.

**Failed Test**:
- `TestParameterTypeConversion::test_type_conversion`

**Error Details**:
```
pydantic_core._pydantic_core.ValidationError: 1 validation error for typed_params
float_param
  Input should be a valid string [type=string_type, input_value=3.14, input_type=float]
```

**Root Cause Analysis**:
The tool registry is creating a Pydantic model where `float_param` is defined as type "number" in the ToolParameter, but the Pydantic model is interpreting it as a string type. The test is passing a float value (3.14) which Pydantic rejects.

**Code Locations**:
- Implementation: `/workspace/app/core/tool_registry.py` (create_pydantic_model method around line 85-105)
- Test: `/workspace/tests/unit/test_tool_registry.py` (line 539)

**The Problem**:
Looking at the test, the ToolParameter is defined as:
```python
ToolParameter("float_param", "number", "Float", required=True)
```

But when the Pydantic model is created, it's mapping "number" to `str` instead of `float`.

**Required Fixes**:
Fix the type mapping in the `create_pydantic_model` method to correctly map:
- "number" → `float`
- "integer" → `int`
- "string" → `str`
- "boolean" → `bool`
- "array" → `List`
- "object" → `Dict`

**Environment Note**:
- Docker commands must be run with `sudo` (e.g., `sudo docker ps`, `sudo docker compose up`)
- The virtual environment is at `.venv` and should be activated before running tests

**Test Command**:
```bash
cd /workspace && source .venv/bin/activate
python -m pytest tests/unit/test_tool_registry.py::TestParameterTypeConversion::test_type_conversion -v --no-cov
```

**Success Criteria**:
The type conversion test should pass, properly converting parameter types.

**Instructions**:
1. Look at the `create_pydantic_model` method in `/workspace/app/core/tool_registry.py`
2. Find where it maps parameter types to Python types
3. Fix the mapping so "number" maps to `float` instead of `str`
4. Ensure all other type mappings are correct
5. Run the test to verify it passes
