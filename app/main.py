"""
Refactored main application entry point with structured logging and authentication.
Merges the best of both original and refactored implementations.
"""

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional, cast

# Set up mock environment if needed
if os.getenv("STANDALONE_MODE", "false").lower() == "true":
    from .core.mock_config import setup_mock_environment
    setup_mock_environment()

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .auth import get_current_active_user
from .core.config_service import ConfigService
from .core.conversation_manager import ConversationManager
from .core.database_manager import DatabaseManager
from .core.llm_manager import LLMManager
from .core.logger_manager import (
    correlation_context,
    get_logger,
    log_api_middleware,
    set_user_id,
    trace,
)
from opentelemetry import trace
from .core.service_interface import ServiceContainer, ServiceLifecycleManager
from .core.tool_executor import ToolExecutor
from .models import ChatRequest, ChatResponse, ToolResult, User
from .paralegal_agents.refactored_agent_sdk import ParalegalAgentSDK
from .routes.auth import router as auth_router
from .routes.case_management_routes import router as case_management_router
from .services import (
    CaseManagementService,
    DocumentGenerationService,
    StatuteSearchService,
    SupremeCourtService,
)

# Get log level and format from environment variables
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
JSON_LOGS = os.getenv("LOG_FORMAT", "json") == "json"
USE_CELERY = os.getenv("USE_CELERY", "false").lower() == "true"

# Import Celery components if enabled
if USE_CELERY:
    from .core.celery_service_wrapper import (
        ExecutionMode,
        celery_service_manager,
    )

tracer = trace.get_tracer(__name__)


# Use the new config to set up logging

logger = get_logger(__name__)


def initialize_services():
    """
    Initialize all services and register them with the container.
    Supports both direct and Celery-based execution modes.
    """
    logger.info(f"Initializing services (Celery mode: {USE_CELERY})")
    service_container = ServiceContainer()

    # Core services
    config_service = ConfigService()
    db_manager = DatabaseManager(config_service)
    llm_manager = LLMManager(config_service)
    conversation_manager = ConversationManager(db_manager, config_service)
    tool_executor = ToolExecutor(config_service)

    # Register core services as singletons
    service_container.register_singleton(ConfigService, config_service)
    service_container.register_singleton(DatabaseManager, db_manager)
    service_container.register_singleton(LLMManager, llm_manager)
    service_container.register_singleton(ConversationManager, conversation_manager)
    service_container.register_singleton(ToolExecutor, tool_executor)


    # Domain services
    statute_search = StatuteSearchService(config_service)
    supreme_court = SupremeCourtService(db_manager, config_service, llm_manager)
    document_generation = DocumentGenerationService(db_manager, statute_search, supreme_court)
    case_management = CaseManagementService(db_manager)

    if USE_CELERY:
        # Register services with Celery manager for async execution
        logger.info("Registering services with Celery manager")

        # Register case management service
        case_proxy = celery_service_manager.register_service(
            "case_management", case_management, default_mode=ExecutionMode.CELERY_ASYNC
        )
        service_container.register_singleton(CaseManagementService, case_proxy)  # type: ignore[arg-type]

        # Register document generation service
        doc_proxy = celery_service_manager.register_service(
            "document_generation", document_generation, default_mode=ExecutionMode.CELERY_ASYNC
        )
        service_container.register_singleton(DocumentGenerationService, doc_proxy)  # type: ignore[arg-type]

        # Register search services
        statute_proxy = celery_service_manager.register_service(
            "statute_search",
            statute_search,
            default_mode=ExecutionMode.CELERY_SYNC,  # Sync for immediate results
        )
        service_container.register_singleton(StatuteSearchService, statute_proxy)  # type: ignore[arg-type]

        supreme_proxy = celery_service_manager.register_service(
            "supreme_court",
            supreme_court,
            default_mode=ExecutionMode.CELERY_SYNC,  # Sync for immediate results
        )
        service_container.register_singleton(SupremeCourtService, supreme_proxy)  # type: ignore[arg-type]
    else:
        # Register services directly without Celery
        service_container.register_singleton(StatuteSearchService, statute_search)
        service_container.register_singleton(SupremeCourtService, supreme_court)
        service_container.register_singleton(DocumentGenerationService, document_generation)
        service_container.register_singleton(CaseManagementService, case_management)

    logger.info("All services registered successfully")

    # Return lifecycle manager for startup/shutdown
    return ServiceLifecycleManager(service_container)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""

    with correlation_context("startup-" + str(uuid.uuid4())) as correlation_id:
        with tracer.start_as_current_span(
            "initialize_services", attributes={"correlation_id": correlation_id}
        ):
            try:
                logger.info("LIFESPAN: Starting AI Paralegal application")

                logger.info("LIFESPAN: Initializing lifecycle manager...")
                app.state.manager = initialize_services()
                await app.state.manager.startup()
                logger.info("LIFESPAN: Lifecycle manager initialization complete.")

                # Initialize agent
                logger.info("LIFESPAN: Initializing agent...")
                app.state.agent = ParalegalAgentSDK(
                    app.state.manager.inject_service(ConfigService),
                    app.state.manager.inject_service(ConversationManager),
                    app.state.manager.inject_service(ToolExecutor),
                )
                await app.state.agent.initialize()
                logger.info("LIFESPAN: Agent initialization complete.")

                if USE_CELERY:
                    # Verify Celery workers are available
                    try:
                        from app.worker.celery_app import celery_app

                        inspect = celery_app.control.inspect()
                        active_workers = inspect.active_queues()

                        if active_workers:
                            logger.info(
                                f"LIFESPAN: Found {len(active_workers)} active Celery workers"
                            )
                        else:
                            logger.warning(
                                "LIFESPAN: No active Celery workers found - tasks will queue"
                            )
                    except Exception as e:
                        logger.error(f"LIFESPAN: Failed to check Celery workers: {e}")

                logger.info("LIFESPAN: Application started successfully")

                yield

            except Exception as e:
                logger.error(f"LIFESPAN: Critical error during startup: {e}", exc_info=True)
                raise

            finally:
                logger.info("LIFESPAN: Shutting down AI Paralegal application")


