# Sub-Agent Task: Fix Tool Executor Middleware Tests

**Model**: Claude 3.5 Sonnet (Sonnet 4)

**Priority**: Medium

**Context**: 
The AI Paralegal application has failing middleware tests in `/workspace/tests/unit/test_tool_executor.py`. The tests are failing due to incorrect expectations about middleware execution order and logging behavior.

**Failed Tests**:
1. `test_initialization` - Mock object key issue
2. `test_middleware_execution_order` - Middleware executes in wrong order
3. `test_logging_middleware` - Log message not found
4. `test_validation_middleware` - Error message mismatch

**Error Details**:

1. **Initialization Test**:
```
AssertionError: assert 'test_tool' in {<Mock name='test_tool.name' id='139705562789408'>: ...}
```
The test expects string keys but the circuit breakers are using mock objects as keys.

2. **Middleware Order**:
```
Expected: ['middleware2_before', 'middleware1_before', 'tool_execute', 'middleware1_after', 'middleware2_after']
Actual:   ['middleware1_before', 'middleware2_before', 'tool_execute', 'middleware2_after', 'middleware1_after']
```
The middleware is executing in the order they were added, not reverse order.

3. **Logging Middleware**:
```
assert "Executing tool 'test_tool'" in caplog.text
```
The log is being written to stdout, not captured by caplog.

4. **Validation Middleware**:
```
assert 'requires arguments' in str(exc_info.value)
```
The error message is "Validation failed" not "requires arguments".

**Root Cause Analysis**:
1. The circuit breakers are using `tool.name` as keys, but in the test, `tool.name` is a Mock object
2. The middleware execution order is not reversed as the test expects
3. The logging is using a different logger that's not captured by pytest's caplog
4. The validation error message doesn't match the test expectation

**Required Fixes**:
1. Fix the mock setup so `tool.name` returns a string, not a Mock
2. Either fix the middleware to execute in reverse order OR update the test expectation
3. Fix the logging test to capture the correct logger output
4. Update the validation error message assertion

**Environment Note**:
- Docker commands must be run with `sudo` (e.g., `sudo docker ps`, `sudo docker compose up`)
- The virtual environment is at `.venv` and should be activated before running tests

**Test Command**:
```bash
cd /workspace && source .venv/bin/activate
python -m pytest tests/unit/test_tool_executor.py::TestToolExecutorInitialization::test_initialization -v --no-cov
python -m pytest tests/unit/test_tool_executor.py::TestMiddleware -v --no-cov
```

**Success Criteria**:
All 4 failing tool executor tests should pass.

**Instructions**:
1. For the initialization test:
   - Check how the mock tools are created in the fixture
   - Ensure each mock tool has a `.name` attribute that returns a string
   
2. For middleware order:
   - Check the ToolExecutor implementation to see the actual execution order
   - Either fix the implementation or update the test expectation
   
3. For logging middleware:
   - Check which logger is being used in the middleware
   - Either capture the correct logger or check stdout capture
   
4. For validation middleware:
   - Check what error message is actually raised
   - Update the assertion to match the actual error message

5. Run all the tests to verify they pass
