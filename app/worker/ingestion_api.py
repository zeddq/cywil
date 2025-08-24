"""
FastAPI application for managing ingestion tasks via Celery.
"""

from typing import Any, Dict, Optional

from celery.result import AsyncResult
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.models import User
from app.auth import get_current_user
from app.core.logger_manager import get_logger
from app.worker.celery_app import celery_app

logger = get_logger(__name__)

# Create FastAPI app
app = FastAPI(
    title="AI Paralegal Ingestion Service",
    description="API for managing document ingestion tasks",
    version="1.0.0",
)


# Pydantic models for request/response
class StatuteIngestionRequest(BaseModel):
    """Request model for statute ingestion"""

    pdf_path: Optional[str] = Field(None, description="Path to specific PDF file")
    code_type: Optional[str] = Field(None, description="Type of statute (KC or KPC)")
    force_update: bool = Field(False, description="Force update existing data")


class RulingIngestionRequest(BaseModel):
    """Request model for ruling ingestion"""

    pdf_directory: str = Field(..., description="Directory containing ruling PDFs")
    max_workers: int = Field(3, description="Maximum concurrent workers")


class PipelineRequest(BaseModel):
    """Request model for full pipeline execution"""

    statute_force_update: bool = Field(False, description="Force update statute data")
    ruling_pdf_directory: Optional[str] = Field(None, description="Directory with ruling PDFs")
    max_ruling_workers: int = Field(3, description="Maximum concurrent workers for rulings")


class TaskResponse(BaseModel):
    """Response model for task submission"""

    task_id: str
    status: str
    message: str


class TaskStatusResponse(BaseModel):
    """Response model for task status"""

    task_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: Optional[Dict[str, Any]] = None


# Health check endpoint
@app.get("/health")
async def health_check():
    """Check health of the ingestion service"""
    try:
        # Check Celery connection
        celery_status = celery_app.control.inspect().active()
        if celery_status is None:
            raise Exception("Cannot connect to Celery workers")

        return {
            "status": "healthy",
            "service": "ingestion-api",
            "celery_workers": len(celery_status) if celery_status else 0,
        }
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})


# Statute ingestion endpoints
@app.post("/ingest/statutes", response_model=TaskResponse)
async def ingest_statutes(
    request: StatuteIngestionRequest, current_user: User = Depends(get_current_user)
):
    """Trigger statute ingestion task"""
    try:
        if request.pdf_path and request.code_type:
            # Ingest specific statute
            from app.worker.tasks.statute_tasks import ingest_statute_pdf

            task = ingest_statute_pdf.delay(
                request.pdf_path, request.code_type, request.force_update
            )
        else:
            # Ingest all statutes
            from app.worker.tasks.statute_tasks import ingest_all_statutes

            task = ingest_all_statutes.delay(request.force_update)

        return TaskResponse(
            task_id=task.id,
            status="submitted",
            message="Statute ingestion task submitted successfully",
        )
    except Exception as e:
        logger.error(f"Error submitting statute task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ingest/statutes/status")
