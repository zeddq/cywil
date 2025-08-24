"""
Comprehensive Celery monitoring with signals, metrics, and error tracking.
"""

import json
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import redis
from celery.signals import (  # Worker signals; Task signals; Beat signals; Event signals
    before_task_publish,
    task_failure,
    task_postrun,
    task_prerun,
    task_rejected,
    task_retry,
    task_revoked,
    task_sent,
    task_success,
    worker_init,
    worker_process_init,
    worker_process_shutdown,
    worker_ready,
    worker_shutting_down,
)

from app.core.config_service import ConfigService
from app.core.logger_manager import get_logger

logger = get_logger(__name__)


class TaskStatus(Enum):
    """Task status enumeration."""

    PENDING = "PENDING"
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RETRY = "RETRY"
    REVOKED = "REVOKED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass
class TaskMetrics:
    """Metrics for a single task execution."""

    task_id: str
    task_name: str
    queue: str
    status: TaskStatus
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    args: list = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)
    result: Any = None
    exception: Optional[str] = None
    traceback: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    worker_hostname: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data["status"] = self.status.value
        if self.start_time:
            data["start_time"] = self.start_time.isoformat()
        if self.end_time:
            data["end_time"] = self.end_time.isoformat()
        return data


@dataclass
class WorkerMetrics:
    """Metrics for a worker instance."""

    hostname: str
    pid: int
    started_at: datetime
    last_heartbeat: datetime
    tasks_executed: int = 0
    tasks_success: int = 0
    tasks_failed: int = 0
    tasks_retried: int = 0
    current_tasks: Dict[str, TaskMetrics] = field(default_factory=dict)
    queue_lengths: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["last_heartbeat"] = self.last_heartbeat.isoformat()
        data["current_tasks"] = {
            task_id: metrics.to_dict() for task_id, metrics in self.current_tasks.items()
        }
        return data


