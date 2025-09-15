# Sub-Agent Task: Fix Agent SDK Dependency Injection Tests

**Model**: Claude 3.5 Sonnet (Sonnet 4)

**Priority**: High

**Context**: 
The AI Paralegal application has failing agent SDK tests in `/workspace/tests/unit/test_agent_sdk.py`. The ParalegalAgentSDK class has been refactored to use dependency injection, but the tests are still trying to instantiate it without the required arguments.

**Failed Tests**:
- `test_agent_initialization`
- `test_agent_streaming`

**Error Details**:
```
TypeError: ParalegalAgentSDK.__init__() missing 3 required positional arguments: 'config_service', 'conversation_manager', and 'tool_executor'
```

**Root Cause Analysis**:
The ParalegalAgentSDK constructor (in `/workspace/app/paralegal_agents/refactored_agent_sdk.py`) now requires three services to be injected:
1. `config_service: ConfigService`
2. `conversation_manager: ConversationManager`
3. `tool_executor: ToolExecutor`

However, the tests are trying to create the SDK with no arguments: `agent = ParalegalAgentSDK()`

**Code Locations**:
- Implementation: `/workspace/app/paralegal_agents/refactored_agent_sdk.py` (constructor at line ~55)
- Tests: `/workspace/tests/unit/test_agent_sdk.py` (lines 24 and 56)

**Required Fixes**:
1. Update both test functions to create proper mock objects for the three required services
2. Use `MagicMock` or `AsyncMock` from unittest.mock for the service dependencies
3. Ensure the mocks have any attributes/methods that the SDK expects to call
4. The test at line 27 attempts to patch a non-existent path (`app.agents.refactored_agent_sdk.initialize_services`), this needs to be corrected or removed

**Environment Note**:
- Docker commands must be run with `sudo` (e.g., `sudo docker ps`, `sudo docker compose up`)
- The virtual environment is at `.venv` and should be activated before running tests

**Test Command**:
```bash
cd /workspace && source .venv/bin/activate
python -m pytest tests/unit/test_agent_sdk.py -v --no-cov
```

**Success Criteria**:
Both agent SDK tests should pass without TypeError.

**Instructions**:
1. Read the ParalegalAgentSDK constructor to understand what methods/attributes it expects from each service
2. Create appropriate mocks:
   - `mock_config_service` - likely needs a `config` attribute
   - `mock_conversation_manager` - check what methods are called
   - `mock_tool_executor` - check what methods are called
3. Update both test functions to pass these mocks when creating the SDK
4. Fix or remove the incorrect patch path
5. Run the tests to verify they pass