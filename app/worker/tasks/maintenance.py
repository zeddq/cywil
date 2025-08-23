"""
Celery maintenance tasks for monitoring, cleanup, and dead letter queue processing.
"""
import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import json
import redis
from celery import states
from celery.result import AsyncResult

from app.worker.celery_app import celery_app
from app.core.database_manager import DatabaseManager
from app.core.config_service import ConfigService
from app.core.logger_manager import get_logger
from app.core.service_interface import ServiceContainer, ServiceStatus

logger = get_logger(__name__)

def run_async(coro):
    """Helper to run async code in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="worker.tasks.maintenance.health_check_all_services",
    bind=True
)
def health_check_all_services(self) -> Dict[str, Any]:
    """
    Check health status of all services.
    
    Returns:
        Health status report for all services
    """
    logger.info("Running health check for all services")
    
    async def _process():
        config_service = ConfigService()
        db_manager = DatabaseManager(config_service)
        
        health_report = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "services": {},
            "warnings": [],
            "errors": []
        }
        
        try:
            # Check database
            try:
                await db_manager.initialize()
                async with db_manager.get_session() as session:
                    result = await session.execute("SELECT 1")
                    health_report["services"]["database"] = {
                        "status": "healthy",
                        "message": "Database connection successful"
                    }
            except Exception as e:
                health_report["services"]["database"] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
                health_report["status"] = "degraded"
                health_report["errors"].append(f"Database error: {e}")
            
            # Check Redis
            try:
                redis_client = redis.from_url(config_service.config.redis.url)
                redis_client.ping()
                health_report["services"]["redis"] = {
                    "status": "healthy",
                    "message": "Redis connection successful"
                }
            except Exception as e:
                health_report["services"]["redis"] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
                health_report["status"] = "degraded"
                health_report["errors"].append(f"Redis error: {e}")
            
            # Check Qdrant
            try:
                from qdrant_client import QdrantClient
                qdrant_client = QdrantClient(
                    host=config_service.config.qdrant.host,
                    port=config_service.config.qdrant.port
                )
                collections = qdrant_client.get_collections()
                health_report["services"]["qdrant"] = {
                    "status": "healthy",
                    "message": f"Qdrant healthy with {len(collections.collections)} collections"
                }
            except Exception as e:
                health_report["services"]["qdrant"] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
                health_report["warnings"].append(f"Qdrant warning: {e}")
            
            # Check Celery workers
            try:
                active_queues = celery_app.control.inspect().active_queues()
                if active_queues:
                    worker_count = len(active_queues)
                    health_report["services"]["celery_workers"] = {
                        "status": "healthy",
                        "message": f"{worker_count} workers active",
                        "workers": list(active_queues.keys())
                    }
                else:
                    health_report["services"]["celery_workers"] = {
                        "status": "warning",
                        "message": "No active workers found"
                    }
                    health_report["warnings"].append("No Celery workers active")
            except Exception as e:
                health_report["services"]["celery_workers"] = {
                    "status": "unknown",
                    "error": str(e)
                }
            
            # Set overall status
            if health_report["errors"]:
                health_report["status"] = "unhealthy"
            elif health_report["warnings"]:
                health_report["status"] = "degraded"
            
            return health_report
            
        except Exception as e:
            logger.error(f"Error during health check: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        finally:
            if db_manager:
                await db_manager.shutdown()
    
    return run_async(_process())


@celery_app.task(
    name="worker.tasks.maintenance.cleanup_expired_results",
    bind=True
)
def cleanup_expired_results(self, days_to_keep: int = 7) -> Dict[str, Any]:
    """
    Clean up expired task results from Redis.
    
    Args:
        days_to_keep: Number of days to keep results
        
    Returns:
        Cleanup statistics
    """
    logger.info(f"Cleaning up task results older than {days_to_keep} days")
    
    try:
        config_service = ConfigService()
        redis_client = redis.from_url(config_service.config.redis.url)
        
        cleanup_stats = {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "days_to_keep": days_to_keep,
            "keys_examined": 0,
            "keys_deleted": 0,
            "space_freed_bytes": 0
        }
        
        # Get all Celery result keys
        pattern = "celery-task-meta-*"
        cursor = 0
        cutoff_time = datetime.utcnow() - timedelta(days=days_to_keep)
        
        while True:
            cursor, keys = redis_client.scan(cursor, match=pattern, count=100)
            cleanup_stats["keys_examined"] += len(keys)
            
            for key in keys:
                try:
                    # Get task result
                    result_data = redis_client.get(key)
                    if result_data:
                        result = json.loads(result_data)
                        
                        # Check if result is expired
                        if "date_done" in result:
                            date_done = datetime.fromisoformat(result["date_done"].replace("Z", "+00:00"))
                            if date_done < cutoff_time:
                                # Get size before deletion
                                key_size = len(result_data)
                                
                                # Delete the key
                                redis_client.delete(key)
                                cleanup_stats["keys_deleted"] += 1
                                cleanup_stats["space_freed_bytes"] += key_size
                except Exception as e:
                    logger.warning(f"Error processing key {key}: {e}")
            
            if cursor == 0:
                break
        
        # Convert bytes to human-readable format
        space_freed_mb = cleanup_stats["space_freed_bytes"] / (1024 * 1024)
        cleanup_stats["space_freed_mb"] = round(space_freed_mb, 2)
        
        logger.info(f"Cleanup completed: {cleanup_stats['keys_deleted']} keys deleted, "
                   f"{cleanup_stats['space_freed_mb']} MB freed")
        
        return cleanup_stats
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@celery_app.task(
    name="worker.tasks.maintenance.process_dead_letter_queue",
    bind=True
)
def process_dead_letter_queue(
    self,
    max_retries: int = 1,
    requeue: bool = False
) -> Dict[str, Any]:
    """
    Process messages in the dead letter queue.
    
    Args:
        max_retries: Maximum retry attempts for failed tasks
        requeue: Whether to requeue tasks or just report
        
    Returns:
        Processing statistics
    """
    logger.info("Processing dead letter queue")
    
    try:
        config_service = ConfigService()
        redis_client = redis.from_url(config_service.config.redis.url)
        
        stats = {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "messages_examined": 0,
            "messages_requeued": 0,
            "messages_discarded": 0,
            "messages_by_queue": {},
            "errors": []
        }
        
        # Get messages from dead letter queue
        # This is a simplified implementation - in production you'd use Kombu
        dlq_key = "dead_letter"
        
        while True:
            # Pop message from dead letter queue
            message = redis_client.lpop(dlq_key)
            if not message:
                break
            
            stats["messages_examined"] += 1
            
            try:
                msg_data = json.loads(message)
                original_queue = msg_data.get("original_queue", "unknown")
                task_name = msg_data.get("task", "unknown")
                retry_count = msg_data.get("retry_count", 0)
                
                # Track by queue
                if original_queue not in stats["messages_by_queue"]:
                    stats["messages_by_queue"][original_queue] = {
                        "examined": 0,
                        "requeued": 0,
                        "discarded": 0
                    }
                
                stats["messages_by_queue"][original_queue]["examined"] += 1
                
                if requeue and retry_count < max_retries:
                    # Requeue the task
                    msg_data["retry_count"] = retry_count + 1
                    
                    # Send back to original queue
                    celery_app.send_task(
                        task_name,
                        args=msg_data.get("args", []),
                        kwargs=msg_data.get("kwargs", {}),
                        queue=original_queue
                    )
                    
                    stats["messages_requeued"] += 1
                    stats["messages_by_queue"][original_queue]["requeued"] += 1
                    
                    logger.info(f"Requeued task {task_name} to {original_queue}")
                else:
                    # Discard or log for manual review
                    stats["messages_discarded"] += 1
                    stats["messages_by_queue"][original_queue]["discarded"] += 1
                    
                    if retry_count >= max_retries:
                        logger.warning(f"Task {task_name} exceeded max retries ({max_retries})")
                    
            except Exception as e:
                logger.error(f"Error processing dead letter message: {e}")
                stats["errors"].append(str(e))
        
        return stats
        
    except Exception as e:
        logger.error(f"Error processing dead letter queue: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@celery_app.task(
    name="worker.tasks.maintenance.get_worker_statistics",
    bind=True
)
def get_worker_statistics(self) -> Dict[str, Any]:
    """
    Get detailed statistics about Celery workers and tasks.
    
    Returns:
        Worker and task statistics
    """
    logger.info("Gathering worker statistics")
    
    try:
        inspect = celery_app.control.inspect()
        
        stats = {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "workers": {},
            "queues": {},
            "summary": {
                "total_workers": 0,
                "total_active_tasks": 0,
                "total_scheduled_tasks": 0,
                "total_reserved_tasks": 0
            }
        }
        
        # Get active workers
        active_queues = inspect.active_queues()
        if active_queues:
            stats["summary"]["total_workers"] = len(active_queues)
            
            for worker, queues in active_queues.items():
                stats["workers"][worker] = {
                    "queues": [q["name"] for q in queues],
                    "active_tasks": 0,
                    "scheduled_tasks": 0,
                    "reserved_tasks": 0
                }
        
        # Get active tasks
        active_tasks = inspect.active()
        if active_tasks:
            for worker, tasks in active_tasks.items():
                if worker in stats["workers"]:
                    stats["workers"][worker]["active_tasks"] = len(tasks)
                    stats["summary"]["total_active_tasks"] += len(tasks)
                
                # Track tasks by queue
                for task in tasks:
                    queue = task.get("delivery_info", {}).get("routing_key", "unknown")
                    if queue not in stats["queues"]:
                        stats["queues"][queue] = {
                            "active": 0,
                            "scheduled": 0,
                            "reserved": 0
                        }
                    stats["queues"][queue]["active"] += 1
        
        # Get scheduled tasks
        scheduled_tasks = inspect.scheduled()
        if scheduled_tasks:
            for worker, tasks in scheduled_tasks.items():
                if worker in stats["workers"]:
                    stats["workers"][worker]["scheduled_tasks"] = len(tasks)
                    stats["summary"]["total_scheduled_tasks"] += len(tasks)
        
        # Get reserved tasks
        reserved_tasks = inspect.reserved()
        if reserved_tasks:
            for worker, tasks in reserved_tasks.items():
                if worker in stats["workers"]:
                    stats["workers"][worker]["reserved_tasks"] = len(tasks)
                    stats["summary"]["total_reserved_tasks"] += len(tasks)
        
        # Get task counts by state from Redis
        config_service = ConfigService()
        redis_client = redis.from_url(config_service.config.redis.url)
        
        task_states = {
            "SUCCESS": 0,
            "FAILURE": 0,
            "PENDING": 0,
            "RETRY": 0,
            "REVOKED": 0
        }
        
        pattern = "celery-task-meta-*"
        cursor = 0
        
        while True:
            cursor, keys = redis_client.scan(cursor, match=pattern, count=100)
            
            for key in keys:
                try:
                    result_data = redis_client.get(key)
                    if result_data:
                        result = json.loads(result_data)
                        state = result.get("status", "UNKNOWN")
                        if state in task_states:
                            task_states[state] += 1
                except:
                    pass
            
            if cursor == 0:
                break
        
        stats["task_states"] = task_states
        
        return stats
        
    except Exception as e:
        logger.error(f"Error gathering statistics: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@celery_app.task(
    name="worker.tasks.maintenance.update_vector_indices",
    bind=True
)
def update_vector_indices(self) -> Dict[str, Any]:
    """
    Update vector database indices for optimal performance.
    
    Returns:
        Index update statistics
    """
    logger.info("Updating vector indices")
    
    try:
        config_service = ConfigService()
        from qdrant_client import QdrantClient
        
        qdrant_client = QdrantClient(
            host=config_service.config.qdrant.host,
            port=config_service.config.qdrant.port
        )
        
        stats = {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "collections_updated": [],
            "total_points": 0
        }
        
        # Get all collections
        collections = qdrant_client.get_collections()
        
        for collection in collections.collections:
            collection_name = collection.name
            
            # Get collection info
            collection_info = qdrant_client.get_collection(collection_name)
            point_count = collection_info.points_count
            
            stats["total_points"] += point_count
            stats["collections_updated"].append({
                "name": collection_name,
                "points": point_count,
                "vectors_size": collection_info.config.params.vectors.size
            })
            
            # Optimize collection (this triggers index optimization)
            qdrant_client.update_collection(
                collection_name=collection_name,
                optimizer_config={
                    "deleted_threshold": 0.2,
                    "vacuum_min_vector_number": 1000,
                    "default_segment_number": 5,
                    "max_segment_size": 200000,
                    "memmap_threshold": 50000,
                    "indexing_threshold": 10000
                }
            )
            
            logger.info(f"Optimized collection {collection_name} with {point_count} points")
        
        return stats
        
    except Exception as e:
        logger.error(f"Error updating indices: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@celery_app.task(
    name="worker.tasks.maintenance.monitor_task_performance",
    bind=True
)
def monitor_task_performance(
    self,
    time_window_hours: int = 24
) -> Dict[str, Any]:
    """
    Monitor task performance metrics over a time window.
    
    Args:
        time_window_hours: Hours to look back for metrics
        
    Returns:
        Performance metrics and statistics
    """
    logger.info(f"Monitoring task performance for last {time_window_hours} hours")
    
    try:
        config_service = ConfigService()
        redis_client = redis.from_url(config_service.config.redis.url)
        
        cutoff_time = datetime.utcnow() - timedelta(hours=time_window_hours)
        
        metrics = {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "time_window_hours": time_window_hours,
            "tasks_by_name": {},
            "performance_summary": {
                "total_tasks": 0,
                "successful_tasks": 0,
                "failed_tasks": 0,
                "average_runtime_seconds": 0,
                "slowest_task": None,
                "fastest_task": None
            }
        }
        
        pattern = "celery-task-meta-*"
        cursor = 0
        runtimes = []
        
        while True:
            cursor, keys = redis_client.scan(cursor, match=pattern, count=100)
            
            for key in keys:
                try:
                    result_data = redis_client.get(key)
                    if result_data:
                        result = json.loads(result_data)
                        
                        # Check if within time window
                        if "date_done" in result:
                            date_done = datetime.fromisoformat(result["date_done"].replace("Z", "+00:00"))
                            if date_done >= cutoff_time:
                                task_name = result.get("task", "unknown")
                                status = result.get("status", "UNKNOWN")
                                runtime = result.get("runtime", 0)
                                
                                # Initialize task metrics
                                if task_name not in metrics["tasks_by_name"]:
                                    metrics["tasks_by_name"][task_name] = {
                                        "total": 0,
                                        "success": 0,
                                        "failure": 0,
                                        "average_runtime": 0,
                                        "runtimes": []
                                    }
                                
                                # Update metrics
                                metrics["tasks_by_name"][task_name]["total"] += 1
                                metrics["performance_summary"]["total_tasks"] += 1
                                
                                if status == "SUCCESS":
                                    metrics["tasks_by_name"][task_name]["success"] += 1
                                    metrics["performance_summary"]["successful_tasks"] += 1
                                elif status == "FAILURE":
                                    metrics["tasks_by_name"][task_name]["failure"] += 1
                                    metrics["performance_summary"]["failed_tasks"] += 1
                                
                                if runtime:
                                    metrics["tasks_by_name"][task_name]["runtimes"].append(runtime)
                                    runtimes.append((task_name, runtime))
                                
                except Exception as e:
                    logger.warning(f"Error processing key {key}: {e}")
            
            if cursor == 0:
                break
        
        # Calculate averages and find extremes
        if runtimes:
            all_runtimes = [r[1] for r in runtimes]
            metrics["performance_summary"]["average_runtime_seconds"] = round(
                sum(all_runtimes) / len(all_runtimes), 2
            )
            
            # Find slowest and fastest
            runtimes.sort(key=lambda x: x[1])
            metrics["performance_summary"]["fastest_task"] = {
                "name": runtimes[0][0],
                "runtime": runtimes[0][1]
            }
            metrics["performance_summary"]["slowest_task"] = {
                "name": runtimes[-1][0],
                "runtime": runtimes[-1][1]
            }
        
        # Calculate averages for each task
        for task_name, task_metrics in metrics["tasks_by_name"].items():
            if task_metrics["runtimes"]:
                task_metrics["average_runtime"] = round(
                    sum(task_metrics["runtimes"]) / len(task_metrics["runtimes"]), 2
                )
            del task_metrics["runtimes"]  # Remove raw data to keep response size down
        
        return metrics
        
    except Exception as e:
        logger.error(f"Error monitoring performance: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }