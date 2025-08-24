"""
Pytest configuration and shared fixtures for all tests.
"""
try:
    import pytest
except ImportError:
    # pytest not available - likely running in non-test environment
    pytest = None
import asyncio
from unittest.mock import Mock, patch
import sys
import os

# Add the app directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singleton instances between tests"""
    # Reset service container
    from app.core.service_container import service_container
    service_container._singletons.clear()
    service_container._factories.clear()
    
    # Reset tool registry
    from app.core.tool_registry import tool_registry
    tool_registry._tools.clear()
    
    yield
    
    # Cleanup after test
    service_container._singletons.clear()
    service_container._factories.clear()
    tool_registry._tools.clear()


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock environment variables for testing"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("QDRANT_HOST", "localhost")
    monkeypatch.setenv("QDRANT_PORT", "6333")
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client"""
    mock_client = Mock()
    mock_client.api_key = "test-key"
    
    # Mock completions
    mock_completion = Mock()
    mock_completion.choices = [Mock(message=Mock(content="Test response"))]
    mock_client.completions.create = Mock(return_value=mock_completion)
    
    # Mock embeddings
    mock_embedding = Mock()
    mock_embedding.data = [Mock(embedding=[0.1, 0.2, 0.3])]
    mock_client.embeddings.create = Mock(return_value=mock_embedding)
    
    return mock_client


@pytest.fixture
def mock_qdrant_client():
    """Mock Qdrant client"""
    from qdrant_client import AsyncQdrantClient
    
    mock_client = Mock(spec=AsyncQdrantClient)
    mock_client.get_collections = Mock(return_value=Mock(collections=[]))
    mock_client.search = Mock(return_value=[])
    mock_client.scroll = Mock(return_value=([], None))
    
    return mock_client


@pytest.fixture
def sample_conversation_state():
    """Sample conversation state for testing"""
    from app.core.conversation_manager import ConversationState
    from datetime import datetime
    
    return ConversationState(
        conversation_id="test_conv_123",
        last_response_id="test_resp_456",
        case_id="test_case_789",
        user_id="test_user_abc",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        metadata={"test": True}
    )


@pytest.fixture
def sample_tool_definition():
    """Sample tool definition for testing"""
    from app.core.tool_registry import ToolDefinition, ToolParameter, ToolCategory
    
    async def sample_tool(arg1: str, arg2: int = 5) -> dict:
        return {"result": f"{arg1}_{arg2}"}
    
    return ToolDefinition(
        name="sample_tool",
        description="A sample tool for testing",
        category=ToolCategory.UTILITY,
        parameters=[
            ToolParameter("arg1", "string", "First argument", required=True),
            ToolParameter("arg2", "integer", "Second argument", required=False, default=5)
        ],
        function=sample_tool,
        returns="Sample result"
    )


@pytest.fixture
def sample_stream_events():
    """Sample streaming events for testing"""
    from app.core.streaming_handler import StreamEvent, StreamEventType
    
    return [
        StreamEvent(
            type=StreamEventType.CREATED,
            thread_id="test_thread_123"
        ),
        StreamEvent(
            type=StreamEventType.TEXT_DELTA,
            content="Hello "
        ),
        StreamEvent(
            type=StreamEventType.TEXT_DELTA,
            content="world!"
        ),
        StreamEvent(
            type=StreamEventType.TEXT_COMPLETE,
            content="Hello world!"
        ),
        StreamEvent(
            type=StreamEventType.COMPLETED,
            thread_id="test_thread_123",
            metadata={"usage": {"total_tokens": 10}}
        )
    ]


@pytest.fixture
def disable_logging():
    """Disable logging during tests to reduce noise"""
    import logging
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


# Async test markers
def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests"
    )
    config.addinivalue_line(
        "markers", "http: tests that require running HTTP API at localhost:8000"
    )


def pytest_collection_modifyitems(config, items):
    """Skip HTTP-marked tests if API is not running locally."""
    import socket
    def is_port_open(host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                return s.connect_ex((host, port)) == 0
            except OSError:
                return False

    api_up = is_port_open("localhost", 8000)
    if api_up:
        return

    skip_http = pytest.mark.skip(reason="HTTP API not running on localhost:8000")
    for item in items:
        if any(mark.name == "http" for mark in item.iter_markers()):
            item.add_marker(skip_http)
