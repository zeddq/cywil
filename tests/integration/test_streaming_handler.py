"""
Comprehensive tests for StreamingHandler with OpenAI protocol parsing.
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
from typing import Optional, List

from app.core.streaming_handler import (
    StreamingHandler, StreamEventType, StreamEvent, StreamProcessor,
    MetricsCollector, TextAccumulator
)
from openai.types.responses import (
    ResponseStreamEvent,
    ResponseCreatedEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
    ResponseCompletedEvent,
    ResponseOutputMessage,
    ResponseFunctionToolCall
)


@pytest.fixture
def streaming_handler():
    """Create StreamingHandler instance"""
    handler = StreamingHandler()
    return handler


class MockStreamProcessor(StreamProcessor):
    """Mock stream processor for testing"""
    def __init__(self):
        self.events_processed = []
        self.transform = None  # type: ignore[assignment]
    
    def process_event(self, event: StreamEvent) -> Optional[StreamEvent]:
        self.events_processed.append(event)
        if self.transform:
            return self.transform(event)
        return event


class TestStreamingHandlerInitialization:
    """Test StreamingHandler initialization"""
    
    def test_initialization(self, streaming_handler):
        """Test handler initializes correctly"""
        assert streaming_handler._processors == []
        assert streaming_handler._accumulated_text == ""
        assert streaming_handler._current_message_id is None
    
    def test_add_processor(self, streaming_handler):
        """Test adding stream processors"""
        processor1 = MockStreamProcessor()
        processor2 = MockStreamProcessor()
        
        streaming_handler.add_processor(processor1)
        streaming_handler.add_processor(processor2)
        
        assert len(streaming_handler._processors) == 2
        assert streaming_handler._processors[0] == processor1
        assert streaming_handler._processors[1] == processor2


class TestEventParsing:
    """Test parsing of different OpenAI streaming events"""
    
    def test_parse_response_created(self, streaming_handler):
        """Test parsing response.created event"""
        chunk = Mock(spec=ResponseStreamEvent)
        chunk.type = "response.created"
        chunk.created_at = 123456789
        
        # Mock the response object
        response = Mock()
        response.id = "resp_123"
        
        event_data = Mock()
        event_data.response = response
        
        with patch('app.core.streaming_handler.ResponseCreatedEvent.model_validate', return_value=event_data):
            event = streaming_handler.parse_chunk(chunk)
            
            assert event.type == StreamEventType.CREATED
            assert event.thread_id == "resp_123"
            assert event.metadata["created_at"] == 123456789
    
    def test_parse_output_item_added_message(self, streaming_handler):
        """Test parsing response.output_item.added for message"""
        chunk = Mock(spec=ResponseStreamEvent)
        chunk.type = "response.output_item.added"
        
        # Mock message item
        message = Mock(spec=ResponseOutputMessage)
        message.content = [Mock(text="Hello"), Mock(text=" world")]
        
        item = Mock()
        item.type = "message"
        item.id = "msg_123"
        
        event_data = Mock()
        event_data.item = item
        
        with patch('app.core.streaming_handler.ResponseOutputItemAddedEvent.model_validate', return_value=event_data), \
             patch('app.core.streaming_handler.ResponseOutputMessage.model_validate', return_value=message):
            
            event = streaming_handler.parse_chunk(chunk)
            
            assert event.type == StreamEventType.TEXT_COMPLETE
            assert event.content == "Hello world"
            assert event.metadata["message_id"] == "msg_123"
            assert streaming_handler._current_message_id == "msg_123"
    
    def test_parse_output_item_done_function_call(self, streaming_handler):
        """Test parsing response.output_item.done for function call"""
        chunk = Mock(spec=ResponseStreamEvent)
        chunk.type = "response.output_item.done"
        
        # Mock function call item
        tool_call = Mock(spec=ResponseFunctionToolCall)
        tool_call.name = "search_statute"
        tool_call.call_id = "call_123"
        tool_call.arguments = {"query": "art. 415 KC"}
        
        item = Mock()
        item.type = "function_call"
        
        event_data = Mock()
        event_data.item = item
        
        with patch('app.core.streaming_handler.ResponseOutputItemDoneEvent.model_validate', return_value=event_data), \
             patch('app.core.streaming_handler.ResponseFunctionToolCall.model_validate', return_value=tool_call):
            
            event = streaming_handler.parse_chunk(chunk)
            
            assert event.type == StreamEventType.TOOL_CALL
            assert len(event.tool_calls) == 1
            assert event.tool_calls[0].name == "search_statute"
            assert event.metadata["call_id"] == "call_123"
    
    def test_parse_text_delta(self, streaming_handler):
        """Test parsing response.output_text.delta"""
        chunk = Mock(spec=ResponseStreamEvent)
        chunk.type = "response.output_text.delta"
        
        event_data = Mock()
        event_data.delta = "Hello "
        
        with patch('app.core.streaming_handler.ResponseTextDeltaEvent.model_validate', return_value=event_data):
            event = streaming_handler.parse_chunk(chunk)
            
            assert event.type == StreamEventType.TEXT_DELTA
            assert event.content == "Hello "
            assert streaming_handler._accumulated_text == "Hello "
            assert event.metadata["accumulated_length"] == 6
    
    def test_parse_text_done(self, streaming_handler):
        """Test parsing response.output_text.done"""
        chunk = Mock(spec=ResponseStreamEvent)
        chunk.type = "response.output_text.done"
        
        event_data = Mock()
        event_data.text = "Complete message"
        
        with patch('app.core.streaming_handler.ResponseTextDoneEvent.model_validate', return_value=event_data):
            event = streaming_handler.parse_chunk(chunk)
            
            assert event.type == StreamEventType.TEXT_COMPLETE
            assert event.content == "Complete message"
            assert event.metadata["final_text"] is True
    
    def test_parse_completed(self, streaming_handler):
        """Test parsing response.completed"""
        chunk = Mock(spec=ResponseStreamEvent)
        chunk.type = "response.completed"
        
        # Mock usage data
        usage = Mock()
        usage.model_dump.return_value = {"total_tokens": 100, "prompt_tokens": 50}
        
        response = Mock()
        response.id = "resp_123"
        response.usage = usage
        response.status = "completed"
        
        event_data = Mock()
        event_data.response = response
        
        with patch('app.core.streaming_handler.ResponseCompletedEvent.model_validate', return_value=event_data):
            event = streaming_handler.parse_chunk(chunk)
            
            assert event.type == StreamEventType.COMPLETED
            assert event.thread_id == "resp_123"
            assert event.metadata["usage"]["total_tokens"] == 100
            assert event.metadata["status"] == "completed"
    
    def test_parse_unknown_event(self, streaming_handler):
        """Test parsing unknown event type"""
        chunk = Mock(spec=ResponseStreamEvent)
        chunk.type = "unknown.event.type"
        
        event = streaming_handler.parse_chunk(chunk)
        
        assert event is None
    
    def test_parse_error_handling(self, streaming_handler):
        """Test error handling during parsing"""
        chunk = Mock(spec=ResponseStreamEvent)
        chunk.type = "response.created"
        
        with patch('app.core.streaming_handler.ResponseCreatedEvent.model_validate', side_effect=Exception("Parse error")):
            event = streaming_handler.parse_chunk(chunk)
            
            assert event.type == StreamEventType.ERROR
            assert event.metadata["error"] == "Parse error"
            assert event.metadata["chunk_type"] == "response.created"


class TestTextAccumulation:
    """Test text accumulation across delta events"""
    
    def test_text_accumulation(self, streaming_handler):
        """Test accumulating text across multiple deltas"""
        # First delta
        chunk1 = Mock(spec=ResponseStreamEvent)
        chunk1.type = "response.output_text.delta"
        event_data1 = Mock()
        event_data1.delta = "Hello "
        
        with patch('app.core.streaming_handler.ResponseTextDeltaEvent.model_validate', return_value=event_data1):
            event1 = streaming_handler.parse_chunk(chunk1)
            assert streaming_handler._accumulated_text == "Hello "
        
        # Second delta
        chunk2 = Mock(spec=ResponseStreamEvent)
        chunk2.type = "response.output_text.delta"
        event_data2 = Mock()
        event_data2.delta = "world!"
        
        with patch('app.core.streaming_handler.ResponseTextDeltaEvent.model_validate', return_value=event_data2):
            event2 = streaming_handler.parse_chunk(chunk2)
            assert streaming_handler._accumulated_text == "Hello world!"
            assert event2.metadata["accumulated_length"] == 12
    
    def test_reset_functionality(self, streaming_handler):
        """Test reset clears accumulated state"""
        streaming_handler._accumulated_text = "Some text"
        streaming_handler._current_message_id = "msg_123"
        
        streaming_handler.reset()
        
        assert streaming_handler._accumulated_text == ""
        assert streaming_handler._current_message_id is None


class TestStreamProcessing:
    """Test stream processing with processors"""
    
    @pytest.mark.asyncio
    async def test_process_stream_with_processors(self, streaming_handler):
        """Test processing stream with multiple processors"""
        processor1 = MockStreamProcessor()
        processor2 = MockStreamProcessor()
        
        streaming_handler.add_processor(processor1)
        streaming_handler.add_processor(processor2)
        
        # Create test chunks
        chunks = []
        
        # Text delta chunk
        chunk1 = Mock(spec=ResponseStreamEvent)
        chunk1.type = "response.output_text.delta"
        chunks.append(chunk1)
        
        # Completed chunk
        chunk2 = Mock(spec=ResponseStreamEvent)
        chunk2.type = "response.completed"
        chunks.append(chunk2)
        
        # Mock parsing
        events = [
            StreamEvent(type=StreamEventType.TEXT_DELTA, content="Hello"),
            StreamEvent(type=StreamEventType.COMPLETED)
        ]
        
        parse_calls = 0
        def mock_parse(chunk):
            nonlocal parse_calls
            result = events[parse_calls]
            parse_calls += 1
            return result
        
        streaming_handler.parse_chunk = mock_parse
        
        # Process stream
        processed_events = []
        async for event in streaming_handler.process_stream(iter(chunks)):
            processed_events.append(event)
        
        assert len(processed_events) == 2
        assert processor1.events_processed == events
        assert processor2.events_processed == events
    
    @pytest.mark.asyncio
    async def test_processor_transformation(self, streaming_handler):
        """Test processor can transform events"""
        processor = MockStreamProcessor()
        
        # Transform text deltas to uppercase
        def transform(event: StreamEvent) -> StreamEvent:
            if event.type == StreamEventType.TEXT_DELTA and event.content:
                event.content = event.content.upper()
            return event
        
        processor.transform = transform
        streaming_handler.add_processor(processor)
        
        # Create test chunk
        chunk = Mock(spec=ResponseStreamEvent)
        chunk.type = "response.output_text.delta"
        
        # Mock parse to return lowercase text
        streaming_handler.parse_chunk = Mock(return_value=StreamEvent(
            type=StreamEventType.TEXT_DELTA,
            content="hello"
        ))
        
        # Process stream
        events = []
        async for event in streaming_handler.process_stream([chunk]):
            events.append(event)
        
        assert len(events) == 1
        assert events[0].content == "HELLO"
    
    @pytest.mark.asyncio
    async def test_processor_filtering(self, streaming_handler):
        """Test processor can filter events"""
        processor = MockStreamProcessor()
        
        # Filter out text deltas
        processor.process_event = lambda event: None if event.type == StreamEventType.TEXT_DELTA else event
        
        streaming_handler.add_processor(processor)
        
        # Create test events
        events = [
            StreamEvent(type=StreamEventType.TEXT_DELTA, content="Skip me"),
            StreamEvent(type=StreamEventType.COMPLETED),
            StreamEvent(type=StreamEventType.TEXT_DELTA, content="Skip me too"),
            StreamEvent(type=StreamEventType.TOOL_CALL)
        ]
        
        streaming_handler.parse_chunk = Mock(side_effect=events)
        
        # Process stream
        processed = []
        chunks = [Mock() for _ in range(4)]
        async for event in streaming_handler.process_stream(chunks):
            processed.append(event)
        
        assert len(processed) == 2
        assert processed[0].type == StreamEventType.COMPLETED
        assert processed[1].type == StreamEventType.TOOL_CALL


class TestMetricsCollector:
    """Test metrics collection processor"""
    
    def test_metrics_collector_initialization(self):
        """Test MetricsCollector initialization"""
        collector = MetricsCollector()
        
        assert collector.chunks_received == 0
        assert collector.events_by_type == {}
        assert collector.text_deltas == 0
        assert collector.tool_calls == 0
        assert collector.errors == 0
        assert collector.start_time is not None
    
    def test_metrics_collection(self):
        """Test metrics are collected correctly"""
        collector = MetricsCollector()
        
        # Process various events
        events = [
            StreamEvent(type=StreamEventType.CREATED),
            StreamEvent(type=StreamEventType.TEXT_DELTA),
            StreamEvent(type=StreamEventType.TEXT_DELTA),
            StreamEvent(type=StreamEventType.TOOL_CALL),
            StreamEvent(type=StreamEventType.ERROR),
            StreamEvent(type=StreamEventType.COMPLETED)
        ]
        
        for event in events:
            collector.process_event(event)
        
        collector.chunks_received = len(events)
        
        metrics = collector.get_metrics()
        
        assert metrics["chunks_received"] == 6
        assert metrics["text_deltas"] == 2
        assert metrics["tool_calls"] == 1
        assert metrics["errors"] == 1
        assert metrics["events_by_type"]["CREATED"] == 1
        assert metrics["events_by_type"]["COMPLETED"] == 1
        assert "duration_ms" in metrics
    
    def test_metrics_reset(self):
        """Test metrics can be reset"""
        collector = MetricsCollector()
        
        # Add some metrics
        collector.chunks_received = 10
        collector.text_deltas = 5
        collector.errors = 2
        
        collector.reset()
        
        assert collector.chunks_received == 0
        assert collector.text_deltas == 0
        assert collector.errors == 0
        assert collector.events_by_type == {}


class TestTextAccumulatorProcessor:
    """Test text accumulator processor"""
    
    def test_text_accumulator(self):
        """Test TextAccumulator processes text events"""
        accumulator = TextAccumulator()
        
        # Process text events
        events = [
            StreamEvent(type=StreamEventType.TEXT_DELTA, content="Hello "),
            StreamEvent(type=StreamEventType.TEXT_DELTA, content="world"),
            StreamEvent(type=StreamEventType.TEXT_COMPLETE, content="Hello world!"),
            StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, content="Final message")
        ]
        
        for event in events:
            accumulator.process_event(event)
        
        assert accumulator.accumulated_text == "Hello world"
        assert accumulator.complete_texts == ["Hello world!", "Final message"]
        assert accumulator.final_text == "Final message"
    
    def test_text_accumulator_reset(self):
        """Test TextAccumulator reset"""
        accumulator = TextAccumulator()
        
        accumulator.accumulated_text = "Some text"
        accumulator.complete_texts = ["Text 1", "Text 2"]
        accumulator.final_text = "Final"
        
        accumulator.reset()
        
        assert accumulator.accumulated_text == ""
        assert accumulator.complete_texts == []
        assert accumulator.final_text is None


class TestErrorScenarios:
    """Test error handling scenarios"""
    
    def test_malformed_chunk_handling(self, streaming_handler):
        """Test handling of malformed chunks"""
        # Chunk missing required attributes
        chunk = Mock()
        chunk.type = None
        
        event = streaming_handler.parse_chunk(chunk)
        
        assert event.type == StreamEventType.ERROR
        assert "Error parsing chunk" in event.metadata["error"]
    
    def test_processor_error_handling(self, streaming_handler):
        """Test handling of processor errors"""
        # Processor that raises exception
        class ErrorProcessor(StreamProcessor):
            def process_event(self, event: StreamEvent) -> Optional[StreamEvent]:
                raise Exception("Processor error")
        
        streaming_handler.add_processor(ErrorProcessor())
        
        # Should not propagate error
        chunk = Mock(spec=ResponseStreamEvent)
        chunk.type = "response.output_text.delta"
        
        streaming_handler.parse_chunk = Mock(return_value=StreamEvent(
            type=StreamEventType.TEXT_DELTA,
            content="Test"
        ))
        
        # Process should continue despite processor error
        events = []
        for event in streaming_handler.process_stream([chunk]):
            events.append(event)
        
        # Event should still be yielded
        assert len(events) == 1