"""
Streaming handler for OpenAI Responses API.
Separates streaming protocol handling from business logic.
"""
from typing import List, Dict, Any, Optional, Protocol, AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
import logging
import json
from openai.types.responses import (
    ResponseStreamEvent,
    ResponseFunctionToolCall,
    ResponseCreatedEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
    ResponseCompletedEvent,
    ResponseOutputMessage
)

logger = logging.getLogger(__name__)


class StreamEventType(Enum):
    """Types of streaming events"""
    CREATED = "created"
    TEXT_DELTA = "text_delta"
    TEXT_COMPLETE = "text_complete"
    MESSAGE_COMPLETE = "message_complete"
    TOOL_CALL = "tool_call"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class StreamEvent:
    """Parsed streaming event"""
    type: StreamEventType
    content: Optional[str] = None
    thread_id: Optional[str] = None
    tool_calls: List[ResponseFunctionToolCall] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class StreamProcessor(Protocol):
    """Protocol for custom stream processors"""
    
    def process_event(self, event: StreamEvent) -> Optional[StreamEvent]:
        """Process a stream event, optionally transforming it"""
        ...


class StreamingHandler:
    """
    Handles OpenAI streaming responses with support for middleware.
    Separates protocol handling from business logic.
    """
    
    def __init__(self):
        self._processors: List[StreamProcessor] = []
        self._accumulated_text = ""
        self._current_message_id = None
        logger.info("StreamingHandler initialized")
    
    def add_processor(self, processor: StreamProcessor):
        """Add a stream processor for custom handling"""
        self._processors.append(processor)
    
    def parse_chunk(self, chunk: ResponseStreamEvent) -> Optional[StreamEvent]:
        """Parse a streaming chunk into a structured event"""
        try:
            if chunk.type == "response.created":
                event = ResponseCreatedEvent.model_validate(chunk)
                return StreamEvent(
                    type=StreamEventType.CREATED,
                    thread_id=event.response.id,
                    metadata={"created_at": chunk.created_at}
                )
            
            elif chunk.type == "response.output_item.added":
                event = ResponseOutputItemAddedEvent.model_validate(chunk)
                if event.item.type == "message":
                    message = ResponseOutputMessage.model_validate(event.item)
                    self._current_message_id = event.item.id
                    content = "".join([c.text for c in message.content])
                    return StreamEvent(
                        type=StreamEventType.TEXT_COMPLETE,
                        content=content,
                        metadata={"message_id": self._current_message_id}
                    )
            
            elif chunk.type == "response.output_item.done":
                event = ResponseOutputItemDoneEvent.model_validate(chunk)
                item = event.item
                
                if item.type == "message":
                    message = ResponseOutputMessage.model_validate(item)
                    content = "".join([c.text for c in message.content])
                    return StreamEvent(
                        type=StreamEventType.MESSAGE_COMPLETE,
                        content=content,
                        metadata={"message_id": item.id}
                    )
                
                elif item.type == "function_call":
                    tool_call = ResponseFunctionToolCall.model_validate(item)
                    logger.info(f"Tool call detected: {tool_call.name}")
                    return StreamEvent(
                        type=StreamEventType.TOOL_CALL,
                        tool_calls=[tool_call],
                        metadata={"call_id": tool_call.call_id}
                    )
            
            elif chunk.type == "response.output_text.delta":
                event = ResponseTextDeltaEvent.model_validate(chunk)
                self._accumulated_text += event.delta
                return StreamEvent(
                    type=StreamEventType.TEXT_DELTA,
                    content=event.delta,
                    metadata={"accumulated_length": len(self._accumulated_text)}
                )
            
            elif chunk.type == "response.output_text.done":
                event = ResponseTextDoneEvent.model_validate(chunk)
                return StreamEvent(
                    type=StreamEventType.TEXT_COMPLETE,
                    content=event.text,
                    metadata={"final_text": True}
                )
            
            elif chunk.type == "response.completed":
                event = ResponseCompletedEvent.model_validate(chunk)
                return StreamEvent(
                    type=StreamEventType.COMPLETED,
                    thread_id=event.response.id,
                    metadata={
                        "usage": event.response.usage.model_dump() if event.response.usage else None,
                        "status": event.response.status
                    }
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error parsing chunk: {e}")
            return StreamEvent(
                type=StreamEventType.ERROR,
                metadata={"error": str(e), "chunk_type": chunk.type}
            )
    
    async def process_stream(self, stream: AsyncIterator[ResponseStreamEvent]) -> AsyncIterator[StreamEvent]:
        """Process a stream of chunks into structured events"""
        tool_calls_buffer = []
        
        async for chunk in stream:
            event = self.parse_chunk(chunk)
            
            if event:
                # Apply processors
                for processor in self._processors:
                    event = processor.process_event(event)
                    if event is None:
                        break
                
                if event:
                    # Buffer tool calls
                    if event.type == StreamEventType.TOOL_CALL:
                        tool_calls_buffer.extend(event.tool_calls)
                    else:
                        # Yield buffered tool calls before other events
                        if tool_calls_buffer and event.type in [StreamEventType.MESSAGE_COMPLETE, StreamEventType.COMPLETED]:
                            yield StreamEvent(
                                type=StreamEventType.TOOL_CALL,
                                tool_calls=tool_calls_buffer,
                                metadata={"count": len(tool_calls_buffer)}
                            )
                            tool_calls_buffer = []
                        
                        yield event
        
        # Yield any remaining tool calls
        if tool_calls_buffer:
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL,
                tool_calls=tool_calls_buffer,
                metadata={"count": len(tool_calls_buffer), "final": True}
            )
    
    def reset(self):
        """Reset handler state"""
        self._accumulated_text = ""
        self._current_message_id = None


class ContentAccumulator(StreamProcessor):
    """Processor that accumulates content"""
    
    def __init__(self):
        self.content = ""
    
    def process_event(self, event: StreamEvent) -> Optional[StreamEvent]:
        if event.type == StreamEventType.TEXT_DELTA and event.content:
            self.content += event.content
        elif event.type in [StreamEventType.TEXT_COMPLETE, StreamEventType.MESSAGE_COMPLETE] and event.content:
            self.content = event.content
        return event
    
    def get_content(self) -> str:
        return self.content
    
    def reset(self):
        self.content = ""


class MetricsCollector(StreamProcessor):
    """Processor that collects streaming metrics"""
    
    def __init__(self):
        self.metrics = {
            "chunks_received": 0,
            "text_deltas": 0,
            "tool_calls": 0,
            "errors": 0,
            "total_content_length": 0
        }
    
    def process_event(self, event: StreamEvent) -> Optional[StreamEvent]:
        self.metrics["chunks_received"] += 1
        
        if event.type == StreamEventType.TEXT_DELTA:
            self.metrics["text_deltas"] += 1
            if event.content:
                self.metrics["total_content_length"] += len(event.content)
        elif event.type == StreamEventType.TOOL_CALL:
            self.metrics["tool_calls"] += len(event.tool_calls)
        elif event.type == StreamEventType.ERROR:
            self.metrics["errors"] += 1
        
        return event
    
    def get_metrics(self) -> Dict[str, Any]:
        return self.metrics.copy()
    
    def reset(self):
        self.metrics = {
            "chunks_received": 0,
            "text_deltas": 0,
            "tool_calls": 0,
            "errors": 0,
            "total_content_length": 0
        }