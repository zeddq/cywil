"""Refactored Paralegal Agent implemented with OpenAI Agent SDK.

NOTE: This is an initial scaffold that mirrors the public surface of the old
`RefactoredParalegalAgent` (from `orchestrator_refactored.py`) but relies on
`openai-agents-sdk` primitives.  Additional wiring for streaming and full tool
wrappers will be added in follow-up commits.
"""
from __future__ import annotations

from typing import AsyncGenerator, Dict, Any, Optional, List, Callable
import asyncio
import logging
import json
import uuid
from datetime import timedelta

from agents import Agent, Runner, function_tool, RunContextWrapper, RunHooks, Usage, Tool  # type: ignore
from openai import AsyncOpenAI
from openai.types.responses import ResponseStreamEvent, ResponseFunctionToolCall

from ..core import (
    ConfigService,
    ServiceLifecycleManager,    
    ToolExecutionError,
    ServiceError,
)
from ..core.streaming_handler import StreamingHandler, StreamEventType, MetricsCollector
from ..core.conversation_manager import ConversationManager, get_conversation_manager
from ..core.tool_executor import ToolExecutor, CircuitBreakerConfig, RetryConfig, logging_middleware, timing_middleware
from ..core.service_interface import ServiceInterface, HealthCheckResult, ServiceStatus
from ..services import get_tool_schemas
from .tool_wrappers import get_all_tools, summarize_sn_rulings_tool, search_statute_tool, search_sn_rulings_tool

logger = logging.getLogger(__name__)


@function_tool
def always_failing_tool(some_arg: str) -> str:
    """
    This tool always fails, for demonstration purposes of the error recovery agent.
    To use it, ask the agent to "use the always failing tool with any argument".
    """
    raise ValueError(f"This tool failed intentionally with argument: {some_arg}")


class ExampleHooks(RunHooks):
    def __init__(self):
        self.event_counter = 0

    def _usage_to_str(self, usage: Usage) -> str:
        return f"{usage.requests} requests, {usage.input_tokens} input tokens, {usage.output_tokens} output tokens, {usage.total_tokens} total tokens"

    async def on_agent_start(self, context: RunContextWrapper, agent: Agent) -> None:
        self.event_counter += 1
        logger.info(
            f"### {self.event_counter}: Agent {agent.name} started. Usage: {self._usage_to_str(context.usage)}"
        )

    async def on_agent_end(self, context: RunContextWrapper, agent: Agent, output: Any) -> None:
        self.event_counter += 1
        logger.info(
            f"### {self.event_counter}: Agent {agent.name} ended with output {output}. Usage: {self._usage_to_str(context.usage)}"
        )

    async def on_tool_start(self, context: RunContextWrapper, agent: Agent, tool: Tool) -> None:
        self.event_counter += 1
        logger.info(
            f"### {self.event_counter}: Tool {tool.name} started. Usage: {self._usage_to_str(context.usage)}"
        )

    async def on_tool_end(
        self, context: RunContextWrapper, agent: Agent, tool: Tool, result: str
    ) -> None:
        self.event_counter += 1
        logger.info(
            f"### {self.event_counter}: Tool {tool.name} ended with result {result}. Usage: {self._usage_to_str(context.usage)}"
        )

    async def on_handoff(
        self, context: RunContextWrapper, from_agent: Agent, to_agent: Agent
    ) -> None:
        self.event_counter += 1
        logger.info(
            f"### {self.event_counter}: Handoff from {from_agent.name} to {to_agent.name}. Usage: {self._usage_to_str(context.usage)}"
        )


hooks = ExampleHooks()

