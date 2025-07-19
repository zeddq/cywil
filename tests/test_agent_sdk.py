"""Tests for the OpenAI Agent SDK integration."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents import ParalegalAgentSDK
from app.agents.tool_wrappers import (
    search_sn_rulings_tool,
    search_statute_tool,
    SearchSNRulingsParams,
    SearchStatuteParams,
)


@pytest.mark.asyncio
async def test_agent_initialization():
    """Test that the agent can be initialized."""
    agent = ParalegalAgentSDK()
    
    # Mock the service initialization
    with patch('app.agents.refactored_agent_sdk.initialize_services') as mock_init:
        mock_lifecycle = MagicMock()
        mock_lifecycle.startup = AsyncMock()
        mock_init.return_value = mock_lifecycle
        
        await agent.initialize()
        
        assert agent._initialized is True
        assert agent._agent is not None
        mock_lifecycle.startup.assert_called_once()


@pytest.mark.asyncio
async def test_search_sn_rulings_tool():
    """Test the Supreme Court rulings search tool wrapper."""
    # Mock the service
    with patch('app.agents.tool_wrappers.inject_service') as mock_inject:
        mock_service = MagicMock()
        mock_service.search_sn_rulings = AsyncMock(return_value=[])
        mock_inject.return_value = mock_service
        
        params = SearchSNRulingsParams(
            query="wyrok o odszkodowaniu",
            top_k=3
        )
        
        result = await search_sn_rulings_tool(params)
        
        assert isinstance(result, str)
        assert "[]" in result  # Empty list as JSON
        mock_service.search_sn_rulings.assert_called_once_with(
            query="wyrok o odszkodowaniu",
            top_k=3,
            filters=None
        )


@pytest.mark.asyncio
async def test_search_statute_tool():
    """Test the statute search tool wrapper."""
    with patch('app.agents.tool_wrappers.inject_service') as mock_inject:
        mock_service = MagicMock()
        mock_service.search_statute = AsyncMock(return_value=[
            {
                "article": "415",
                "code": "KC",
                "text": "Kto z winy swej wyrządził drugiemu szkodę...",
                "citation": "art. 415 KC"
            }
        ])
        mock_inject.return_value = mock_service
        
        params = SearchStatuteParams(
            query="odpowiedzialność deliktowa",
            code="KC"
        )
        
        result = await search_statute_tool(params)
        
        assert isinstance(result, str)
        assert "415" in result
        assert "KC" in result


@pytest.mark.asyncio
async def test_agent_streaming():
    """Test basic streaming functionality."""
    agent = ParalegalAgentSDK()
    
    # Mock initialization and Runner
    with patch('app.agents.refactored_agent_sdk.initialize_services') as mock_init:
        mock_lifecycle = MagicMock()
        mock_lifecycle.startup = AsyncMock()
        mock_init.return_value = mock_lifecycle
        
        with patch('app.agents.refactored_agent_sdk.Runner') as mock_runner:
            # Create a mock streaming result
            async def mock_stream():
                # Simulate streaming events
                event1 = MagicMock()
                event1.event_type = "message"
                event1.data.content = "Witam, "
                yield event1
                
                event2 = MagicMock()
                event2.event_type = "message"
                event2.data.content = "jak mogę pomóc?"
                yield event2
                
                event3 = MagicMock()
                event3.event_type = "completion"
                yield event3
            
            mock_result = mock_stream()
            mock_runner.run = AsyncMock(return_value=mock_result)
            
            await agent.initialize()
            
            # Collect streamed events
            events = []
            async for event in agent.process_message_stream("Cześć"):
                events.append(event)
            
            # Verify events
            assert len(events) >= 3
            assert any(e["type"] == "text_delta" for e in events)
            assert any(e["type"] == "message_complete" for e in events)
            assert any(e["type"] == "stream_complete" for e in events) 
