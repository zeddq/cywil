# Sub-Agent Task: Fix Agent SDK Tests

**Model**: Claude 3.5 Sonnet (Sonnet 4)

**Priority**: Medium

**Context**:
The AI Paralegal application has failing agent SDK tests in `/workspace/tests/unit/test_agent_sdk.py`.

**Failed Tests**:
- `test_agent_initialization`
- `test_agent_streaming`

**Error**:
```
TypeError: ParalegalAgentSDK.__init__() missing 3 required positional arguments: 'config_service', 'conversation_manager', and 'tool_executor'
```

**Root Cause Analysis**:
The ParalegalAgentSDK constructor has changed to require dependency injection of services, but the tests are trying to instantiate it without arguments.

**Code Locations**:
- Implementation: `/workspace/app/paralegal_agents/refactored_agent_sdk.py`
- Tests: `/workspace/tests/unit/test_agent_sdk.py` (lines 24, 56)

**Required Fixes**:
1. Update tests to provide mock services when instantiating ParalegalAgentSDK
2. Create appropriate mock objects for config_service, conversation_manager, and tool_executor
3. Ensure the mocks have the necessary methods/attributes that the SDK expects

**Test Command**:
```bash
cd /workspace && source .venv/bin/activate
python -m pytest tests/unit/test_agent_sdk.py -v --no-cov
```

**Success Criteria**:
Both agent SDK tests should pass.

**Instructions**:
1. Read the ParalegalAgentSDK implementation to understand what it expects from the injected services
2. Create proper mocks for config_service, conversation_manager, and tool_executor
3. You might need to use `MagicMock` or `AsyncMock` from unittest.mock
4. Make sure the mocks have any attributes or methods that the SDK calls
5. Update both failing tests with the proper initialization
6. Run the tests to verify they pass