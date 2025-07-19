"""
Integration tests for the refactored AI Paralegal system.
Tests the complete flow with all components working together.
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
import json

from app.core import (
    get_config,
    service_container,
    ServiceLifecycleManager
)
from app.core.logger_manager import setup_structured_logging, correlation_context
from app.services import initialize_services
from app.orchestrator_refactored import RefactoredParalegalAgent


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_services():
    """Initialize services for testing"""
    # Configure logging for tests
    setup_structured_logging(level="DEBUG", json_format=False)
    
    # Mock external services
    with patch('app.core.database_manager.create_async_engine') as mock_engine, \
         patch('qdrant_client.QdrantClient') as mock_qdrant, \
         patch('redis.asyncio.from_url') as mock_redis:
        
        # Configure mocks
        mock_engine.return_value = Mock()
        mock_qdrant.return_value = AsyncMock()
        mock_redis.return_value = AsyncMock()
        
        # Initialize services
        lifecycle_manager = initialize_services()
        await lifecycle_manager.startup()
        
        yield lifecycle_manager
        
        # Cleanup
        await lifecycle_manager.shutdown()


@pytest.fixture
async def test_agent(test_services):
    """Create test agent instance"""
    agent = RefactoredParalegalAgent()
    
    # Mock OpenAI client
    mock_client = AsyncMock()
    agent._client = mock_client
    
    # Mock tool schemas
    agent._tool_schemas = [
        {
            "type": "function",
            "function": {
                "name": "search_statute",
                "description": "Search Polish civil law statutes",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"}
                    },
                    "required": ["query"]
                }
            }
        }
    ]
    
    agent._initialized = True
    
    yield agent
    
    await agent.shutdown()


class TestRefactoredIntegration:
    """Integration tests for refactored system"""
    
    async def test_end_to_end_chat_flow(self, test_agent):
        """Test complete chat flow with tool execution"""
        # Mock streaming response
        mock_chunks = [
            Mock(type="response.created", response=Mock(id="resp-123")),
            Mock(type="response.output_text.delta", delta="Sprawdzę "),
            Mock(type="response.output_text.delta", delta="przepisy "),
            Mock(type="response.output_item.done", item=Mock(
                type="function_call",
                name="search_statute",
                arguments='{"query": "art. 415 KC"}',
                call_id="call-123"
            )),
            Mock(type="response.completed", response=Mock(
                id="resp-123",
                usage=Mock(total_tokens=100),
                status="completed"
            ))
        ]
        
        # Mock tool execution result
        with patch('app.core.tool_executor.ToolExecutor.execute_tool') as mock_execute:
            mock_execute.return_value = [
                {
                    "article": "415",
                    "text": "Kto z winy swej wyrządził drugiemu szkodę...",
                    "citation": "art. 415 KC"
                }
            ]
            
            # Mock continuation response
            mock_continuation = [
                Mock(type="response.output_text.delta", delta="Zgodnie z "),
                Mock(type="response.output_text.delta", delta="art. 415 KC..."),
                Mock(type="response.output_item.done", item=Mock(
                    type="message",
                    content=[Mock(text="Zgodnie z art. 415 KC...")]
                )),
                Mock(type="response.completed", response=Mock(
                    id="resp-124",
                    usage=Mock(total_tokens=150),
                    status="completed"
                ))
            ]
            
            # Configure mock to return different responses
            test_agent._client.responses.create = AsyncMock()
            test_agent._client.responses.create.side_effect = [
                AsyncMock(__aiter__=lambda self: iter(mock_chunks)),
                AsyncMock(__aiter__=lambda self: iter(mock_continuation))
            ]
            
            # Process message
            chunks_received = []
            with correlation_context() as correlation_id:
                async for chunk in test_agent.process_message_stream(
                    user_message="Co mówi art. 415 KC?",
                    user_id="test-user"
                ):
                    chunks_received.append(chunk)
            
            # Assertions
            assert len(chunks_received) > 0
            
            # Check stream start
            assert chunks_received[0]["type"] == "stream_start"
            
            # Check tool execution
            tool_chunks = [c for c in chunks_received if c["type"] == "tool_calls"]
            assert len(tool_chunks) == 1
            assert tool_chunks[0]["tools"][0]["name"] == "search_statute"
            
            # Check final message
            message_chunks = [c for c in chunks_received if c["type"] == "message_complete"]
            assert len(message_chunks) > 0
            assert "art. 415 KC" in message_chunks[-1]["content"]
            
            # Verify tool was called
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args[0]
            assert call_args[0] == "search_statute"
            assert call_args[1]["query"] == "art. 415 KC"
    
    async def test_conversation_persistence(self, test_agent):
        """Test conversation state persistence"""
        conversation_id = "test-conv-123"
        
        # Mock response
        mock_chunks = [
            Mock(type="response.created", response=Mock(id="resp-123")),
            Mock(type="response.output_item.done", item=Mock(
                type="message",
                content=[Mock(text="Test response")]
            )),
            Mock(type="response.completed", response=Mock(
                id="resp-123",
                usage=Mock(total_tokens=50),
                status="completed"
            ))
        ]
        
        test_agent._client.responses.create = AsyncMock(
            return_value=AsyncMock(__aiter__=lambda self: iter(mock_chunks))
        )
        
        # First message
        async for _ in test_agent.process_message_stream(
            user_message="First message",
            thread_id=conversation_id
        ):
            pass
        
        # Check conversation state
        conv_manager = service_container.get("ConversationManager")
        state = await conv_manager.get_or_create_conversation(conversation_id)
        assert state.last_response_id == "resp-123"
        
        # Second message should include history
        test_agent._client.responses.create.reset_mock()
        
        async for _ in test_agent.process_message_stream(
            user_message="Second message",
            thread_id=conversation_id
        ):
            pass
        
        # Verify history was included
        call_args = test_agent._client.responses.create.call_args[1]
        assert call_args["previous_response_id"] == "resp-123"
    
    async def test_circuit_breaker_integration(self, test_agent):
        """Test circuit breaker behavior"""
        from app.core.exceptions import ServiceUnavailableError
        
        # Configure tool to fail
        with patch('app.core.tool_registry.ToolRegistry.execute_tool') as mock_execute:
            mock_execute.side_effect = Exception("Tool failure")
            
            # Mock response with tool call
            mock_chunks = [
                Mock(type="response.created", response=Mock(id="resp-123")),
                Mock(type="response.output_item.done", item=Mock(
                    type="function_call",
                    name="search_statute",
                    arguments='{"query": "test"}',
                    call_id="call-123"
                )),
                Mock(type="response.completed", response=Mock(
                    id="resp-123",
                    usage=Mock(total_tokens=50),
                    status="completed"
                ))
            ]
            
            test_agent._client.responses.create = AsyncMock(
                return_value=AsyncMock(__aiter__=lambda self: iter(mock_chunks))
            )
            
            # Process multiple messages to trip circuit breaker
            for i in range(5):
                try:
                    async for chunk in test_agent.process_message_stream(
                        user_message=f"Test message {i}"
                    ):
                        if chunk["type"] == "error":
                            break
                except:
                    pass
            
            # Circuit should be open now
            tool_executor = service_container.get("ToolExecutor")
            metrics = tool_executor.get_metrics("search_statute")
            assert metrics["state"] == "open"
            
            # Next call should fail immediately
            with pytest.raises(ServiceUnavailableError):
                await tool_executor.execute_tool("search_statute", {"query": "test"})
    
    async def test_health_check_integration(self, test_services):
        """Test health check across all services"""
        health_status = await test_services.check_health()
        
        assert health_status["healthy"] is True
        assert len(health_status["services"]) > 0
        
        # Check specific services
        service_names = [s["name"] for s in health_status["services"]]
        assert "DatabaseManager" in service_names
        assert "ConversationManager" in service_names
        assert "ToolExecutor" in service_names
        assert "StatuteSearchService" in service_names
    
    async def test_metrics_collection(self, test_agent):
        """Test metrics collection during stream processing"""
        # Mock simple response
        mock_chunks = [
            Mock(type="response.created", response=Mock(id="resp-123")),
            Mock(type="response.output_text.delta", delta="Test "),
            Mock(type="response.output_text.delta", delta="response"),
            Mock(type="response.output_item.done", item=Mock(
                type="message",
                content=[Mock(text="Test response")]
            )),
            Mock(type="response.completed", response=Mock(
                id="resp-123",
                usage=Mock(total_tokens=10),
                status="completed"
            ))
        ]
        
        test_agent._client.responses.create = AsyncMock(
            return_value=AsyncMock(__aiter__=lambda self: iter(mock_chunks))
        )
        
        # Process message
        final_metrics = None
        async for chunk in test_agent.process_message_stream("Test"):
            if chunk["type"] == "stream_complete":
                final_metrics = chunk["metrics"]
        
        # Verify metrics
        assert final_metrics is not None
        assert final_metrics["chunks_received"] == 5
        assert final_metrics["text_deltas"] == 2
        assert final_metrics["total_content_length"] == 13  # "Test response"


class TestServiceOrchestration:
    """Test service dependency and lifecycle management"""
    
    async def test_service_initialization_order(self):
        """Test that services initialize in correct order"""
        init_order = []
        
        # Patch initialize methods to track order
        with patch('app.core.database_manager.DatabaseManager.initialize') as mock_db_init, \
             patch('app.services.statute_search_service.StatuteSearchService.initialize') as mock_search_init:
            
            mock_db_init.side_effect = lambda: init_order.append("DatabaseManager")
            mock_search_init.side_effect = lambda: init_order.append("StatuteSearchService")
            
            lifecycle_manager = initialize_services()
            await lifecycle_manager.startup()
            
            # Database should initialize before services that depend on it
            assert init_order.index("DatabaseManager") < init_order.index("StatuteSearchService")
            
            await lifecycle_manager.shutdown()
    
    async def test_graceful_shutdown(self, test_services):
        """Test graceful shutdown of services"""
        # Track shutdown calls
        shutdown_order = []
        
        for service_info in test_services._services:
            original_shutdown = service_info["instance"].shutdown
            
            async def tracked_shutdown(name=service_info["name"]):
                shutdown_order.append(name)
                await original_shutdown()
            
            service_info["instance"].shutdown = tracked_shutdown
        
        # Shutdown
        await test_services.shutdown()
        
        # Verify all services shut down
        assert len(shutdown_order) > 0
        
        # Services should shutdown in reverse order of initialization
        # (dependencies shut down before dependents)
        assert "StatuteSearchService" in shutdown_order
        assert "DatabaseManager" in shutdown_order


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])
