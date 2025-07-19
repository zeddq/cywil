# AI Paralegal Test Suite

Comprehensive test suite for the AI Paralegal POC system.

## Test Organization

### Unit Tests
- `test_database_manager.py` - Database connection pooling and transactions
- `test_tool_executor.py` - Circuit breaker and retry logic
- `test_streaming_handler.py` - OpenAI streaming protocol parsing
- `test_conversation_manager.py` - Conversation state management
- `test_performance_utils.py` - Caching and batching utilities
- `test_tool_registry.py` - Tool registration and execution

### Integration Tests
- `test_integration.py` - End-to-end workflows and service interactions

## Running Tests

### Install test dependencies
```bash
pip install -r requirements-test.txt
```

### Run all tests
```bash
pytest
```

### Run with coverage
```bash
pytest --cov=app --cov-report=html
```

### Run specific test categories
```bash
# Unit tests only
pytest -m unit

# Integration tests only  
pytest -m integration

# Exclude slow tests
pytest -m "not slow"
```

### Run specific test file
```bash
pytest tests/test_database_manager.py
```

### Run with verbose output
```bash
pytest -v
```

## Test Fixtures

Common fixtures are defined in `conftest.py`:

- `mock_config` - Mock configuration object
- `mock_env_vars` - Mock environment variables
- `mock_openai_client` - Mock OpenAI client
- `mock_qdrant_client` - Mock Qdrant client
- `sample_conversation_state` - Sample conversation state
- `sample_tool_definition` - Sample tool definition
- `sample_stream_events` - Sample streaming events

## Writing Tests

### Async Tests
```python
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result == expected
```

### Mocking Dependencies
```python
@pytest.fixture
def mock_service():
    service = Mock(spec=ServiceClass)
    service.method = AsyncMock(return_value="result")
    return service
```

### Testing Error Cases
```python
async def test_error_handling():
    with pytest.raises(ExpectedException) as exc_info:
        await function_that_raises()
    assert "expected message" in str(exc_info.value)
```

## Test Coverage

Current test coverage targets:
- Overall: 80%+ 
- Core components: 90%+
- Services: 85%+
- Utilities: 80%+

View coverage report:
```bash
open htmlcov/index.html
```

## Continuous Integration

Tests are automatically run on:
- Push to main branch
- Pull requests
- Nightly builds

CI configuration ensures:
- All tests pass
- Coverage thresholds met
- Code quality checks pass
- Type checking passes