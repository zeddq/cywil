# Migration Guide: OpenAI Agent SDK Integration

This guide documents the migration from the legacy `RefactoredParalegalAgent` to the new `ParalegalAgentSDK` that uses the OpenAI Agent SDK.

## Overview

The AI Paralegal POC has been refactored to use the [OpenAI Agent SDK](https://openai.github.io/openai-agents-python/quickstart/), which provides:

- Simplified agent creation and management
- Built-in streaming support
- Native tool integration using the `@tool` decorator
- Better handoff and guardrail capabilities
- Automatic tracing and observability

## Key Changes

### 1. Dependencies

Added `openai-agents-sdk==0.1.2` to `requirements.txt`.

### 2. New Agent Implementation

- **Old**: `app.orchestrator_refactored.RefactoredParalegalAgent`
- **New**: `app.agents.refactored_agent_sdk.ParalegalAgentSDK`

The new implementation maintains the same public API for compatibility:
- `initialize()` - Initialize the agent
- `process_message_stream()` - Process messages with streaming response

### 3. Tool Integration

Tools are now wrapped using the SDK's `@tool` decorator in `app.agents.tool_wrappers.py`:

```python
from agents import tool

@tool(name="search_statute", description="Search Polish civil law statutes")
async def search_statute_tool(params: SearchStatuteParams) -> str:
    # Implementation
```

### 4. Streaming

The SDK provides its own streaming events which are mapped to the existing format for compatibility:
- `event_type == "message"` → `"text_delta"`
- `event_type == "completion"` → `"message_complete"` and `"stream_complete"`
- `event_type == "tool_call"` → `"tool_calls"`

## Migration Steps

1. **Update imports**:
   ```python
   # Old
   from app.orchestrator_refactored import RefactoredParalegalAgent
   
   # New
   from app.agents import ParalegalAgentSDK
   ```

2. **Update class references**:
   ```python
   # Old
   agent = RefactoredParalegalAgent()
   
   # New
   agent = ParalegalAgentSDK()
   ```

3. **No API changes needed** - The public methods remain the same.

## Testing

New tests have been added in `tests/test_agent_sdk.py` to verify:
- Agent initialization
- Tool wrapper functionality
- Streaming behavior

Run tests with:
```bash
pytest tests/test_agent_sdk.py -v
```

## Benefits of Migration

1. **Simplified Tool Management**: Tools are now simple async functions with the `@tool` decorator
2. **Better Error Handling**: The SDK provides built-in error handling and recovery
3. **Native Streaming**: No need for custom streaming handlers
4. **Future Features**: Access to upcoming SDK features like guardrails, handoffs, and multi-agent orchestration

## Rollback

If needed, you can rollback by:
1. Reverting the import changes
2. The old implementation is preserved but marked as deprecated

## Next Steps

- Consider implementing guardrails for input validation
- Explore multi-agent handoffs for specialized tasks
- Enable SDK tracing for better observability 
