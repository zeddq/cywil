"""Tests for the OpenAI Agent SDK integration."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
# Add the app directory to the path
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.paralegal_agents import ParalegalAgentSDK


def create_mock_config_service():
    """Create a mock ConfigService with required attributes."""
    mock_config_service = MagicMock()
    mock_config = MagicMock()
    mock_openai_config = MagicMock()
    mock_api_key = MagicMock()
    mock_api_key.get_secret_value.return_value = "test-api-key"
    
    mock_openai_config.api_key = mock_api_key
    mock_openai_config.orchestrator_model = "gpt-4"
    mock_config.openai = mock_openai_config
    mock_config_service.config = mock_config
    
    return mock_config_service


def create_mock_conversation_manager():
    """Create a mock ConversationManager with required methods."""
    mock_manager = MagicMock()
    mock_manager.conversation_context = AsyncMock()
    mock_manager.link_to_case = AsyncMock()
    mock_manager.save_response_history = AsyncMock()
    mock_manager.update_conversation = AsyncMock()
    
    # Mock context manager
    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock()
    mock_context.__aexit__ = AsyncMock()
    mock_conv_state = MagicMock()
    mock_conv_state.case_id = None
    mock_conv_state.user_id = None
    mock_conv_state.last_response_id = None
    mock_context.__aenter__.return_value = mock_conv_state
    mock_manager.conversation_context.return_value = mock_context
    
    return mock_manager


def create_mock_tool_executor():
    """Create a mock ToolExecutor with required methods."""
    mock_executor = MagicMock()
    mock_executor.configure_circuit_breaker = MagicMock()
    mock_executor.configure_retry = MagicMock()
    mock_executor.add_middleware = MagicMock()
    mock_executor.get_metrics = AsyncMock(return_value={})
    mock_executor.reset_circuit = AsyncMock()
    return mock_executor


@pytest.mark.asyncio
async def test_agent_initialization():
    """Test that the agent can be initialized."""
    # Create mock services
    mock_config_service = create_mock_config_service()
    mock_conversation_manager = create_mock_conversation_manager()
    mock_tool_executor = create_mock_tool_executor()
    
    # Mock the external dependencies
    with patch('app.paralegal_agents.refactored_agent_sdk.AsyncOpenAI') as mock_openai:
        with patch('app.paralegal_agents.refactored_agent_sdk.get_tool_schemas') as mock_get_tools:
            with patch('app.paralegal_agents.refactored_agent_sdk.Agent') as mock_agent_class:
                
                # Setup mocks
                mock_openai.return_value = MagicMock()
                mock_get_tools.return_value = []
                mock_agent_instance = MagicMock()
                mock_agent_class.return_value = mock_agent_instance
                
                # Create agent with required dependencies
                agent = ParalegalAgentSDK(
                    config_service=mock_config_service,
                    conversation_manager=mock_conversation_manager,
                    tool_executor=mock_tool_executor
                )
                
                await agent.initialize()
                
                assert agent._initialized is True
                assert agent._agent is not None
                mock_get_tools.assert_called_once()
                mock_agent_class.assert_called_once()


@pytest.mark.asyncio
async def test_agent_streaming():
    """Test basic streaming functionality."""
    # Create mock services
    mock_config_service = create_mock_config_service()
    mock_conversation_manager = create_mock_conversation_manager()
    mock_tool_executor = create_mock_tool_executor()
    
    # Mock external dependencies
    with patch('app.paralegal_agents.refactored_agent_sdk.AsyncOpenAI') as mock_openai:
        with patch('app.paralegal_agents.refactored_agent_sdk.get_tool_schemas') as mock_get_tools:
            with patch('app.paralegal_agents.refactored_agent_sdk.Agent') as mock_agent_class:
                with patch('app.paralegal_agents.refactored_agent_sdk.Runner') as mock_runner:
                    
                    # Setup mocks
                    mock_openai.return_value = MagicMock()
                    mock_get_tools.return_value = []
                    mock_agent_instance = MagicMock()
                    mock_agent_class.return_value = mock_agent_instance
                    
                    # Create a mock streaming result
                    async def mock_stream_events():
                        # Simulate streaming events
                        event1 = MagicMock()
                        event1.type = "message"
                        event1.data = MagicMock()
                        event1.data.content = "Witam, "
                        yield event1
                        
                        event2 = MagicMock()
                        event2.type = "message"
                        event2.data = MagicMock()
                        event2.data.content = "jak mogę pomóc?"
                        yield event2
                        
                        event3 = MagicMock()
                        event3.type = "completion"
                        yield event3
                    
                    mock_result = MagicMock()
                    mock_result.stream_events = AsyncMock(return_value=mock_stream_events())
                    mock_runner.run_streamed.return_value = mock_result
                    
                    # Create agent with required dependencies
                    agent = ParalegalAgentSDK(
                        config_service=mock_config_service,
                        conversation_manager=mock_conversation_manager,
                        tool_executor=mock_tool_executor
                    )
                    
                    await agent.initialize()
                    
                    # Collect streamed events
                    events = []
                    async for event in agent.process_message_stream("Cześć"):
                        events.append(event)
                    
                    # Verify events
                    assert len(events) >= 3
                    assert any(e["type"] == "stream_start" for e in events)
                    assert any(e["type"] == "text_delta" for e in events)
                    assert any(e["type"] == "message_complete" for e in events) 