# Create FastAPI app
app = FastAPI(
    title="AI Paralegal POC",
    version="2.0.0",
    description="AI Paralegal with authentication, structured logging, and improved architecture",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://localhost:3000",
        "http://localhost",
        "https://localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add logging middleware
log_api_middleware(app)

# Include routers
app.include_router(auth_router)
app.include_router(case_management_router)


@app.get("/health")
async def health_check(req: Request):
    """Health check endpoint with service status"""
    agent = req.app.state.agent
    with correlation_context() as correlation_id:
        with tracer.start_as_current_span(
            "health_check", attributes={"correlation_id": correlation_id}
        ):
            logger.info("Health check requested")

            # Get tool metrics
            tool_metrics = await agent.get_tool_metrics()

            # Add Celery status if enabled
            celery_status = "disabled"
            if USE_CELERY:
                try:
                    from app.worker.celery_app import celery_app

                    inspect = celery_app.control.inspect()
                    active_workers = inspect.active_queues()
                    celery_status = (
                        f"active ({len(active_workers)} workers)"
                        if active_workers
                        else "no workers"
                    )
                except:
                    celery_status = "error"

            return {
                "user": "anonymous",
                "status": "healthy",
                "tool_metrics": tool_metrics,
                "celery": celery_status,
                "version": "2.0.0",
            }


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    req: Request,
    current_user: Optional[User] = Depends(get_current_active_user),
):
    """
    Process a chat message with correlation tracking and optional authentication.
    """
    # Use authenticated user ID if available, otherwise use header or anonymous
    agent = req.app.state.agent

    with correlation_context() as correlation_id:
        with tracer.start_as_current_span("chat", attributes={"correlation_id": correlation_id}):
            logger.info(
                f"Chat request received",
                extra={
                    "extra_fields": {
                        "event": "chat_request",
                        "message_length": len(request.message),
                        "has_thread_id": bool(request.thread_id),
                        "has_case_id": bool(request.case_id),
                    }
                },
            )

            try:
                # Process message
                response_content = ""
                tool_results = []
                response_thread_id = request.thread_id

                async for chunk in agent.process_message_stream(
                    user_message=request.message,
                    thread_id=request.thread_id,
                    case_id=request.case_id,
                    user_id=str(current_user.id) if current_user else "anonymous",
                ):
                    if chunk["type"] == "message_complete":
                        response_content = chunk["content"]
                        response_thread_id = chunk.get("thread_id", response_thread_id)
                    elif chunk["type"] == "tool_calls":
                        for tool in chunk["tools"]:
                            tool_results.append(
                                ToolResult(
                                    name=tool["name"], status=tool["status"], call_id=tool["id"]
                                )
                            )
                    elif chunk["type"] == "error":
                        logger.error(
                            "Chat processing error",
                            extra={
                                "extra_fields": {
                                    "event": "chat_error",
                                    "error_type": chunk["error_details"]["type"],
                                    "error_message": chunk["error_details"]["message"],
                                }
                            },
                        )
                        raise HTTPException(status_code=500, detail=chunk["content"])

                        # Return response
                        return ChatResponse(
                            content=response_content,
                            thread_id=response_thread_id,
                            correlation_id=correlation_id,
                            tool_results=tool_results,
                        )

            except Exception as e:
                logger.error(
                    "Failed to process chat request",
                    extra={"extra_fields": {"event": "chat_error", "error_type": type(e).__name__}},
                    exc_info=True,
                )
                raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    req: Request,
    current_user: Optional[User] = Depends(get_current_active_user),
):
    """
    Stream chat responses with Server-Sent Events.
    """
    user_id = str(current_user.id) if current_user else "anonymous"
    agent = req.app.state.agent

    async def generate():
        with correlation_context() as correlation_id:
            with tracer.start_as_current_span(
                "chat_stream", attributes={"correlation_id": correlation_id}
            ):
                try:
                    # Send correlation ID
                    yield f"data: {{'type': 'correlation', 'correlation_id': '{correlation_id}'}}\n\n"

                    # Stream responses
                    async for chunk in agent.process_message_stream(
                        user_message=request.message,
                        thread_id=request.thread_id,
                        user_id=user_id,
                        case_id=request.case_id,
                    ):
                        yield f"data: {json.dumps(chunk)}\n\n"

                    yield "data: [DONE]\n\n"

                except Exception as e:
                    logger.error("Streaming error", exc_info=True)
                    error_chunk = {"type": "error", "content": str(e)}
                    yield f"data: {json.dumps(error_chunk)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket, req: Request):
    """
    WebSocket endpoint for real-time chat.
    """
    await websocket.accept()

    # Extract user ID from query params or headers
    user_id = websocket.query_params.get("user_id", "anonymous")
    agent = req.app.state.agent
    with correlation_context() as correlation_id:
        with tracer.start_as_current_span(
            "websocket_chat", attributes={"correlation_id": correlation_id}
        ):
            set_user_id(req, user_id)

            logger.info(
                "WebSocket connection established",
                extra={"extra_fields": {"event": "websocket_connect", "user_id": user_id}},
            )

            try:
                while True:
                    # Receive message
                    data = await websocket.receive_json()

                    # Process message
                    async for chunk in agent.process_message_stream(
                        user_message=data["message"],
                        thread_id=data.get("thread_id"),
                        user_id=user_id,
                        case_id=data.get("case_id"),
                    ):
                        chunk["correlation_id"] = correlation_id
                        await websocket.send_json(chunk)

            except WebSocketDisconnect:
                logger.info(
                    "WebSocket disconnected",
                    extra={"extra_fields": {"event": "websocket_disconnect", "user_id": user_id}},
                )
            except Exception as e:
                logger.error("WebSocket error", exc_info=True)
                await websocket.close(code=1000)


