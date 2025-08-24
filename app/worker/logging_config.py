"""
Structured logging configuration for Celery workers.
"""

import json
import logging
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

from pythonjsonlogger import jsonlogger

from app.core.config_service import ConfigService


class CeleryTaskFilter(logging.Filter):
    """
    Add Celery task context to log records.
    """

    def filter(self, record):
        """Add Celery-specific fields to log record."""
        from celery import current_task

        # Add task context if available
        if current_task:
            record.task_id = getattr(current_task.request, 'id', None)
            record.task_name = getattr(current_task, 'name', None)
            record.task_queue = getattr(current_task.request, "queue", "unknown")
            record.task_hostname = getattr(current_task.request, "hostname", "unknown")
            record.task_retries = getattr(current_task.request, 'retries', 0)
        else:
            record.task_id = None
            record.task_name = None
            record.task_queue = None
            record.task_hostname = None
            record.task_retries = None

        return True


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """
    Custom JSON formatter for structured logging.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def add_fields(self, log_record, record, message_dict):
        """Add custom fields to the log record."""
        super().add_fields(log_record, record, message_dict)

        # Add timestamp
        log_record["timestamp"] = datetime.utcnow().isoformat()

        # Add log level
        log_record["level"] = record.levelname

        # Add logger name
        log_record["logger"] = record.name

        # Add source location
        log_record["source"] = {
            "file": record.pathname,
            "line": record.lineno,
            "function": record.funcName,
        }

        # Add process info
        log_record["process"] = {"pid": record.process, "name": record.processName}

        # Add thread info
        log_record["thread"] = {"id": record.thread, "name": record.threadName}

        # Add Celery task context if available
        if hasattr(record, "task_id") and getattr(record, 'task_id', None):
            log_record["celery"] = {
                "task_id": getattr(record, 'task_id', None),
                "task_name": getattr(record, 'task_name', None),
                "queue": getattr(record, 'task_queue', None),
                "hostname": getattr(record, 'task_hostname', None),
                "retries": getattr(record, 'task_retries', 0),
            }

        # Add exception info if present
        if record.exc_info:
            log_record["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "Unknown",
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Remove redundant fields
        for field in [
            "pathname",
            "lineno",
            "funcName",
            "process",
            "processName",
            "thread",
            "threadName",
            "exc_info",
            "task_id",
            "task_name",
            "task_queue",
            "task_hostname",
            "task_retries",
        ]:
            log_record.pop(field, None)


class ErrorAggregator:
    """
    Aggregate and batch errors for efficient logging.
    """

    def __init__(self, batch_size: int = 10, flush_interval: int = 60):
        """
        Initialize error aggregator.

        Args:
            batch_size: Number of errors to batch before flushing
            flush_interval: Seconds between automatic flushes
        """
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.errors = []
        self.last_flush = datetime.utcnow()

    def add_error(self, error_info: Dict[str, Any]):
        """Add an error to the batch."""
        self.errors.append({**error_info, "timestamp": datetime.utcnow().isoformat()})

        # Check if we should flush
        if len(self.errors) >= self.batch_size:
            self.flush()
        elif (datetime.utcnow() - self.last_flush).seconds > self.flush_interval:
            self.flush()

    def flush(self):
        """Flush accumulated errors."""
        if not self.errors:
            return

        # Log aggregated errors
        logger = logging.getLogger("celery.errors.aggregated")
        logger.error(
            json.dumps(
                {
                    "error_batch": self.errors,
                    "count": len(self.errors),
                    "batch_timestamp": datetime.utcnow().isoformat(),
                }
            )
        )

        # Clear errors
        self.errors = []
        self.last_flush = datetime.utcnow()


def configure_celery_logging(log_level: str = "INFO", json_logs: bool = True):
    """
    Configure structured logging for Celery workers.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_logs: Whether to use JSON format for logs
    """
    config = ConfigService()

    # Set log level
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    root_logger.handlers = []

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    if json_logs:
        # Use JSON formatter
        formatter = CustomJsonFormatter(
            "%(timestamp)s %(level)s %(name)s %(message)s", json_default=str
        )
    else:
        # Use standard formatter
        formatter = logging.Formatter(
            "[%(asctime)s: %(levelname)s/%(processName)s][%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console_handler.setFormatter(formatter)

    # Add Celery task filter
    task_filter = CeleryTaskFilter()
    console_handler.addFilter(task_filter)

    # Add handler to root logger
    root_logger.addHandler(console_handler)

    # Configure specific loggers
    loggers_config = {
        "celery": level,
        "celery.task": level,
        "celery.worker": level,
        "celery.beat": level,
        "celery.concurrency": logging.WARNING,
        "celery.redirected": logging.WARNING,
        "app.worker": level,
        "app.worker.tasks": level,
        "app.worker.monitoring": level,
    }

    for logger_name, logger_level in loggers_config.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(logger_level)
        logger.propagate = True

    # Suppress noisy loggers
    noisy_loggers = [
        "urllib3",
        "requests",
        "qdrant_client",
        "httpx",
        "httpcore",
        "openai",
        "anthropic",
    ]

    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Create error aggregator
    global error_aggregator
    error_aggregator = ErrorAggregator()

    logging.info(f"Celery logging configured: level={log_level}, json={json_logs}")


def log_task_event(
    event_type: str,
    task_name: str,
    task_id: str,
    details: Optional[Dict[str, Any]] = None,
):
    """
    Log a task event in structured format.

    Args:
        event_type: Type of event (started, completed, failed, etc.)
        task_name: Name of the task
        task_id: Task ID
        details: Additional event details
    """
    logger = logging.getLogger("celery.task.events")

    event_data = {
        "event_type": event_type,
        "task_name": task_name,
        "task_id": task_id,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if details:
        event_data.update(details)

    # Log at appropriate level based on event type
    if event_type in ["failed", "error", "timeout"]:
        logger.error(json.dumps(event_data))
    elif event_type in ["retry", "revoked"]:
        logger.warning(json.dumps(event_data))
    else:
        logger.info(json.dumps(event_data))


def log_performance_metric(
    task_name: str,
    duration: float,
    success: bool,
    details: Optional[Dict[str, Any]] = None,
):
    """
    Log task performance metrics.

    Args:
        task_name: Name of the task
        duration: Task execution duration in seconds
        success: Whether the task succeeded
        details: Additional performance details
    """
    logger = logging.getLogger("celery.performance")

    metric_data = {
        "task_name": task_name,
        "duration_seconds": duration,
        "success": success,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if details:
        metric_data.update(details)

    logger.info(json.dumps(metric_data))


def log_queue_metric(queue_name: str, length: int, details: Optional[Dict[str, Any]] = None):
    """
    Log queue metrics.

    Args:
        queue_name: Name of the queue
        length: Current queue length
        details: Additional queue details
    """
    logger = logging.getLogger("celery.queues")

    metric_data = {
        "queue_name": queue_name,
        "length": length,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if details:
        metric_data.update(details)

    logger.info(json.dumps(metric_data))


def log_worker_event(event_type: str, hostname: str, details: Optional[Dict[str, Any]] = None):
    """
    Log worker lifecycle events.

    Args:
        event_type: Type of event (started, stopped, heartbeat, etc.)
        hostname: Worker hostname
        details: Additional event details
    """
    logger = logging.getLogger("celery.worker.events")

    event_data = {
        "event_type": event_type,
        "hostname": hostname,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if details:
        event_data.update(details)

    logger.info(json.dumps(event_data))


# Initialize logging when module is imported
configure_celery_logging()
