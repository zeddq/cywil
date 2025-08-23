"""
Updated main application with Celery integration for microservices architecture.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
import uuid

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from .paralegal_agents.refactored_agent_sdk import ParalegalAgentSDK
from .core.config_service import ConfigService
from .core.logger_manager import get_logger, correlation_context, set_user_id, trace, log_api_middleware
from .auth import get_current_active_user
from .core.auth_middleware import auth_middleware
from .models import ChatRequest, ChatResponse, ToolResult, User
from .routes.auth_routes_refactored import router as auth_router
from .routes.case_management_routes import router as case_management_router
from .core.service_interface import ServiceContainer, ServiceLifecycleManager
from .services import StatuteSearchService, SupremeCourtService, DocumentGenerationService, CaseManagementService
from .core.database_manager import DatabaseManager
from .core.llm_manager import LLMManager
from .core.conversation_manager import ConversationManager
from .core.tool_executor import ToolExecutor
from .services.auth_service import AuthService
from .core.celery_service_wrapper import (
    CeleryServiceManager,
    ExecutionMode,
    celery_service_manager,
    celery_task
)
import json

# Get log level and format from environment variables
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
JSON_LOGS = os.getenv("LOG_FORMAT", "json") == "json"
USE_CELERY = os.getenv("USE_CELERY", "true").lower() == "true"

tracer = trace.get_tracer(__name__)
logger = get_logger(__name__)


def initialize_services_with_celery() -> ServiceLifecycleManager:
    """
    Initialize all services with Celery integration for microservices architecture.
    """
    logger.info(f"Initializing services with Celery: {USE_CELERY}")
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
    case_management = CaseManagementService(db_manager)
    
    if USE_CELERY:
        # Register services with Celery manager for async execution
        logger.info("Registering services with Celery manager")
        
        # Register case management service
        case_proxy = celery_service_manager.register_service(
            "case_management",
            case_management,
            default_mode=ExecutionMode.CELERY_ASYNC
        )
        service_container.register_singleton(CaseManagementService, case_proxy)
        
        # Register document generation service
        doc_proxy = celery_service_manager.register_service(
            "document_generation",
            document_generation,
            default_mode=ExecutionMode.CELERY_ASYNC
        )
        service_container.register_singleton(DocumentGenerationService, doc_proxy)
        
        # Register search services
        statute_proxy = celery_service_manager.register_service(
            "statute_search",
            statute_search,
            default_mode=ExecutionMode.CELERY_SYNC  # Sync for immediate results
        )
        service_container.register_singleton(StatuteSearchService, statute_proxy)
        
        supreme_proxy = celery_service_manager.register_service(
            "supreme_court",
            supreme_court,
            default_mode=ExecutionMode.CELERY_SYNC  # Sync for immediate results
        )
        service_container.register_singleton(SupremeCourtService, supreme_proxy)
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
    """Application lifespan manager with Celery integration"""
    
    with correlation_context("startup-" + str(uuid.uuid4())) as correlation_id:
        with tracer.start_as_current_span("initialize_services", attributes={"correlation_id": correlation_id}):
            try:
                logger.info("LIFESPAN: Starting AI Paralegal application with Celery")
                
                logger.info("LIFESPAN: Initializing lifecycle manager...")
                app.state.manager = initialize_services_with_celery()
                
                logger.info("LIFESPAN: Starting services...")
                await app.state.manager.startup()
                
                logger.info("LIFESPAN: Initializing paralegal agent...")
                config = ConfigService().config
                app.state.agent = ParalegalAgentSDK(config)
                await app.state.agent.initialize()
                
                if USE_CELERY:
                    # Verify Celery workers are available
                    from app.worker.celery_app import celery_app
                    inspect = celery_app.control.inspect()
                    active_workers = inspect.active_queues()
                    
                    if active_workers:
                        logger.info(f"LIFESPAN: Found {len(active_workers)} active Celery workers")
                    else:
                        logger.warning("LIFESPAN: No active Celery workers found - tasks will queue")
                
                logger.info("LIFESPAN: Application startup complete")
                
            except Exception as e:
                logger.error(f"LIFESPAN: Startup failed: {str(e)}", exc_info=True)
                raise
    
    yield
    
    with correlation_context("shutdown-" + str(uuid.uuid4())) as correlation_id:
        with tracer.start_as_current_span("shutdown_services", attributes={"correlation_id": correlation_id}):
            logger.info("LIFESPAN: Shutting down AI Paralegal application")
            
            if hasattr(app.state, "agent"):
                await app.state.agent.shutdown()
            
            if hasattr(app.state, "manager"):
                await app.state.manager.shutdown()
            
            logger.info("LIFESPAN: Application shutdown complete")


app = FastAPI(
    title="AI Paralegal POC with Celery",
    version="2.1.0",
    lifespan=lifespan
)

# CORS middleware
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


# Celery-specific endpoints
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
        return {
            "status": "error",
            "error": str(e)
        }


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
        return {
            "status": "error",
            "error": str(e)
        }


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
        return {
            "status": "error",
            "error": str(e)
        }


@app.delete("/celery/task/{task_id}")
async def cancel_task(task_id: str):
    """Cancel a Celery task"""
    if not USE_CELERY:
        return {"status": "disabled", "message": "Celery is disabled"}
    
    try:
        cancelled = celery_service_manager.cancel_task(task_id)
        return {
            "status": "success",
            "task_id": task_id,
            "cancelled": cancelled
        }
    except Exception as e:
        logger.error(f"Failed to cancel task: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@app.post("/celery/search/async")
async def async_search(
    query: str,
    search_type: str = "hybrid",
    current_user: Optional[User] = Depends(get_current_active_user)
):
    """
    Perform asynchronous search using Celery.
    Returns task ID for tracking.
    """
    if not USE_CELERY:
        return {"status": "disabled", "message": "Celery is disabled"}
    
    try:
        from app.worker.tasks.search_tasks import hybrid_search, search_statutes, search_rulings
        
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
            "check_status_url": f"/celery/task/{result.id}"
        }
    except Exception as e:
        logger.error(f"Failed to queue search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/celery/document/generate/async")
async def async_generate_document(
    document_type: str,
    context: Dict[str, Any],
    current_user: User = Depends(get_current_active_user)
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
            "check_status_url": f"/celery/task/{result.id}"
        }
    except Exception as e:
        logger.error(f"Failed to queue document generation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/celery/ingest/trigger")
async def trigger_ingestion(
    ingestion_type: str = "all",
    force_update: bool = False,
    current_user: User = Depends(get_current_active_user)
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
                "ruling_pdf_directory": "/app/data/pdfs/sn-rulings"
            }
        )
        
        return {
            "status": "queued",
            "task_id": result.id,
            "ingestion_type": ingestion_type,
            "check_status_url": f"/celery/task/{result.id}"
        }
    except Exception as e:
        logger.error(f"Failed to trigger ingestion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Keep existing endpoints
@app.get("/health")
async def health_check(req: Request):
    """Health check endpoint with service status"""
    agent = req.app.state.agent
    with correlation_context() as correlation_id:
        with tracer.start_as_current_span("health_check", attributes={"correlation_id": correlation_id}):
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
                    celery_status = f"active ({len(active_workers)} workers)" if active_workers else "no workers"
                except:
                    celery_status = "error"
            
            return {
                "user": "anonymous",
                "status": "healthy",
                "tool_metrics": tool_metrics,
                "celery": celery_status,
                "version": "2.1.0"
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
                response_thread_id = request.thread_id
                
                async for chunk in agent.process_message_stream(
                    user_message=request.message,
                    thread_id=request.thread_id,
                    case_id=request.case_id,
                    user_id=str(current_user.id) if current_user else None
                ):
                    if chunk["type"] == "message_complete":
                        response_content = chunk["content"]
                        response_thread_id = chunk.get("thread_id", response_thread_id)
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
                
                return ChatResponse(
                    content=response_content,
                    tool_calls=tool_results,
                    thread_id=response_thread_id
                )
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Chat processing failed: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(
        "app.main_celery:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "[%(asctime)s] %(levelname)s - %(name)s - %(message)s",
                },
            },
            "handlers": {
                "default": {
                    "formatter": "default",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {
                "level": LOG_LEVEL,
                "handlers": ["default"],
            },
        }
    )