@app.get("/metrics")
async def get_metrics(req: Request):
    """Get application metrics"""

    agent = req.app.state.agent
    with correlation_context() as correlation_id:
        with tracer.start_as_current_span(
            "get_metrics", attributes={"correlation_id": correlation_id}
        ):
            tool_metrics = await agent.get_tool_metrics()

            return {
                "tools": tool_metrics,
                "application": {
                    "version": "2.0.0",
                    "uptime_seconds": asyncio.get_event_loop().time(),
                },
            }


@app.post("/admin/reset-circuit/{tool_name}")
async def reset_circuit_breaker(tool_name: str, req: Request):
    """Admin endpoint to reset circuit breaker"""
    agent = req.app.state.agent
    with correlation_context() as correlation_id:
        with tracer.start_as_current_span(
            "reset_circuit_breaker", attributes={"correlation_id": correlation_id}
        ):
            logger.warning(
                f"Circuit breaker reset requested",
                extra={"extra_fields": {"event": "circuit_reset", "tool_name": tool_name}},
            )

            await agent.reset_circuit(tool_name)

            return {"status": "success", "tool": tool_name}


# ==================== Celery-specific endpoints ====================


@app.get("/celery/health")
async def celery_health():
    """Check Celery workers health"""
    if not USE_CELERY:
        return {"status": "disabled", "message": "Celery is disabled"}

    try:
        from app.worker.tasks.maintenance import health_check_all_services

        result = health_check_all_services.apply_async()
        health_status = result.get(timeout=10)
        return health_status
    except Exception as e:
        logger.error(f"Celery health check failed: {e}")
        return {"status": "error", "error": str(e)}