class ParalegalAgentSDK(ServiceInterface):
    """Agent wrapper built on the OpenAI Agent SDK with service interface."""

    def __init__(self, config_service: ConfigService, conversation_manager: ConversationManager, tool_executor: ToolExecutor) -> None:
        super().__init__("ParalegalAgentSDK")
        self._config = config_service.config
        self._client = AsyncOpenAI(api_key=self._config.openai.api_key.get_secret_value())

        # Dependency-injected helpers
        self._conversation_manager = conversation_manager
        self._tool_executor = tool_executor
        self._streaming_handler = StreamingHandler()
        self._metrics_collector = MetricsCollector()
        self._streaming_handler.add_processor(self._metrics_collector)

        self._initialized: bool = False
        self._agent: Optional[Agent] = None
        self._tool_schemas = None
        
        logger.info("ParalegalAgentSDK created")

    # ---------------------------------------------------------------------
    # ServiceInterface implementation
    # ---------------------------------------------------------------------
    async def _health_check_impl(self) -> HealthCheckResult:
        """Check agent and tool executor health."""
        if not self._initialized:
            return HealthCheckResult(
                status=ServiceStatus.INITIALIZING,
                message="Agent not yet initialized"
            )
        
        # Check tool executor health
        executor_healthy = self._tool_executor is not None
        agent_healthy = self._agent is not None
        
        if executor_healthy and agent_healthy:
            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message="Agent is healthy",
                details={
                    "tool_count": len(self._tool_schemas) if self._tool_schemas else 0,
                    "agent_ready": True
                }
            )
        else:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message="Agent components not ready",
                details={
                    "executor_ready": executor_healthy,
                    "agent_ready": agent_healthy
                }
            )
    
    async def _initialize_impl(self) -> None:
        """Initialize the agent and all services."""
        await self.initialize()
        
    async def _shutdown_impl(self) -> None:
        """Shutdown the agent and clean up resources."""
        logger.info("ParalegalAgentSDK shutdown complete")
    
    # ---------------------------------------------------------------------
    # Public API (matches previous orchestrator)
    # ---------------------------------------------------------------------
    async def initialize(self) -> None:
        """Lazy initialization because it requires async calls."""
        if self._initialized:
            return
        # Configure ToolExecutor similarly to old orchestrator
        self._configure_tool_executor()
        
        # Get tool schemas
        self._tool_schemas = get_tool_schemas()

        # Build SDK agent
        self._agent = self._build_agent()

        self._initialized = True
        logger.info(f"ParalegalAgentSDK initialized with {len(self._tool_schemas)} tools")

    async def process_message_stream(
        self,
        user_message: str,
        thread_id: Optional[str] = None,
        user_id: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream assistant response; API compatible with the original class."""
        if not self._initialized:
            await self.initialize()

        if self._agent is None:
            raise RuntimeError("Agent not initialized")

        conversation_id = thread_id or f"conv_{uuid.uuid4()}"

        # Reset streaming handler for new conversation
        self._streaming_handler.reset()
        self._metrics_collector.reset()
        
        try:
            # The Agent SDK manages context internally; we still track our DB history
            async with self._conversation_manager.conversation_context(conversation_id) as conv_state:
                if case_id and not conv_state.case_id:
                    conv_state.case_id = case_id
                    await self._conversation_manager.link_to_case(conversation_id, case_id)
                if user_id:
                    conv_state.user_id = user_id

                # Yield stream start event
                yield {
                    "type": "stream_start",
                    "thread_id": conversation_id,
                    "response_id": conversation_id
                }
                
                # We directly run the agent via Runner.run() with streaming=True
                result = await Runner.run(
                    starting_agent=self._agent,
                    input=user_message,
                    stream=True,
                    hooks=hooks,
                )

                # The SDK returns a StreamedRunResult when stream=True
                accumulated_content = ""
                
                async for event in result:
                    # The SDK emits different event types than the raw OpenAI API
                    # Based on the SDK docs, events have properties like:
                    # - event_type: "agent", "message", "tool_call", etc.
                    # - data: the actual event data
                    
                    if hasattr(event, 'event_type'):
                        if event.event_type == "message":
                            # Text content from the agent
                            if hasattr(event, 'data') and hasattr(event.data, 'content'):
                                content = event.data.content
                                accumulated_content += content
                                yield {
                                    "type": "text_delta",
                                    "content": content,
                                    "thread_id": conversation_id
                                }
                        
                        elif event.event_type == "tool_call":
                            # Tool is being called
                            if hasattr(event, 'data'):
                                yield {
                                    "type": "tool_calls",
                                    "tools": [{
                                        "name": event.data.name if hasattr(event.data, 'name') else "unknown",
                                        "id": event.data.id if hasattr(event.data, 'id') else "",
                                        "status": "executing"
                                    }],
                                    "thread_id": conversation_id
                                }
                        
                        elif event.event_type == "completion":
                            # Stream completed
                            yield {
                                "type": "message_complete",
                                "content": accumulated_content,
                                "thread_id": conversation_id
                            }
                            yield {
                                "type": "stream_complete",
                                "thread_id": conversation_id,
                                "metrics": self._metrics_collector.get_metrics()
                            }
                    
                    else:
                        # Fallback for unknown event types
                        yield {
                            "type": "unknown",
                            "raw": str(event),
                            "thread_id": conversation_id
                        }

                # Save conversation history
                await self._conversation_manager.save_response_history(
                    conversation_id,
                    conversation_id,  # Using conversation_id as response_id for now
                    [{"role": "user", "content": user_message}],
                    accumulated_content,
                    conv_state.last_response_id
                )
            
                # Update conversation state
                conv_state.last_response_id = conversation_id
                await self._conversation_manager.update_conversation(
                    conversation_id,
                    conv_state
                )
                
        except Exception as e:
            logger.error(f"Error processing message stream: {e}", exc_info=True)
            yield {
                "type": "error",
                "content": str(e),
                "thread_id": conversation_id
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_legal_research_agent(self) -> Agent:
        """Builds a specialist agent for complex legal research."""
        return Agent(
            name="LegalResearchAgent",
            instructions=(
                "You are an expert in deep legal research. Your role is to analyze complex "
                "legal questions, find obscure precedents, and provide detailed research memos. "
                "Focus on jurisprudence and comparative law."
            ),
            model="o3",
            tools=[summarize_sn_rulings_tool, search_statute_tool, search_sn_rulings_tool]
        )

    def _build_error_recovery_agent(self) -> Agent:
        """Builds a specialist agent for recovering from tool errors."""
        return Agent(
            name="ToolErrorRecoveryAgent",
            instructions=(
                "You are a specialist AI assistant that helps other agents recover from tool "
                "errors. Your task is to analyze a failed tool call, including the tool name, "
                "its arguments, and the error message returned. Your goal is to understand the "
                "root cause and provide a solution. This could be corrected arguments for the "
                "tool, a suggestion to use a different tool, or a clarification question."
            ),
            model="o3-mini",
        )

    def _build_agent(self) -> Agent:
        """Create the Agent SDK object with system prompt and tool list."""

        system_prompt = (
            "# ROLE\n"
            "You are an expert Polish legal assistant specializing in civil law (Kodeks cywilny), "
            "civil procedure (Kodeks postępowania cywilnego), and Supreme Court (Sąd Najwyższy) jurisprudence. "
            "You are the lead orchestrator and can delegate tasks to specialist agents.\n\n"
            "# RESPONSIBILITIES\n"
            "- Answer legal questions with precise citations to relevant articles\n"
            "- Search and analyze Supreme Court rulings for precedents\n"
            "- Draft legal documents following Polish legal standards\n"
            "- Calculate procedural deadlines accurately\n"
            "- Validate documents against current statutes\n\n"
            "# INSTRUCTIONS\n"
            "- Always cite specific articles (e.g., 'art. 415 KC')\n"
            "- Use proper Polish legal terminology\n"
            "- Consider both substantive and procedural aspects\n"
            "- Provide practical, actionable advice\n"
            "- Track conversation context and case information\n\n"
            "# DELEGATION\n"
            "For complex legal research tasks requiring deep analysis of jurisprudence or comparative law, "
            "delegate the task by handing off to the 'LegalResearchAgent'.\n\n"
            "# ERROR HANDLING\n"
            "If a tool you use returns an error, do not give up or apologize. Your primary responsibility "
            "is to solve the user's problem. Invoke the 'ToolErrorRecoveryAgent', providing it with the "
            "name of the tool that failed, the arguments you passed to it, and the exact error message "
            "you received. The recovery agent will help you fix the problem so you can try again."
        )

        # Get all wrapped tools
        tools = get_all_tools()
        # tools.append(always_failing_tool)

        # Build handoff agents
        research_agent = self._build_legal_research_agent()
        recovery_agent = self._build_error_recovery_agent()

        agent = Agent(
            name="ParalegalAgent",
            instructions=system_prompt,
            tools=tools + [research_agent, recovery_agent],
            model=self._config.openai.orchestrator_model,
        )
        return agent

    def _configure_tool_executor(self) -> None:
        critical_tools = ["search_statute", "draft_document", "compute_deadline"]
        for t in critical_tools:
            self._tool_executor.configure_circuit_breaker(
                t,
                CircuitBreakerConfig(
                    failure_threshold=3,
                    recovery_timeout=timedelta(seconds=30),
                    success_threshold=2,
                ),
            )

        self._tool_executor.configure_retry(
            RetryConfig(max_retries=2, initial_delay=0.5, exponential_base=2)
        )
        
        # Add middleware
        self._tool_executor.add_middleware(logging_middleware)
        self._tool_executor.add_middleware(timing_middleware)

    # async def _recover_from_error(self, tool_name: str, tool_args: str, error: Exception) -> Dict[str, Any]:
        # """Attempt to recover from a tool execution error."""
        # error_message = f"Error in {tool_name}: {str(error)}"
        
        # # Use a validator model to get a sensible default
        # recovery_result = await recover_from_tool_error(
        #     tool_name=tool_name,
        #     tool_args=tool_args,
        #     error_message=error_message
        # )
        
        # return {
        #     "error": error_message,
        #     "recovery": recovery_result.recovery_suggestion
        # }
    
    # --------------------------------------------------------------
    def _convert_stream_event(self, event: Any, conversation_id: str) -> Dict[str, Any]:
        """Map internal streaming events to legacy format expected by callers."""
        if event.type == StreamEventType.TEXT_DELTA:
            return {"type": "text_delta", "content": event.content, "thread_id": conversation_id}
        if event.type == StreamEventType.MESSAGE_COMPLETE:
            return {"type": "message_complete", "content": event.content, "thread_id": conversation_id}
        if event.type == StreamEventType.CREATED:
            return {"type": "stream_start", "thread_id": conversation_id, "response_id": event.thread_id}
        if event.type == StreamEventType.COMPLETED:
            return {"type": "stream_complete", "thread_id": conversation_id, "metrics": self._metrics_collector.get_metrics()}
        # Default passthrough
        return {"type": "other", "raw": event, "thread_id": conversation_id}


    async def get_tool_metrics(self) -> Dict[str, Any]:
        """Get metrics from tool executor."""
        return self._tool_executor.get_metrics()

    async def reset_circuit(self, tool_name: str):
        """Reset circuit breaker for a specific tool."""
        self._tool_executor.reset_circuit(tool_name)
    
    async def shutdown(self):
        """Shutdown the agent and all services."""
        await self._shutdown_impl()

    def get_system_prompt(self) -> str:
        """Get the system prompt for the agent."""
        return (
            "# ROLE\n"
            "You are an expert Polish legal assistant specializing in civil law (Kodeks cywilny), "
            "civil procedure (Kodeks postępowania cywilnego), and Supreme Court (Sąd Najwyższy) jurisprudence.\n\n"
            "# RESPONSIBILITIES\n"
            "- Answer legal questions with precise citations to relevant articles\n"
            "- Search and analyze Supreme Court rulings for precedents\n"
            "- Draft legal documents following Polish legal standards\n"
            "- Calculate procedural deadlines accurately\n"
            "- Validate documents against current statutes\n\n"
            "# INSTRUCTIONS\n"
            "- Always cite specific articles (e.g., 'art. 415 KC')\n"
            "- Use proper Polish legal terminology\n"
            "- Consider both substantive and procedural aspects\n"
            "- Provide practical, actionable advice\n"
            "- Track conversation context and case information"
        )


# ---------------------------------------------------------------------
# Quick CLI test (optional)
# ---------------------------------------------------------------------
async def _demo() -> None:  # pragma: no cover
    from ..core import ConfigService
    config_service = ConfigService()
    agent = ParalegalAgentSDK(config_service)
    await agent.initialize()

    async for chunk in agent.process_message_stream("Jakie są terminy na apelację w sprawie cywilnej?"):
        if chunk["type"] == "text_delta":
            print(chunk["content"], end="", flush=True)
        elif chunk["type"] == "message_complete":
            print("\n\n==DONE==\n" + chunk["content"])

    await asyncio.sleep(0.1)

if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_demo()) 
