"""
Refactored main application entry point with structured logging and authentication.
Merges the best of both original and refactored implementations.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from .paralegal_agents.refactored_agent_sdk import ParalegalAgentSDK
from .core.config_service import ConfigService
from .core.logger_manager import get_logger, correlation_context, set_user_id, trace, log_api_middleware
from .auth import get_current_user, get_current_active_user
from .core.auth_middleware import auth_middleware
from .models import ChatRequest, ChatResponse, ToolResult, User
from .routes.auth_routes_refactored import router as auth_router
from .routes.case_management_routes import router as case_management_router
from .models import init_db
from .core.service_interface import ServiceContainer, ServiceLifecycleManager
from .services import StatuteSearchService, SupremeCourtService, DocumentGenerationService, CaseManagementService, EmbeddingService, StatuteIngestionService, SupremeCourtIngestService
from .core.database_manager import DatabaseManager
from .core.llm_manager import LLMManager
from .core.conversation_manager import ConversationManager
from .core.tool_executor import ToolExecutor
from .services.auth_service import AuthService
from .core.logger_manager import get_logger
import json


# Get log level and format from environment variables
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
JSON_LOGS = os.getenv("LOG_FORMAT", "json") == "json"

tracer = trace.get_tracer(__name__)


# Use the new config to set up logging

logger = get_logger(__name__)


def initialize_services():
    """
    Initialize all services and register them with the container.
    This should be called during application startup.
    """
    logger.info("Initializing services...")
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
    
    # Auth service
    auth_service = AuthService(config_service)
    service_container.register_singleton(AuthService, auth_service)
    
    # Domain services
    statute_search = StatuteSearchService(config_service)
    supreme_court = SupremeCourtService(db_manager, config_service)
    document_generation = DocumentGenerationService(db_manager, statute_search, supreme_court)
    case_management = CaseManagementService()
    
    # Ingestion services
    embedding_service = EmbeddingService(db_manager)
    statute_ingestion = StatuteIngestionService(db_manager)
    supreme_court_ingest = SupremeCourtIngestService(db_manager)
    
    # Register domain services
    service_container.register_singleton(StatuteSearchService, statute_search)
    service_container.register_singleton(SupremeCourtService, supreme_court)
    service_container.register_singleton(DocumentGenerationService, document_generation)
    service_container.register_singleton(CaseManagementService, case_management)
    
    # Register ingestion services
    service_container.register_singleton(EmbeddingService, embedding_service)
    service_container.register_singleton(StatuteIngestionService, statute_ingestion)
    service_container.register_singleton(SupremeCourtIngestService, supreme_court_ingest)
    
    logger.info("All services registered successfully")
    
    # Return lifecycle manager for startup/shutdown
    return ServiceLifecycleManager(service_container)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    
    with correlation_context() as correlation_id:
        with tracer.start_as_current_span("initialize_services", attributes={"correlation_id": correlation_id}):
            try:
                logger.info("LIFESPAN: Starting AI Paralegal application")
                # Initialize database
                logger.info("LIFESPAN: Initializing lifecycle manager...")
                app.state.manager = initialize_services()
                await app.state.manager.startup()
                logger.info("LIFESPAN: Lifecycle manager initialization complete.")
                
                logger.info("LIFESPAN: Initializing database...")
                init_db(app.state.manager.inject_service(DatabaseManager))
                logger.info("LIFESPAN: Database initialization complete.")
                
                # Initialize agent
                logger.info("LIFESPAN: Initializing agent...")
                app.state.agent = ParalegalAgentSDK(app.state.manager.inject_service(ConfigService))
                await app.state.agent.initialize()
                logger.info("LIFESPAN: Agent initialization complete.")
                
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
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://localhost:3000", "http://localhost", "https://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Add logging middleware
log_api_middleware(app)
# Add authentication middleware
app.middleware("http")(auth_middleware)

# Include routers
app.include_router(auth_router)
app.include_router(case_management_router)


@app.get("/health")
async def health_check(req: Request, current_user: Optional[User] = Depends(get_current_user)):
    """Health check endpoint with service status"""
    agent = req.app.state.agent
    with correlation_context() as correlation_id:
        with tracer.start_as_current_span("health_check", attributes={"correlation_id": correlation_id}):
            logger.info("Health check requested")
            
            # Get tool metrics
            tool_metrics = await agent.get_tool_metrics()
            
            return {
                "user": current_user.model_dump_json(),
                "status": "healthy",
                "tool_metrics": tool_metrics,
                "version": "2.0.0"
            }


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest, 
    req: Request,
    current_user: Optional[User] = Depends(get_current_active_user)
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
                        "has_case_id": bool(request.case_id)
                    }
                }
            )
            
            try:
                # Process message
                response_content = ""
                tool_results = []
                
                async for chunk in agent.process_message_stream(
                    user_message=request.message,
                    thread_id=request.thread_id,
                    case_id=request.case_id,
                    user_id=str(current_user.id)
                ):
                    if chunk["type"] == "message_complete":
                        response_content = chunk["content"]
                    elif chunk["type"] == "tool_calls":
                        for tool in chunk["tools"]:
                            tool_results.append(
                                ToolResult(
                                    name=tool["name"],
                                    status=tool["status"],
                                    call_id=tool["id"]
                                )
                            )
                    elif chunk["type"] == "error":
                        logger.error(
                            "Chat processing error",
                            extra={
                                "extra_fields": {
                                    "event": "chat_error",
                                    "error_type": chunk["error_details"]["type"],
                                    "error_message": chunk["error_details"]["message"]
                                }
                            }
                        )
                        raise HTTPException(status_code=500, detail=chunk["content"])
                
                # Return response
                return ChatResponse(
                    content=response_content,
                    thread_id=chunk.get("thread_id"),
                    correlation_id=correlation_id,
                    tool_results=tool_results
                )
                
            except Exception as e:
                logger.error(
                    "Failed to process chat request",
                    extra={
                        "extra_fields": {
                            "event": "chat_error",
                            "error_type": type(e).__name__
                        }
                    },
                    exc_info=True
                )
                raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest, req: Request, current_user: Optional[User] = Depends(get_current_active_user)):
    """
    Stream chat responses with Server-Sent Events.
    """
    user_id = str(current_user.id)
    agent = req.app.state.agent
    
    async def generate():
        with correlation_context() as correlation_id:
            with tracer.start_as_current_span("chat_stream", attributes={"correlation_id": correlation_id}):                
                try:
                    # Send correlation ID
                    yield f"data: {{'type': 'correlation', 'correlation_id': '{correlation_id}'}}\n\n"
                    
                    # Stream responses
                    async for chunk in agent.process_message_stream(
                        user_message=request.message,
                        thread_id=request.thread_id,
                        user_id=user_id,
                        case_id=request.case_id
                    ):
                        yield f"data: {json.dumps(chunk)}\n\n"
                        
                    yield "data: [DONE]\n\n"
                    
                except Exception as e:
                    logger.error("Streaming error", exc_info=True)
                    error_chunk = {
                        "type": "error",
                        "content": str(e)
                    }
                    yield f"data: {json.dumps(error_chunk)}\n\n"
        
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
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
        with tracer.start_as_current_span("websocket_chat", attributes={"correlation_id": correlation_id}):
            set_user_id(user_id)
            
            logger.info(
                "WebSocket connection established",
                extra={
                    "extra_fields": {
                        "event": "websocket_connect",
                        "user_id": user_id
                    }
                }
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
                        case_id=data.get("case_id")
                    ):
                        chunk["correlation_id"] = correlation_id
                        await websocket.send_json(chunk)
                        
            except WebSocketDisconnect:
                logger.info(
                    "WebSocket disconnected",
                    extra={
                        "extra_fields": {
                            "event": "websocket_disconnect",
                            "user_id": user_id
                        }
                    }
                )
            except Exception as e:
                logger.error("WebSocket error", exc_info=True)
                await websocket.close(code=1000)


@app.get("/metrics")
async def get_metrics(req: Request):
    """Get application metrics"""

    agent = req.app.state.agent
    with correlation_context() as correlation_id:
        with tracer.start_as_current_span("get_metrics", attributes={"correlation_id": correlation_id}):
            tool_metrics = await agent.get_tool_metrics()
            
            return {
                "tools": tool_metrics,
                "application": {
                    "version": "2.0.0",
                    "uptime_seconds": asyncio.get_event_loop().time()
                }
            }


@app.post("/admin/reset-circuit/{tool_name}")
async def reset_circuit_breaker(tool_name: str, req: Request):
    """Admin endpoint to reset circuit breaker"""
    agent = req.app.state.agent
    with correlation_context() as correlation_id:
        with tracer.start_as_current_span("reset_circuit_breaker", attributes={"correlation_id": correlation_id}):
            logger.warning(
                f"Circuit breaker reset requested",
                extra={
                    "extra_fields": {
                        "event": "circuit_reset",
                        "tool_name": tool_name
                    }
                }
            )
            
            await agent.reset_circuit(tool_name)
            
            return {"status": "success", "tool": tool_name}
