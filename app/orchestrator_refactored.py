"""
DEPRECATED: This module is being replaced by app.agents.refactored_agent_sdk.ParalegalAgentSDK
which uses the OpenAI Agent SDK. Please migrate to the new implementation.

Refactored orchestrator using the new service architecture.
This demonstrates how to use all the refactored components together.
"""
from typing import List, Dict, Any, Optional, AsyncGenerator
import asyncio
import logging
from datetime import timedelta
from openai import AsyncOpenAI
from openai.types.responses import (
    ResponseStreamEvent, 
    ResponseFunctionToolCall
)
import json
import uuid

from .core import (
    get_config, 
    ToolExecutionError,
    ServiceError
)
from .core.streaming_handler import StreamingHandler, StreamEventType, MetricsCollector
from .core.conversation_manager import get_conversation_manager, ConversationManager
from .core.tool_executor import ToolExecutor, CircuitBreakerConfig, RetryConfig
from .services import get_tool_schemas
from .validator import recover_from_tool_error
from .core.database_manager import get_database_manager, DatabaseManager
from .core.service_interface import ServiceInterface, HealthCheckResult, ServiceStatus
from .core.config_service import ConfigService
from fastapi import Depends

logger = logging.getLogger(__name__)


class RefactoredParalegalAgent(ServiceInterface):
    """
    Refactored orchestrator using service architecture with proper separation of concerns.
    """
    
    def __init__(self, config_service: ConfigService):
        self._config = config_service.config
        self._client = AsyncOpenAI(api_key=self._config.openai.api_key.get_secret_value())
        
        # Initialize components with dependency injection
        self._tool_executor = ToolExecutor(config_service)
        
        # Add stream processors
        self._metrics_collector = MetricsCollector()
        
        self._tool_schemas = None
        self._initialized = False
        
        logger.info("Refactored Paralegal Agent created")

    async def _health_check_impl(self) -> HealthCheckResult:
        return HealthCheckResult(
            status=ServiceStatus.HEALTHY,
            message="Agent is healthy"
        )
    
    async def _initialize_impl(self) -> None:
        """Initialize the agent and all services"""
        pass
        
    async def _shutdown_impl(self) -> None:
        """Shutdown the agent and all services"""
        logger.info("Agent shutdown complete")
    
    async def initialize(self):
        """Initialize the agent and all services"""
        if self._initialized:
            return
        
        # Configure tool executor
        self._configure_tool_executor()
        
        # Get tool schemas
        self._tool_schemas = get_tool_schemas()
        
        self._initialized = True
        logger.info(f"Agent initialized with {len(self._tool_schemas)} tools")
    
    def _configure_tool_executor(self):
        """Configure tool executor with circuit breakers and middleware"""
        # Configure circuit breakers for critical tools
        critical_tools = ["search_statute", "draft_document", "compute_deadline"]
        for tool_name in critical_tools:
            self._tool_executor.configure_circuit_breaker(
                tool_name,
                CircuitBreakerConfig(
                    failure_threshold=3,  # More sensitive for critical tools
                    recovery_timeout=timedelta(seconds=30),
                    success_threshold=2
                )
            )
        
        # Configure retry policy
        self._tool_executor.configure_retry(
            RetryConfig(
                max_retries=2,
                initial_delay=0.5,
                exponential_base=2
            )
        )
        
        # Add middleware
        from .core.tool_executor import logging_middleware, timing_middleware
        self._tool_executor.add_middleware(logging_middleware)
        self._tool_executor.add_middleware(timing_middleware)
    
    def get_system_prompt(self) -> Dict[str, Any]:
        """Get the system prompt"""
        return {
            "role": "developer",
            "content": """
# ROLE                
You are an expert Polish legal assistant specializing in civil law (Kodeks cywilny), 
civil procedure (Kodeks postępowania cywilnego), and Supreme Court (Sąd Najwyższy) jurisprudence.

# RESPONSIBILITIES
- Answer legal questions with precise citations to relevant articles
- Search and analyze Supreme Court rulings for precedents
- Draft legal documents following Polish legal standards
- Calculate procedural deadlines accurately
- Validate documents against current statutes

# INSTRUCTIONS
- Always cite specific articles (e.g., "art. 415 KC")
- Use proper Polish legal terminology
- Consider both substantive and procedural aspects
- Provide practical, actionable advice
- Track conversation context and case information
"""
        }
    
    async def process_message_stream(
        self,
        user_message: str,
        thread_id: Optional[str] = None,
        user_id: Optional[str] = None,
        case_id: Optional[str] = None,
        db_manager: DatabaseManager = Depends(get_database_manager),
        conversation_manager: ConversationManager = Depends(get_conversation_manager),
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Process a message with streaming response.
        
        Args:
            user_message: The user's message
            thread_id: Optional conversation thread ID
            user_id: Optional user ID for tracking
            case_id: Optional case ID to link conversation
            
        Yields:
            Stream events with type and content
        """
        if not self._initialized:
            await self.initialize()
        
        # Initialize streaming handler
        streaming_handler: StreamingHandler = StreamingHandler()
        streaming_handler.add_processor(self._metrics_collector)
        
        # Setup conversation
        conversation_id = thread_id or f"conv_{uuid.uuid4()}"
        
        async with conversation_manager.conversation_context(conversation_id) as conv_state:
            # Link to case if provided
            if case_id and not conv_state.case_id:
                conv_state.case_id = case_id
                await conversation_manager.link_to_case(conversation_id, case_id)
            
            # Update user if provided
            if user_id:
                conv_state.user_id = user_id
            
            # Get conversation history
            history = await conversation_manager.get_conversation_history(
                conversation_id, 
                limit=5  # Keep last 5 exchanges for context
            )
            
            # Prepare messages
            messages = [self.get_system_prompt()]
            
            # Add history
            for hist_item in history:
                if isinstance(hist_item["input"], list):
                    messages.extend(hist_item["input"])
                if hist_item["output"]:
                    messages.append({
                        "role": "assistant",
                        "content": hist_item["output"]
                    })
            
            # Add current message
            messages.append({"role": "user", "content": user_message})
            
            try:
                # Create streaming response
                response = await self._client.responses.create(
                    model=self._config.openai.orchestrator_model,
                    input=messages,
                    previous_response_id=conv_state.last_response_id,
                    stream=True,
                    tools=self._tool_schemas,
                    tool_choice="auto",
                    temperature=0.1
                )
                
                # Reset streaming handler for new conversation
                streaming_handler.reset()
                self._metrics_collector.reset()
                
                response_id = None
                accumulated_content = ""
                tool_results = []
                
                # Process stream
                async for event in streaming_handler.process_stream(response):
                    if event.type == StreamEventType.CREATED:
                        response_id = event.thread_id
                        yield {
                            "type": "stream_start",
                            "thread_id": conversation_id,
                            "response_id": response_id
                        }
                    
                    elif event.type == StreamEventType.TEXT_DELTA:
                        yield {
                            "type": "text_delta",
                            "content": event.content,
                            "thread_id": conversation_id
                        }
                    
                    elif event.type == StreamEventType.TEXT_COMPLETE:
                        accumulated_content = event.content
                    
                    elif event.type == StreamEventType.MESSAGE_COMPLETE:
                        accumulated_content = event.content
                        yield {
                            "type": "message_complete",
                            "content": event.content,
                            "thread_id": conversation_id
                        }
                    
                    elif event.type == StreamEventType.TOOL_CALL:
                        # Execute tools
                        tool_results = await self._handle_tool_calls(event.tool_calls)
                        
                        yield {
                            "type": "tool_calls",
                            "tools": [
                                {
                                    "name": tc.name,
                                    "id": tc.call_id,
                                    "status": "completed" if any(r["call_id"] == tc.call_id for r in tool_results) else "failed"
                                }
                                for tc in event.tool_calls
                            ]
                        }
                        
                        # After tool execution, get new response from the model
                        messages.append({"role": "tool_outputs", "outputs": tool_results})
                        
                        tool_response = await self._client.responses.create(
                            model=self._config.openai.orchestrator_model,
                            input=messages,
                            previous_response_id=response_id,
                            stream=True
                        )
                        
                        async for tool_event in streaming_handler.process_stream(tool_response):
                            if tool_event.type == StreamEventType.TEXT_DELTA:
                                yield {
                                    "type": "text_delta",
                                    "content": tool_event.content,
                                    "thread_id": conversation_id
                                }
                            elif tool_event.type == StreamEventType.MESSAGE_COMPLETE:
                                accumulated_content += "\n" + tool_event.content
                                yield {
                                    "type": "message_complete",
                                    "content": accumulated_content,
                                    "thread_id": conversation_id
                                }
                
                # Save conversation
                await conversation_manager.save_response_history(
                    conversation_id,
                    response_id,
                    messages,
                    accumulated_content,
                    conv_state.last_response_id
                )
                
                # Update conversation state
                conv_state.last_response_id = response_id
                await conversation_manager.update_conversation(
                    conversation_id,
                    conv_state
                )
                
                yield {
                    "type": "stream_complete",
                    "thread_id": conversation_id,
                    "metrics": self._metrics_collector.get_metrics()
                }

            except Exception as e:
                logger.error(f"Error processing message stream: {e}", exc_info=True)
                yield {
                    "type": "error",
                    "content": str(e)
                }
    
    async def _handle_tool_calls(self, tool_calls: List[ResponseFunctionToolCall]) -> List[Dict[str, Any]]:
        """
        Execute tool calls concurrently and handle errors.
        """
        tool_results = []
        
        async def execute_and_collect(tool_call):
            try:
                args = json.loads(tool_call.arguments)
                result = await self._tool_executor.execute(tool_call.name, **args)
                
                tool_results.append({
                    "call_id": tool_call.call_id,
                    "output": json.dumps(result)
                })
            except Exception as e:
                logger.error(f"Error executing tool {tool_call.name}: {e}", exc_info=True)
                recovered_output = await self._recover_from_error(tool_call, e)
                tool_results.append(recovered_output)

        await asyncio.gather(*(execute_and_collect(tc) for tc in tool_calls))
        
        return tool_results

    async def _recover_from_error(self, tool_call: ResponseFunctionToolCall, error: Exception) -> Dict[str, Any]:
        """Attempt to recover from a tool execution error"""
        error_message = f"Error in {tool_call.name}: {str(error)}"
        
        # Use a validator model to get a sensible default
        recovery_result = await recover_from_tool_error(
            tool_name=tool_call.name,
            tool_args=tool_call.arguments,
            error_message=error_message
        )
        
        return {
            "call_id": tool_call.call_id,
            "output": json.dumps({
                "error": error_message,
                "recovery": recovery_result.recovery_suggestion
            })
        }
        
    async def get_tool_metrics(self) -> Dict[str, Any]:
        return self._tool_executor.get_metrics()

    async def reset_circuit(self, tool_name: str):
        self._tool_executor.reset_circuit(tool_name)

    async def shutdown(self):
        """Shutdown the agent and all services"""
        logger.info("Agent shutdown complete")

async def main():
    agent = RefactoredParalegalAgent()
    
    async def run():
        async for chunk in agent.process_message_stream("What is the deadline for an appeal?"):
            if chunk['type'] == 'text_delta':
                print(chunk['content'], end="")
    
    await run()

if __name__ == "__main__":
    asyncio.run(main()) 