class CeleryMonitor:
    """
    Centralized monitoring for Celery workers and tasks.
    Provides metrics, logging, and error tracking.
    """

    def __init__(self):
        """Initialize the monitor."""
        self.config_service = ConfigService()
        self.redis_client = None
        self.worker_metrics: Dict[str, WorkerMetrics] = {}
        self.task_metrics: Dict[str, TaskMetrics] = {}
        self.error_buffer = deque(maxlen=1000)  # Keep last 1000 errors
        self.performance_buffer = defaultdict(lambda: deque(maxlen=100))
        self._initialize_redis()

    def _initialize_redis(self):
        """Initialize Redis connection for metrics storage.
        Prefer the shared client from the worker service registry, with a safe fallback.
        """
        # Try to use the shared worker-level Redis client
        try:
            try:
                from app.worker.service_registry import get_worker_services
                self.redis_client = get_worker_services().redis
                # Validate connection
                self.redis_client.ping()
                logger.info("Using shared Redis client from service registry for monitoring")
                return
            except Exception as e:
                logger.warning(
                    f"Shared Redis client unavailable; falling back to direct connection: {e}"
                )

            # Fallback to a direct connection
            self.redis_client = redis.from_url(
                self.config_service.config.redis.url, decode_responses=True
            )
            self.redis_client.ping()
            logger.info("Direct Redis connection established for monitoring")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = None

    def register_signals(self):
        """Register all Celery signal handlers."""
        # Worker lifecycle signals
        worker_init.connect(self.on_worker_init)
        worker_ready.connect(self.on_worker_ready)
        worker_process_init.connect(self.on_worker_process_init)
        worker_process_shutdown.connect(self.on_worker_process_shutdown)
        worker_shutting_down.connect(self.on_worker_shutting_down)

        # Task lifecycle signals
        task_prerun.connect(self.on_task_prerun)
        task_postrun.connect(self.on_task_postrun)
        task_success.connect(self.on_task_success)
        task_failure.connect(self.on_task_failure)
        task_retry.connect(self.on_task_retry)
        task_rejected.connect(self.on_task_rejected)
        task_revoked.connect(self.on_task_revoked)
        task_sent.connect(self.on_task_sent)
        before_task_publish.connect(self.on_before_task_publish)

        logger.info("Celery monitoring signals registered")

    # Worker lifecycle handlers
    def on_worker_init(self, sender=None, **kwargs):
        """Handle worker initialization."""
        logger.info(f"Worker initializing: {sender}")

    def on_worker_ready(self, sender=None, **kwargs):
        """Handle worker ready event."""
        hostname = sender.hostname if sender else "unknown"
        pid = kwargs.get("pid", 0)

        self.worker_metrics[hostname] = WorkerMetrics(
            hostname=hostname,
            pid=pid,
            started_at=datetime.utcnow(),
            last_heartbeat=datetime.utcnow(),
        )

        logger.info(f"Worker ready: {hostname} (PID: {pid})")
        self._store_metric(
            "worker_ready",
            {
                "hostname": hostname,
                "pid": pid,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    def on_worker_process_init(self, sender=None, **kwargs):
        """Handle worker process initialization."""
        logger.info(f"Worker process initialized")

    def on_worker_process_shutdown(self, sender=None, **kwargs):
        """Handle worker process shutdown."""
        logger.info(f"Worker process shutting down")

    def on_worker_shutting_down(self, sender=None, **kwargs):
        """Handle worker shutdown."""
        hostname = sender.hostname if sender else "unknown"

        if hostname in self.worker_metrics:
            metrics = self.worker_metrics[hostname]
            uptime = (datetime.utcnow() - metrics.started_at).total_seconds()

            logger.info(
                f"Worker shutting down: {hostname} "
                f"(uptime: {uptime:.2f}s, "
                f"tasks: {metrics.tasks_executed}, "
                f"success: {metrics.tasks_success}, "
                f"failed: {metrics.tasks_failed})"
            )

            self._store_metric(
                "worker_shutdown",
                {
                    "hostname": hostname,
                    "uptime_seconds": uptime,
                    "tasks_executed": metrics.tasks_executed,
                    "tasks_success": metrics.tasks_success,
                    "tasks_failed": metrics.tasks_failed,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            del self.worker_metrics[hostname]

    # Task lifecycle handlers
    def on_task_sent(self, sender=None, task_id=None, task=None, args=None, kwargs=None, **kw):
        """Handle task sent event."""
        logger.debug(f"Task sent: {task}[{task_id}]")
        self._store_metric(
            "task_sent",
            {
                "task_id": task_id,
                "task_name": task,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    def on_before_task_publish(self, sender=None, body=None, headers=None, **kwargs):
        """Handle before task publish event."""
        task_id = headers.get("id") if headers else None
        task_name = headers.get("task") if headers else None

        if task_id:
            logger.debug(f"Publishing task: {task_name}[{task_id}]")

    def on_task_prerun(self, sender=None, task_id=None, task=None, args=None, kwargs=None, **kw):
        """Handle task pre-run event."""
        # Handle None task_id
        if task_id is None:
            task_id = f"unknown-{datetime.utcnow().timestamp()}"
            
        task_name = getattr(task, "name", "unknown")
        request_obj = getattr(task, "request", None)
        queue = getattr(request_obj, "queue", "default") if request_obj else "default"
        hostname = getattr(request_obj, "hostname", "unknown") if request_obj else "unknown"

        # Create task metrics
        metrics = TaskMetrics(
            task_id=task_id,
            task_name=task_name,
            queue=queue,
            status=TaskStatus.STARTED,
            start_time=datetime.utcnow(),
            args=list(args) if args else [],
            kwargs=dict(kwargs) if kwargs else {},
            worker_hostname=hostname,
        )

        self.task_metrics[task_id] = metrics

        # Update worker metrics
        if hostname in self.worker_metrics:
            self.worker_metrics[hostname].current_tasks[task_id] = metrics
            self.worker_metrics[hostname].last_heartbeat = datetime.utcnow()

        logger.info(f"Task started: {task_name}[{task_id}] on {hostname}")
        self._store_metric("task_started", metrics.to_dict())

    def on_task_postrun(
        self,
        sender=None,
        task_id=None,
        task=None,
        args=None,
        kwargs=None,
        retval=None,
        state=None,
        **kw,
    ):
        """Handle task post-run event."""
        task_id_key = str(task_id) if task_id is not None else None
        if task_id_key and task_id_key in self.task_metrics:
            metrics = self.task_metrics[task_id_key]
            metrics.end_time = datetime.utcnow()
            metrics.duration_seconds = (
                (metrics.end_time - metrics.start_time).total_seconds()
                if metrics.start_time
                else None
            )

            # Remove from worker's current tasks
            hostname_key = str(metrics.worker_hostname) if metrics.worker_hostname else "unknown"
            if hostname_key in self.worker_metrics:
                worker = self.worker_metrics[hostname_key]
                if task_id_key is not None and task_id_key in worker.current_tasks:
                    del worker.current_tasks[task_id_key]
                worker.tasks_executed += 1

            logger.info(
                f"Task completed: {metrics.task_name}[{task_id}] "
                f"in {metrics.duration_seconds:.2f}s"
            )

    def on_task_success(self, sender=None, result=None, **kwargs):
        """Handle task success event."""
        task_id = sender.request.id if sender else None

        if task_id and task_id in self.task_metrics:
            metrics = self.task_metrics[task_id]
            metrics.status = TaskStatus.SUCCESS
            metrics.result = str(result)[:1000] if result else None  # Limit result size

            # Update worker metrics
            if metrics.worker_hostname in self.worker_metrics:
                self.worker_metrics[metrics.worker_hostname].tasks_success += 1

            # Store performance metrics
            self.performance_buffer[metrics.task_name].append(metrics.duration_seconds)

            logger.info(f"Task success: {metrics.task_name}[{task_id}]")
            self._store_metric("task_success", metrics.to_dict())

            # Clean up old metrics after some time
            self._schedule_cleanup(task_id)

    def on_task_failure(
        self,
        sender=None,
        task_id=None,
        exception=None,
        args=None,
        kwargs=None,
        traceback=None,
        einfo=None,
        **kw,
    ):
        """Handle task failure event."""
        task_name = sender.name if sender else "unknown"

        if task_id and task_id in self.task_metrics:
            metrics = self.task_metrics[task_id]
            metrics.status = TaskStatus.FAILURE
            metrics.exception = str(exception) if exception else None
            metrics.traceback = str(einfo) if einfo else None

            # Update worker metrics
            if metrics.worker_hostname in self.worker_metrics:
                self.worker_metrics[metrics.worker_hostname].tasks_failed += 1
        else:
            # Create metrics for failed task if not exists
            # Handle None task_id
            if task_id is None:
                task_id = f"unknown-failed-{datetime.utcnow().timestamp()}"
            metrics = TaskMetrics(
                task_id=task_id,
                task_name=task_name,
                queue="unknown",
                status=TaskStatus.FAILURE,
                exception=str(exception) if exception else None,
                traceback=str(einfo) if einfo else None,
            )
            self.task_metrics[task_id] = metrics

        # Add to error buffer
        error_info = {
            "task_id": task_id,
            "task_name": task_name,
            "exception": str(exception),
            "traceback": str(einfo) if einfo else None,
            "timestamp": datetime.utcnow().isoformat(),
            "args": args,
            "kwargs": kwargs,
        }
        self.error_buffer.append(error_info)

        logger.error(f"Task failed: {task_name}[{task_id}] - {exception}", exc_info=True)

        self._store_metric("task_failure", metrics.to_dict())
        self._store_error(error_info)

        # Send to dead letter queue if max retries exceeded
        if metrics.retry_count >= metrics.max_retries:
            self._send_to_dlq(task_id, metrics)

    def on_task_retry(self, sender=None, task_id=None, reason=None, **kwargs):
        """Handle task retry event."""
        if task_id and task_id in self.task_metrics:
            metrics = self.task_metrics[task_id]
            metrics.status = TaskStatus.RETRY
            metrics.retry_count += 1

            # Update worker metrics
            if metrics.worker_hostname in self.worker_metrics:
                self.worker_metrics[metrics.worker_hostname].tasks_retried += 1

            logger.warning(
                f"Task retry: {metrics.task_name}[{task_id}] "
                f"(attempt {metrics.retry_count}/{metrics.max_retries}) - {reason}"
            )

            self._store_metric(
                "task_retry",
                {
                    "task_id": task_id,
                    "task_name": metrics.task_name,
                    "retry_count": metrics.retry_count,
                    "max_retries": metrics.max_retries,
                    "reason": str(reason),
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

    def on_task_rejected(self, sender=None, message=None, exc_info=None, **kwargs):
        """Handle task rejected event."""
        logger.error(f"Task rejected: {message}")
        self._store_metric(
            "task_rejected",
            {
                "message": str(message),
                "exception": str(exc_info) if exc_info else None,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    def on_task_revoked(
        self,
        sender=None,
        request=None,
        terminated=None,
        signum=None,
        expired=None,
        **kwargs,
    ):
        """Handle task revoked event."""
        task_id = request.id if request else None

        if task_id and task_id in self.task_metrics:
            metrics = self.task_metrics[task_id]
            metrics.status = TaskStatus.REVOKED

            logger.warning(
                f"Task revoked: {metrics.task_name}[{task_id}] "
                f"(terminated: {terminated}, expired: {expired})"
            )

            self._store_metric(
                "task_revoked",
                {
                    "task_id": task_id,
                    "task_name": metrics.task_name,
                    "terminated": terminated,
                    "expired": expired,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

    # Metric storage methods
    def _store_metric(self, metric_type: str, data: dict):
        """Store metric in Redis."""
        if not self.redis_client:
            return

        try:
            key = f"celery:metrics:{metric_type}:{datetime.utcnow().strftime('%Y%m%d')}"
            self.redis_client.lpush(key, json.dumps(data))
            self.redis_client.expire(key, 86400 * 7)  # Keep for 7 days
        except Exception as e:
            logger.error(f"Failed to store metric: {e}")

    def _store_error(self, error_info: dict):
        """Store error information in Redis."""
        if not self.redis_client:
            return

        try:
            key = f"celery:errors:{datetime.utcnow().strftime('%Y%m%d')}"
            self.redis_client.lpush(key, json.dumps(error_info))
            self.redis_client.expire(key, 86400 * 30)  # Keep for 30 days
        except Exception as e:
            logger.error(f"Failed to store error: {e}")

    def _send_to_dlq(self, task_id: str, metrics: TaskMetrics):
        """Send failed task to dead letter queue."""
        if not self.redis_client:
            return

        try:
            dlq_item = {
                "task_id": task_id,
                "task_name": metrics.task_name,
                "queue": metrics.queue,
                "args": metrics.args,
                "kwargs": metrics.kwargs,
                "exception": metrics.exception,
                "traceback": metrics.traceback,
                "retry_count": metrics.retry_count,
                "failed_at": datetime.utcnow().isoformat(),
            }

            key = "celery:dlq:items"
            self.redis_client.lpush(key, json.dumps(dlq_item))

            logger.info(f"Task sent to DLQ: {metrics.task_name}[{task_id}]")
        except Exception as e:
            logger.error(f"Failed to send task to DLQ: {e}")

    def _schedule_cleanup(self, task_id: str):
        """Schedule cleanup of task metrics after completion."""
        # In production, you might want to use a scheduler
        # For now, just clean up after 1 hour
        try:
            if self.redis_client:
                key = f"celery:metrics:cleanup"
                cleanup_time = (datetime.utcnow() + timedelta(hours=1)).timestamp()
                self.redis_client.zadd(key, {task_id: cleanup_time})
        except Exception as e:
            logger.error(f"Failed to schedule cleanup: {e}")

    # Query methods
    def get_worker_status(self) -> Dict[str, Any]:
        """Get current status of all workers."""
        return {hostname: metrics.to_dict() for hostname, metrics in self.worker_metrics.items()}

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific task."""
        if task_id in self.task_metrics:
            return self.task_metrics[task_id].to_dict()
        return None

    def get_performance_stats(self, task_name: str) -> Dict[str, Any]:
        """Get performance statistics for a task type."""
        durations = list(self.performance_buffer.get(task_name, []))

        if not durations:
            return {"message": "No performance data available"}

        return {
            "task_name": task_name,
            "count": len(durations),
            "min_duration": min(durations),
            "max_duration": max(durations),
            "avg_duration": sum(durations) / len(durations),
            "last_durations": durations[-10:],  # Last 10 executions
        }

    def get_error_summary(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent errors."""
        return list(self.error_buffer)[-limit:]

    def get_queue_lengths(self) -> Dict[str, int]:
        """Get current queue lengths."""
        if not self.redis_client:
            return {}

        try:
            from app.worker.config import CeleryConfig

            queue_lengths = {}

            for queue in CeleryConfig.task_queues:
                queue_name = queue.name
                # This would need actual queue inspection logic
                # For now, return placeholder
                queue_lengths[queue_name] = 0

            return queue_lengths
        except Exception as e:
            logger.error(f"Failed to get queue lengths: {e}")
            return {}

    def health_check(self) -> Dict[str, Any]:
        """Perform health check on Celery infrastructure."""
        health = {
            "healthy": True,
            "timestamp": datetime.utcnow().isoformat(),
            "workers": {},
            "queues": {},
            "errors": [],
        }

        # Check workers
        for hostname, metrics in self.worker_metrics.items():
            time_since_heartbeat = (datetime.utcnow() - metrics.last_heartbeat).total_seconds()

            worker_healthy = time_since_heartbeat < 60  # 1 minute threshold

            health["workers"][hostname] = {
                "healthy": worker_healthy,
                "last_heartbeat_seconds_ago": time_since_heartbeat,
                "current_tasks": len(metrics.current_tasks),
                "tasks_executed": metrics.tasks_executed,
            }

            if not worker_healthy:
                health["healthy"] = False
                health["errors"].append(
                    f"Worker {hostname} not responding (last heartbeat: {time_since_heartbeat:.0f}s ago)"
                )

        # Check Redis connection
        if self.redis_client:
            try:
                self.redis_client.ping()
                health["redis"] = {"healthy": True}
            except Exception as e:
                health["redis"] = {"healthy": False, "error": str(e)}
                health["healthy"] = False
                health["errors"].append(f"Redis connection failed: {e}")
        else:
            health["redis"] = {"healthy": False, "error": "Not connected"}
            health["healthy"] = False
            health["errors"].append("Redis not connected")

        # Check for recent failures
        recent_errors = self.get_error_summary(5)
        if recent_errors:
            health["recent_errors"] = len(recent_errors)

            # If too many recent errors, mark as unhealthy
            if len(recent_errors) >= 5:
                health["healthy"] = False
                health["errors"].append(f"Too many recent task failures: {len(recent_errors)}")

        return health


# Global monitor instance
monitor = CeleryMonitor()

# Auto-register signals when module is imported
monitor.register_signals()
