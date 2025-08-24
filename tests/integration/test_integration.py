"""
Comprehensive integration tests for the AI Paralegal system.
Tests end-to-end workflows and service interactions.
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
import json

from app.core import (
    service_container,
    ServiceContainer,
    initialize_services,
    get_config
)
from app.core.database_manager import DatabaseManager
from app.core.tool_executor import ToolExecutor, CircuitState
from app.core.conversation_manager import ConversationManager
from app.core.streaming_handler import StreamingHandler, StreamEventType, StreamEvent
from app.orchestrator_refactored import RefactoredParalegalAgent
from app.core.service_interface import ServiceStatus
from app.services import StatuteSearchService, DocumentGenerationService
from openai.types.responses import ResponseStreamEvent


@pytest.fixture
def mock_config():
    """Mock configuration for integration tests"""
    config = Mock()
    config.openai.api_key.get_secret_value.return_value = "test-key"
    config.openai.orchestrator_model = "gpt-4"
    config.postgres.async_url = "postgresql+asyncpg://test:test@localhost/test"
    config.redis.url = "redis://localhost:6379/0"
    config.qdrant.host = "localhost"
    config.qdrant.port = 6333
    config.qdrant.collection_statutes = "test_statutes"
    return config


@pytest.fixture
async def test_container():
    """Create test service container with mocked services"""
    container = ServiceContainer()
    
    # Create mock services
    mock_db = Mock(spec=DatabaseManager)
    mock_db._initialized = True
    mock_db.name = "DatabaseManager"
    
    mock_conv = Mock(spec=ConversationManager)
    mock_conv._initialized = True
    mock_conv.name = "ConversationManager"
    
    mock_executor = Mock(spec=ToolExecutor)
    mock_executor._initialized = True
    mock_executor.name = "ToolExecutor"
    
    # Register services
    container.register_singleton(DatabaseManager, mock_db)
    container.register_singleton(ConversationManager, mock_conv)
    container.register_singleton(ToolExecutor, mock_executor)
    
    return container


class TestServiceLifecycle:
    """Test service initialization and lifecycle management"""
    
    @pytest.mark.asyncio
    async def test_service_initialization_order(self, mock_config):
        """Test that services initialize in correct dependency order"""
        with patch('app.core.config_service.get_config', return_value=mock_config):
            # Track initialization order
            init_order = []
            
            # Mock service initialization
            async def mock_init(self):
                init_order.append(self.name)
                self._initialized = True
            
            with patch.object(DatabaseManager, 'initialize', mock_init), \
                 patch.object(ConversationManager, 'initialize', mock_init), \
                 patch.object(ToolExecutor, 'initialize', mock_init):
                
                # Initialize services
                lifecycle = initialize_services()
                await lifecycle.startup()
                
                # Verify order: DatabaseManager should initialize first
                assert init_order[0] == "DatabaseManager"
                assert "ConversationManager" in init_order
                assert "ToolExecutor" in init_order
    
    @pytest.mark.asyncio
    async def test_service_health_check_aggregation(self, test_container):
        """Test aggregated health check across all services"""
        # Set up mock health checks
        test_container.get_service(DatabaseManager).health_check = AsyncMock(
            return_value=Mock(status=ServiceStatus.HEALTHY, message="DB healthy")
        )
        test_container.get_service(ConversationManager).health_check = AsyncMock(
            return_value=Mock(status=ServiceStatus.HEALTHY, message="Conv healthy")
        )
        test_container.get_service(ToolExecutor).health_check = AsyncMock(
            return_value=Mock(status=ServiceStatus.DEGRADED, message="Some circuits open")
        )
        
        # Check overall health
        lifecycle = Mock()
        lifecycle._container = test_container
        
        health = await lifecycle.check_health()
        
        assert health["healthy"] is False  # Degraded service makes overall unhealthy
        assert len(health["services"]) == 3
        assert any(s["status"] == "degraded" for s in health["services"])
    
    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, test_container):
        """Test graceful shutdown of all services"""
        shutdown_order = []
        
        # Mock shutdown
        for service_type in [DatabaseManager, ConversationManager, ToolExecutor]:
            service = test_container.get_service(service_type)
            
            async def make_shutdown(name):
                async def shutdown():
                    shutdown_order.append(name)
                return shutdown
            
            service.shutdown = await make_shutdown(service.name)
        
        # Shutdown services
        lifecycle = Mock()
        lifecycle._container = test_container
        
        for service in test_container._singletons.values():
            await service.shutdown()
        
        # All services should shutdown
        assert len(shutdown_order) == 3
        assert all(name in shutdown_order for name in ["DatabaseManager", "ConversationManager", "ToolExecutor"])


class TestEndToEndWorkflow:
    """Test complete workflows through the system"""
    
    @pytest.mark.asyncio
    async def test_chat_request_with_tool_execution(self, mock_config):
        """Test complete chat request with tool execution"""
        with patch('app.orchestrator_refactored.get_config', return_value=mock_config):
            agent = RefactoredParalegalAgent()
            
            # Mock dependencies
            agent._db_manager = Mock()
            agent._conversation_manager = Mock()
            agent._tool_executor = Mock()
            agent._initialized = True
            
            # Mock conversation state
            conv_state = Mock()
            conv_state.conversation_id = "conv_123"
            conv_state.last_response_id = None
            conv_state.case_id = None
            conv_state.user_id = "user_123"
            
            conv_context = AsyncMock()
            conv_context.__aenter__ = AsyncMock(return_value=conv_state)
            conv_context.__aexit__ = AsyncMock(return_value=None)
            agent._conversation_manager.conversation_context = Mock(return_value=conv_context)
            
            # Mock conversation history
            agent._conversation_manager.get_conversation_history = AsyncMock(return_value=[])
            
            # Mock OpenAI client response
            mock_response = AsyncMock()
            
            # Create streaming events
            events = [
                Mock(type="response.created", response=Mock(id="resp_123")),
                Mock(type="response.output_text.delta", delta="Zgodnie z "),
                Mock(type="response.output_text.delta", delta="art. 415 KC"),
                Mock(type="response.output_item.done", item=Mock(
                    type="function_call",
                    name="search_statute",
                    call_id="call_123",
                    arguments={"query": "art. 415 KC"}
                )),
                Mock(type="response.completed", response=Mock(
                    id="resp_123",
                    status="completed",
                    usage=Mock(model_dump=Mock(return_value={"total_tokens": 100}))
                ))
            ]
            
            # Make events async iterable
            async def event_generator():
                for event in events:
                    yield event
            
            mock_response.__aiter__ = event_generator
            agent._client.responses.create = AsyncMock(return_value=mock_response)
            
            # Mock tool execution
            agent._tool_executor.execute_tool = AsyncMock(return_value={
                "results": [{"article": "415", "text": "Kto z winy swej..."}]
            })
            
            # Mock conversation save
            agent._conversation_manager.save_conversation_turn = AsyncMock()
            
            # Process message
            events_received = []
            async for event in agent.process_message_stream(
                "Co mówi art. 415 KC?",
                thread_id="conv_123",
                user_id="user_123"
            ):
                events_received.append(event)
            
            # Verify flow
            assert len(events_received) > 0
            assert any(e["type"] == "stream_start" for e in events_received)
            assert any(e["type"] == "text_delta" for e in events_received)
            assert any(e["type"] == "tool_calls" for e in events_received)
            assert any(e["type"] == "stream_complete" for e in events_received)
            
            # Verify tool was executed
            agent._tool_executor.execute_tool.assert_called_once()
            call_args = agent._tool_executor.execute_tool.call_args
            assert call_args[0][0] == "search_statute"
            assert call_args[0][1]["query"] == "art. 415 KC"
    
    @pytest.mark.asyncio
    async def test_error_recovery_workflow(self, mock_config):
        """Test error recovery during request processing"""
        with patch('app.orchestrator_refactored.get_config', return_value=mock_config):
            agent = RefactoredParalegalAgent()
            
            # Set up mocks
            agent._initialized = True
            agent._tool_executor = Mock()
            
            # Make tool execution fail
            agent._tool_executor.execute_tool = AsyncMock(
                side_effect=Exception("Tool execution failed")
            )
            
            # Mock streaming handler
            agent._streaming_handler = StreamingHandler()
            
            # Process tool call event
            tool_event = StreamEvent(
                type=StreamEventType.TOOL_CALL,
                tool_calls=[Mock(
                    name="search_statute",
                    call_id="call_123",
                    arguments=json.dumps({"query": "test"})
                )]
            )
            
            # Execute tool should handle error gracefully
            tool_results = await agent._execute_tool_calls(tool_event.tool_calls)
            
            assert len(tool_results) == 1
            assert tool_results[0]["name"] == "search_statute"
            assert tool_results[0]["status"] == "error"
            assert "Tool execution failed" in tool_results[0]["error"]


class TestCircuitBreakerIntegration:
    """Test circuit breaker behavior in integrated system"""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_prevents_cascading_failures(self):
        """Test that circuit breaker prevents cascading failures"""
        executor = ToolExecutor()
        executor._initialized = True
        
        # Mock failing tool
        failing_tool = AsyncMock(side_effect=Exception("Service unavailable"))
        
        with patch('app.core.tool_registry.tool_registry.execute_tool', failing_tool):
            # Make multiple failing requests
            for i in range(5):
                try:
                    await executor.execute_tool("test_tool", {})
                except Exception:
                    pass
            
            # Circuit should be open
            cb = executor._circuit_breakers.get("test_tool")
            assert cb is not None
            assert cb.state == CircuitState.OPEN
            
            # Further requests should fail immediately
            with pytest.raises(Exception) as exc_info:
                await executor.execute_tool("test_tool", {})
            
            assert "currently unavailable" in str(exc_info.value)
            
            # Failing tool should not be called when circuit is open
            assert failing_tool.call_count == 5  # Not incremented


class TestStreamingIntegration:
    """Test streaming response handling"""
    
    @pytest.mark.asyncio
    async def test_streaming_with_multiple_processors(self):
        """Test streaming with multiple processors"""
        handler = StreamingHandler()
        
        # Add multiple processors
        processor1_events = []
        processor2_events = []
        
        class Processor1:
            def process_event(self, event):
                processor1_events.append(event)
                return event
        
        class Processor2:
            def process_event(self, event):
                processor2_events.append(event)
                # Transform text to uppercase
                if event.type == StreamEventType.TEXT_DELTA and event.content:
                    event.content = event.content.upper()
                return event
        
        handler.add_processor(Processor1())
        handler.add_processor(Processor2())
        
        # Create test chunks
        chunks = [
            Mock(type="response.output_text.delta", delta="hello"),
            Mock(type="response.output_text.delta", delta=" world"),
            Mock(type="response.completed", response=Mock(
                id="resp_123",
                status="completed",
                usage=None
            ))
        ]
        
        # Mock parsing
        handler.parse_chunk = Mock(side_effect=[
            StreamEvent(type=StreamEventType.TEXT_DELTA, content="hello"),
            StreamEvent(type=StreamEventType.TEXT_DELTA, content=" world"),
            StreamEvent(type=StreamEventType.COMPLETED)
        ])
        
        # Process stream
        events = []
        async for event in handler.process_stream(chunks):
            events.append(event)
        
        # Verify processing
        assert len(events) == 3
        assert len(processor1_events) == 3
        assert len(processor2_events) == 3
        
        # Verify transformation
        assert events[0].content == "HELLO"
        assert events[1].content == " WORLD"


class TestCacheIntegration:
    """Test caching behavior across services"""
    
    @pytest.mark.asyncio
    async def test_conversation_caching_workflow(self):
        """Test conversation caching between Redis and database"""
        db_manager = Mock()
        conv_manager = ConversationManager(db_manager)
        
        # Mock Redis available
        conv_manager._redis_client = AsyncMock()
        conv_manager._redis_client.get = AsyncMock(return_value=None)
        conv_manager._redis_client.setex = AsyncMock()
        
        # Mock database response
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        mock_history = Mock()
        mock_history.thread_id = "conv_123"
        mock_history.response_id = "resp_456"
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_history)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        db_manager.get_session.return_value = mock_session
        
        # First call - should hit database
        state1 = await conv_manager.get_or_create_conversation("conv_123")
        assert state1.conversation_id == "conv_123"
        assert mock_session.execute.called
        
        # Should save to cache
        assert conv_manager._redis_client.setex.called
        
        # Mock cache hit for second call
        cache_data = json.dumps(state1.to_dict())
        conv_manager._redis_client.get = AsyncMock(return_value=cache_data)
        
        # Second call - should hit cache
        mock_session.execute.reset_mock()
        state2 = await conv_manager.get_or_create_conversation("conv_123")
        
        assert state2.conversation_id == "conv_123"
        assert not mock_session.execute.called  # Database not queried


class TestPerformanceOptimization:
    """Test performance optimization features"""
    
    @pytest.mark.asyncio
    async def test_batch_embedding_generation(self):
        """Test batch processing of embeddings"""
        from app.core.performance_utils import EmbeddingBatcher
        
        mock_embedder = Mock()
        call_count = 0
        batch_sizes = []
        
        async def mock_embed(texts):
            nonlocal call_count
            call_count += 1
            batch_sizes.append(len(texts))
            return [[0.1 * i, 0.2 * i] for i in range(len(texts))]
        
        mock_embedder.aembed_documents = mock_embed
        
        batcher = EmbeddingBatcher(mock_embedder, batch_size=3)
        await batcher.start()
        
        try:
            # Generate multiple embeddings quickly
            tasks = []
            for i in range(5):
                task = batcher.get_embedding(f"text {i}")
                tasks.append(task)
            
            embeddings = await asyncio.gather(*tasks)
            
            # Should batch efficiently
            assert call_count <= 2  # At most 2 batches for 5 items with batch_size=3
            assert sum(batch_sizes) == 5
            assert len(embeddings) == 5
            
        finally:
            await batcher.stop()
    
    @pytest.mark.asyncio
    async def test_query_result_caching(self):
        """Test query result caching across multiple requests"""
        from app.core.performance_utils import cached_query
        
        call_count = 0
        
        @cached_query(ttl=timedelta(seconds=10))
        async def expensive_search(query: str, limit: int = 10):
            nonlocal call_count
            call_count += 1
            return [f"Result {i} for {query}" for i in range(limit)]
        
        # First call
        results1 = await expensive_search("test query", 5)
        assert len(results1) == 5
        assert call_count == 1
        
        # Second call with same parameters - should use cache
        results2 = await expensive_search("test query", 5)
        assert results2 == results1
        assert call_count == 1  # Not incremented
        
        # Different parameters - should execute
        results3 = await expensive_search("different query", 5)
        assert len(results3) == 5
        assert call_count == 2


class TestErrorPropagation:
    """Test error propagation through the system"""
    
    @pytest.mark.asyncio
    async def test_database_error_propagation(self, mock_config):
        """Test that database errors propagate correctly"""
        with patch('app.orchestrator_refactored.get_config', return_value=mock_config):
            agent = RefactoredParalegalAgent()
            
            # Mock database error
            agent._conversation_manager = Mock()
            agent._conversation_manager.conversation_context = Mock(
                side_effect=Exception("Database connection failed")
            )
            
            # Should propagate as user-friendly error
            events = []
            async for event in agent.process_message_stream("Test message"):
                events.append(event)
            
            # Should have error event
            error_events = [e for e in events if e.get("type") == "error"]
            assert len(error_events) > 0
            assert "błąd" in error_events[0]["error"].lower()  # Polish error message
    
    @pytest.mark.asyncio
    async def test_openai_error_handling(self, mock_config):
        """Test handling of OpenAI API errors"""
        with patch('app.orchestrator_refactored.get_config', return_value=mock_config):
            agent = RefactoredParalegalAgent()
            agent._initialized = True
            
            # Mock conversation setup
            conv_state = Mock()
            conv_context = AsyncMock()
            conv_context.__aenter__ = AsyncMock(return_value=conv_state)
            conv_context.__aexit__ = AsyncMock(return_value=None)
            agent._conversation_manager = Mock()
            agent._conversation_manager.conversation_context = Mock(return_value=conv_context)
            agent._conversation_manager.get_conversation_history = AsyncMock(return_value=[])
            
            # Mock OpenAI error
            from openai import RateLimitError
            agent._client.responses.create = AsyncMock(
                side_effect=RateLimitError("Rate limit exceeded")
            )
            
            # Should handle gracefully
            events = []
            async for event in agent.process_message_stream("Test"):
                events.append(event)
            
            assert any(e.get("type") == "error" for e in events)


class TestConcurrentRequests:
    """Test handling of concurrent requests"""
    
    @pytest.mark.asyncio
    async def test_concurrent_conversation_handling(self, mock_config):
        """Test multiple concurrent conversations"""
        with patch('app.orchestrator_refactored.get_config', return_value=mock_config):
            agent = RefactoredParalegalAgent()
            agent._initialized = True
            
            # Mock dependencies for concurrent access
            agent._conversation_manager = Mock()
            agent._tool_executor = Mock()
            
            # Track conversation IDs
            processed_conversations = []
            
            async def mock_context(conv_id):
                conv_state = Mock()
                conv_state.conversation_id = conv_id
                context = AsyncMock()
                context.__aenter__ = AsyncMock(return_value=conv_state)
                context.__aexit__ = AsyncMock(return_value=None)
                processed_conversations.append(conv_id)
                return context
            
            agent._conversation_manager.conversation_context = mock_context
            agent._conversation_manager.get_conversation_history = AsyncMock(return_value=[])
            agent._conversation_manager.save_conversation_turn = AsyncMock()
            
            # Mock simple OpenAI response
            async def mock_response():
                yield Mock(type="response.created", response=Mock(id="resp_123"))
                yield Mock(type="response.completed", response=Mock(
                    id="resp_123",
                    status="completed",
                    usage=None
                ))
            
            agent._client.responses.create = AsyncMock(return_value=mock_response())
            
            # Process multiple conversations concurrently
            async def process_conversation(conv_id):
                events = []
                async for event in agent.process_message_stream(
                    f"Message for {conv_id}",
                    thread_id=conv_id
                ):
                    events.append(event)
                return conv_id, len(events)
            
            # Run concurrent conversations
            tasks = [process_conversation(f"conv_{i}") for i in range(5)]
            results = await asyncio.gather(*tasks)
            
            # All conversations should process
            assert len(results) == 5
            assert all(len(events) > 0 for _, events in results)
            assert len(set(processed_conversations)) == 5