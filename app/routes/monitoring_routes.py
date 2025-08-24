"""
API routes for Celery monitoring and management.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.core.logger_manager import get_logger
from app.models import User
from app.worker.celery_app import celery_app
from app.worker.monitoring import monitor
from app.worker.tasks.maintenance import (
    cleanup_expired_results,
    get_worker_statistics,
    health_check_all_services,
    monitor_task_performance,
    process_dead_letter_queue,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])


class TaskSubmission(BaseModel):
    """Model for submitting a task."""

    task_name: str = Field(..., description="Name of the task to execute")
    args: List[Any] = Field(default_factory=list, description="Task arguments")
    kwargs: Dict[str, Any] = Field(default_factory=dict, description="Task keyword arguments")
    queue: Optional[str] = Field(None, description="Queue to submit to")
    priority: Optional[int] = Field(None, description="Task priority (0-10)")


class TaskStatusResponse(BaseModel):
    """Response model for task status."""

    task_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    timestamp: str


@router.get("/health")
async def get_health_status(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Get health status of all services including Celery workers.

    Returns:
        Comprehensive health status report
    """
    try:
        # Get monitoring health check
        celery_health = monitor.health_check()

        # Trigger comprehensive health check task
        task = health_check_all_services.delay()

        # Wait for result with timeout
        try:
            service_health = task.get(timeout=10)
        except Exception as e:
            logger.error(f"Health check task failed: {e}")
            service_health = {"status": "error", "error": str(e)}

        return {
            "monitoring": celery_health,
            "services": service_health,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error getting health status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workers")
async def get_workers(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Get status of all Celery workers.

    Returns:
        Worker status and statistics
    """
    try:
        # Get current worker status from monitor
        worker_status = monitor.get_worker_status()

        # Get detailed statistics from Celery
        task = get_worker_statistics.delay()

        try:
            detailed_stats = task.get(timeout=5)
        except Exception as e:
            logger.error(f"Failed to get detailed stats: {e}")
            detailed_stats = None

        return {
            "current_status": worker_status,
            "detailed_stats": detailed_stats,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error getting worker status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str, current_user: User = Depends(get_current_user)
) -> TaskStatusResponse:
    """
    Get status of a specific task.

    Args:
        task_id: The task ID to check

    Returns:
        Task status and result
    """
    try:
        # Get from monitor first
        task_status = monitor.get_task_status(task_id)

        if task_status:
            return TaskStatusResponse(
                task_id=task_id,
                status=task_status.get("status", "UNKNOWN"),
                result=task_status.get("result"),
                error=task_status.get("exception"),
                traceback=task_status.get("traceback"),
                timestamp=datetime.utcnow().isoformat(),
            )

        # Fall back to Celery result backend
        from celery.result import AsyncResult

        result = AsyncResult(task_id, app=celery_app)

        response = TaskStatusResponse(
            task_id=task_id,
            status=result.status,
            timestamp=datetime.utcnow().isoformat(),
        )

        if result.ready():
            if result.successful():
                response.result = result.result
            else:
                response.error = str(result.info)
                response.traceback = result.traceback

        return response

    except Exception as e:
        logger.error(f"Error getting task status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/submit")
async def submit_task(
    task_submission: TaskSubmission, current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Submit a task for execution.

    Args:
        task_submission: Task details

    Returns:
        Task ID and submission status
    """
    try:
        # Get the task from registry
        task = celery_app.tasks.get(task_submission.task_name)

        if not task:
            raise HTTPException(
                status_code=404, detail=f"Task {task_submission.task_name} not found"
            )

        # Submit the task
        options = {}
        if task_submission.queue:
            options["queue"] = task_submission.queue
        if task_submission.priority is not None:
            options["priority"] = task_submission.priority

        result = task.apply_async(
            args=task_submission.args, kwargs=task_submission.kwargs, **options
        )

        return {
            "task_id": result.id,
            "status": "submitted",
            "task_name": task_submission.task_name,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/revoke")
async def revoke_task(
    task_id: str,
    terminate: bool = Query(False, description="Terminate running task"),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Revoke a task.

    Args:
        task_id: Task ID to revoke
        terminate: Whether to terminate if running

    Returns:
        Revocation status
    """
    try:
        celery_app.control.revoke(task_id, terminate=terminate)

        return {
            "task_id": task_id,
            "status": "revoked",
            "terminated": terminate,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error revoking task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance")
async def get_performance_metrics(
    task_name: Optional[str] = Query(None, description="Specific task name"),
    hours: int = Query(24, description="Hours to look back"),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Get performance metrics for tasks.

    Args:
        task_name: Optional specific task to get metrics for
        hours: Number of hours to look back

    Returns:
        Performance metrics
    """
    try:
        if task_name:
            # Get metrics from monitor
            metrics = monitor.get_performance_stats(task_name)
            return {
                "task_name": task_name,
                "metrics": metrics,
                "timestamp": datetime.utcnow().isoformat(),
            }
        else:
            # Get comprehensive metrics
            task = monitor_task_performance.delay(time_window_hours=hours)

            try:
                result = task.get(timeout=30)
                return result
            except Exception as e:
                logger.error(f"Failed to get performance metrics: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to get metrics: {e}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting performance metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/errors")
async def get_recent_errors(
    limit: int = Query(10, description="Number of errors to return"),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Get recent task errors.

    Args:
        limit: Maximum number of errors to return

    Returns:
        List of recent errors
    """
    try:
        errors = monitor.get_error_summary(limit=limit)

        return {
            "errors": errors,
            "count": len(errors),
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error getting error summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dlq/process")
async def process_dlq(
    max_items: int = Query(100, description="Maximum items to process"),
    requeue: bool = Query(False, description="Whether to requeue tasks"),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Process dead letter queue items.

    Args:
        max_items: Maximum number of items to process
        requeue: Whether to requeue failed tasks

    Returns:
        Processing statistics
    """
    try:
        task = process_dead_letter_queue.delay(max_retries=3 if requeue else 0, requeue=requeue)

        try:
            result = task.get(timeout=60)
            return result
        except Exception as e:
            logger.error(f"DLQ processing failed: {e}")
            raise HTTPException(status_code=500, detail=f"DLQ processing failed: {e}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing DLQ: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/maintenance/cleanup")
async def cleanup_old_results(
    days: int = Query(7, description="Days to keep results"),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Clean up old task results.

    Args:
        days: Number of days to keep results

    Returns:
        Cleanup statistics
    """
    try:
        task = cleanup_expired_results.delay(days_to_keep=days)

        try:
            result = task.get(timeout=30)
            return result
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            raise HTTPException(status_code=500, detail=f"Cleanup failed: {e}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during cleanup: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queues")
async def get_queue_status(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Get status of all queues.

    Returns:
        Queue lengths and status
    """
    try:
        queue_lengths = monitor.get_queue_lengths()

        # Get active queues from Celery
        inspect = celery_app.control.inspect()
        active_queues = inspect.active_queues()

        return {
            "queue_lengths": queue_lengths,
            "active_queues": active_queues,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error getting queue status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks")
async def list_available_tasks(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    List all available Celery tasks.

    Returns:
        List of registered tasks
    """
    try:
        tasks = []

        for task_name, task in celery_app.tasks.items():
            # Skip built-in Celery tasks
            if not task_name.startswith("celery."):
                tasks.append(
                    {
                        "name": task_name,
                        "module": (task.__module__ if hasattr(task, "__module__") else None),
                        "rate_limit": getattr(task, "rate_limit", None),
                        "max_retries": getattr(task, "max_retries", None),
                        "queue": getattr(task, "queue", "default"),
                    }
                )

        return {
            "tasks": sorted(tasks, key=lambda x: x["name"]),
            "count": len(tasks),
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error listing tasks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