@app.get("/celery/stats")
async def celery_stats():
    """Get Celery worker statistics"""
    if not USE_CELERY:
        return {"status": "disabled", "message": "Celery is disabled"}

    try:
        from app.worker.tasks.maintenance import get_worker_statistics

        result = get_worker_statistics.apply_async()
        stats = result.get(timeout=10)
        return stats
    except Exception as e:
        logger.error(f"Failed to get Celery stats: {e}")
        return {"status": "error", "error": str(e)}


@app.get("/celery/task/{task_id}")
async def get_task_status(task_id: str):
    """Get status of a specific Celery task"""
    if not USE_CELERY:
        return {"status": "disabled", "message": "Celery is disabled"}

    try:
        status = celery_service_manager.get_task_status(task_id)
        return status
    except Exception as e:
        logger.error(f"Failed to get task status: {e}")
        return {"status": "error", "error": str(e)}


@app.delete("/celery/task/{task_id}")
async def cancel_task(task_id: str):
    """Cancel a Celery task"""
    if not USE_CELERY:
        return {"status": "disabled", "message": "Celery is disabled"}

    try:
        cancelled = celery_service_manager.cancel_task(task_id)
        return {"status": "success", "task_id": task_id, "cancelled": cancelled}
    except Exception as e:
        logger.error(f"Failed to cancel task: {e}")
        return {"status": "error", "error": str(e)}


@app.post("/celery/search/async")
async def async_search(
    query: str,
    search_type: str = "hybrid",
    current_user: Optional[User] = Depends(get_current_active_user),
):
    """
    Perform asynchronous search using Celery.
    Returns task ID for tracking.
    """
    if not USE_CELERY:
        return {"status": "disabled", "message": "Celery is disabled"}

    try:
        from app.worker.tasks.search_tasks import (
            hybrid_search,
            search_rulings,
            search_statutes,
        )

        if search_type == "hybrid":
            result = hybrid_search.apply_async(args=[query])
        elif search_type == "statutes":
            result = search_statutes.apply_async(args=[query])
        elif search_type == "rulings":
            result = search_rulings.apply_async(args=[query])
        else:
            raise ValueError(f"Unknown search type: {search_type}")

        return {
            "status": "queued",
            "task_id": result.id,
            "search_type": search_type,
            "query": query,
            "check_status_url": f"/celery/task/{result.id}",
        }
    except Exception as e:
        logger.error(f"Failed to queue search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/celery/document/generate/async")
async def async_generate_document(
    document_type: str,
    context: Dict[str, Any],
    current_user: User = Depends(get_current_active_user),
):
    """
    Generate document asynchronously using Celery.
    Returns task ID for tracking.
    """
    if not USE_CELERY:
        return {"status": "disabled", "message": "Celery is disabled"}

    try:
        from app.worker.tasks.document_tasks import generate_legal_document

        result = generate_legal_document.apply_async(
            args=[document_type, context, str(current_user.id)]
        )

        return {
            "status": "queued",
            "task_id": result.id,
            "document_type": document_type,
            "check_status_url": f"/celery/task/{result.id}",
        }
    except Exception as e:
        logger.error(f"Failed to queue document generation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/celery/ingest/trigger")
async def trigger_ingestion(
    ingestion_type: str = "all",
    force_update: bool = False,
    current_user: User = Depends(get_current_active_user),
):
    """
    Trigger data ingestion pipeline via Celery.
    """
    if not USE_CELERY:
        return {"status": "disabled", "message": "Celery is disabled"}

    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        from app.worker.tasks.ingestion_pipeline import run_full_pipeline

        result = run_full_pipeline.apply_async(
            kwargs={
                "statute_force_update": force_update,
                "ruling_pdf_directory": "/app/data/pdfs/sn-rulings",
            }
        )

        return {
            "status": "queued",
            "task_id": result.id,
            "ingestion_type": ingestion_type,
            "check_status_url": f"/celery/task/{result.id}",
        }
    except Exception as e:
        logger.error(f"Failed to trigger ingestion: {e}")
        raise HTTPException(status_code=500, detail=str(e))