async def get_statute_status(current_user: User = Depends(get_current_user)):
    """Get current statute ingestion status"""
    try:
        from app.worker.tasks.statute_tasks import get_statute_ingestion_status

        task = get_statute_ingestion_status.delay()
        result = task.get(timeout=10)
        return result
    except Exception as e:
        logger.error(f"Error getting statute status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Ruling ingestion endpoints
@app.post("/ingest/rulings", response_model=TaskResponse)
async def ingest_rulings(
    request: RulingIngestionRequest, current_user: User = Depends(get_current_user)
):
    """Trigger ruling ingestion task"""
    try:
        from app.worker.tasks.ruling_tasks import process_ruling_batch

        task = process_ruling_batch.delay(request.pdf_directory, request.max_workers)

        return TaskResponse(
            task_id=task.id,
            status="submitted",
            message="Ruling ingestion task submitted successfully",
        )
    except Exception as e:
        logger.error(f"Error submitting ruling task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ingest/rulings/status")
async def get_ruling_status(current_user: User = Depends(get_current_user)):
    """Get current ruling processing status"""
    try:
        from app.worker.tasks.ruling_tasks import get_ruling_processing_status

        task = get_ruling_processing_status.delay()
        result = task.get(timeout=10)
        return result
    except Exception as e:
        logger.error(f"Error getting ruling status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Embedding endpoints
@app.post("/embeddings/generate/{collection_type}", response_model=TaskResponse)
async def generate_embeddings(
    collection_type: str,
    force_regenerate: bool = False,
    current_user: User = Depends(get_current_user),
):
    """Generate embeddings for a collection"""
    try:
        if collection_type in ["KC", "KPC"]:
            from app.worker.tasks.embedding_tasks import generate_statute_embeddings

            task = generate_statute_embeddings.delay(collection_type, force_regenerate)
        else:
            raise ValueError(f"Invalid collection type: {collection_type}")

        return TaskResponse(
            task_id=task.id,
            status="submitted",
            message=f"Embedding generation for {collection_type} submitted",
        )
    except Exception as e:
        logger.error(f"Error submitting embedding task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/embeddings/statistics")
async def get_embedding_statistics(
    collection_name: Optional[str] = None, current_user: User = Depends(get_current_user)
):
    """Get embedding statistics"""
    try:
        from app.worker.tasks.embedding_tasks import get_embedding_statistics

        task = get_embedding_statistics.delay(collection_name)
        result = task.get(timeout=10)
        return result
    except Exception as e:
        logger.error(f"Error getting embedding statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Pipeline endpoints
@app.post("/pipeline/full", response_model=TaskResponse)
async def run_full_pipeline(
    request: PipelineRequest, current_user: User = Depends(get_current_user)
):
    """Run the complete ingestion pipeline"""
    try:
        from app.worker.tasks.ingestion_pipeline import run_full_pipeline

        task = run_full_pipeline.delay(
            request.statute_force_update, request.ruling_pdf_directory, request.max_ruling_workers
        )

        return TaskResponse(
            task_id=task.id, status="submitted", message="Full pipeline execution submitted"
        )
    except Exception as e:
        logger.error(f"Error submitting pipeline task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/pipeline/statutes", response_model=TaskResponse)
async def run_statute_pipeline(
    force_update: bool = False, current_user: User = Depends(get_current_user)
):
    """Run only the statute ingestion pipeline"""
    try:
        from app.worker.tasks.ingestion_pipeline import run_statute_pipeline

        task = run_statute_pipeline.delay(force_update)

        return TaskResponse(
            task_id=task.id, status="submitted", message="Statute pipeline execution submitted"
        )
    except Exception as e:
        logger.error(f"Error submitting statute pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/pipeline/rulings", response_model=TaskResponse)
async def run_ruling_pipeline(
    request: RulingIngestionRequest, current_user: User = Depends(get_current_user)
):
    """Run only the ruling ingestion pipeline"""
    try:
        from app.worker.tasks.ingestion_pipeline import run_ruling_pipeline

        task = run_ruling_pipeline.delay(request.pdf_directory, request.max_workers)

        return TaskResponse(
            task_id=task.id, status="submitted", message="Ruling pipeline execution submitted"
        )
    except Exception as e:
        logger.error(f"Error submitting ruling pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Task management endpoints
@app.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str, current_user: User = Depends(get_current_user)):
    """Get status of a specific task"""
    try:
        result = AsyncResult(task_id, app=celery_app)

        response = TaskStatusResponse(task_id=task_id, status=result.status)

        if result.ready():
            if result.successful():
                response.result = result.result
            else:
                response.error = str(result.info)
        elif result.status == "PENDING":
            response.progress = {"state": "Task not found or pending"}
        else:
            response.progress = result.info

        return response
    except Exception as e:
        logger.error(f"Error getting task status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/tasks/{task_id}")
async def cancel_task(task_id: str, current_user: User = Depends(get_current_user)):
    """Cancel a running task"""
    try:
        result = AsyncResult(task_id, app=celery_app)
        result.revoke(terminate=True)

        return {"task_id": task_id, "status": "cancelled", "message": "Task cancellation requested"}
    except Exception as e:
        logger.error(f"Error cancelling task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tasks")
async def list_active_tasks(current_user: User = Depends(get_current_user)):
    """List all active tasks"""
    try:
        inspect = celery_app.control.inspect()
        active_tasks = inspect.active()

        if not active_tasks:
            return {"active_tasks": [], "worker_count": 0}

        all_tasks = []
        for worker, tasks in active_tasks.items():
            for task in tasks:
                task["worker"] = worker
                all_tasks.append(task)

        return {"active_tasks": all_tasks, "worker_count": len(active_tasks)}
    except Exception as e:
        logger.error(f"Error listing active tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
