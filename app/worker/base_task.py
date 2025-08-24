"""
Base task class with enhanced error handling, retries, and monitoring.
"""

import json
import time
from datetime import datetime
from functools import wraps

from celery import Task
from celery.exceptions import Reject, Retry
from kombu.exceptions import OperationalError

from app.core.logger_manager import get_logger
from app.worker.service_registry import get_service

logger = get_logger(__name__)


class BaseTask(Task):
    """
    Enhanced base task with automatic retries, error handling, and monitoring.

    Features:
    - Automatic retries with exponential backoff
    - Circuit breaker pattern for failing services
    - Detailed error tracking
    - Performance monitoring
    - Dead letter queue handling
    """

    # Default retry configuration
    autoretry_for = (
        OperationalError,  # Network/connection errors
        ConnectionError,
        TimeoutError,
        IOError,
    )

    # Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, 64s...
    retry_backoff = True
    retry_backoff_max = 600  # Max 10 minutes between retries
    retry_jitter = True  # Add randomness to prevent thundering herd

    # Default max retries
    max_retries = 3

    # Task execution limits
    soft_time_limit = 300  # 5 minutes soft limit
    time_limit = 600  # 10 minutes hard limit

    # Rate limiting
    rate_limit = None  # e.g., '100/m' for 100 per minute

    # Circuit breaker settings
    circuit_breaker_errors = 5  # Errors before opening circuit
    circuit_breaker_timeout = 60  # Seconds before trying again
    _circuit_breaker_state = {}  # Track circuit state per task

    def __init__(self):
        """Initialize the base task."""
        super().__init__()
        self.start_time = None
        self.task_context = {}

    def before_start(self, task_id, args, kwargs):
        """Called before task execution starts."""
        self.start_time = time.time()
        self.task_context = {
            "task_id": task_id,
            "task_name": self.name,
            "args": args,
            "kwargs": kwargs,
            "started_at": datetime.utcnow().isoformat(),
        }

        logger.info(f"Starting task {self.name}[{task_id}] " f"with args={args}, kwargs={kwargs}")

        # Check circuit breaker
        if self._is_circuit_open():
            raise Reject(f"Circuit breaker open for {self.name}", requeue=True)

    def on_success(self, retval, task_id, args, kwargs):
        """Called on successful task completion."""
        duration = time.time() - self.start_time if self.start_time else 0

        logger.info(f"Task {self.name}[{task_id}] completed successfully " f"in {duration:.2f}s")

        # Reset circuit breaker on success
        self._reset_circuit_breaker()

        # Clean up context
        self.task_context = {}

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called on task failure (after all retries exhausted)."""
        duration = time.time() - self.start_time if self.start_time else 0

        logger.error(
            f"Task {self.name}[{task_id}] failed after "
            f"{self.request.retries}/{self.max_retries} retries "
            f"in {duration:.2f}s: {exc}",
            exc_info=True,
        )

        # Update circuit breaker
        self._record_circuit_failure()

        # Prepare detailed error info for dead letter queue
        error_details = {
            "task_id": task_id,
            "task_name": self.name,
            "args": args,
            "kwargs": kwargs,
            "exception": str(exc),
            "exception_type": type(exc).__name__,
            "traceback": str(einfo),
            "retries": self.request.retries,
            "max_retries": self.max_retries,
            "duration": duration,
            "failed_at": datetime.utcnow().isoformat(),
        }

        # Send to dead letter queue
        self._send_to_dlq(error_details)

        # Clean up context
        self.task_context = {}

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Called when task is retried."""
        current_retry = self.request.retries

        # Calculate backoff delay
        delay = self._calculate_backoff_delay(current_retry)

        logger.warning(
            f"Task {self.name}[{task_id}] retry "
            f"{current_retry}/{self.max_retries} "
            f"after {delay}s due to: {exc}"
        )

        # Store retry context for monitoring
        self.task_context["retry_count"] = current_retry
        self.task_context["retry_reason"] = str(exc)

    def retry(self, args=None, kwargs=None, exc=None, **options):
        """Enhanced retry with exponential backoff."""
        # Get current retry count
        current_retry = self.request.retries

        # Calculate delay with exponential backoff
        if self.retry_backoff:
            delay = self._calculate_backoff_delay(current_retry)
            options["countdown"] = delay

        # Add jitter to prevent thundering herd
        if self.retry_jitter and "countdown" in options:
            import random

            jitter = random.uniform(0, min(options["countdown"] * 0.1, 10))
            options["countdown"] += jitter

        return super().retry(args=args, kwargs=kwargs, exc=exc, **options)

    def _calculate_backoff_delay(self, retry_count: int) -> float:
        """Calculate exponential backoff delay."""
        if not self.retry_backoff:
            return 60  # Default 1 minute

        # Exponential backoff: 2^retry_count
        delay = min(2**retry_count, self.retry_backoff_max)
        return delay

    def _is_circuit_open(self) -> bool:
        """Check if circuit breaker is open."""
        state = self._circuit_breaker_state.get(self.name, {})

        if state.get("status") == "open":
            # Check if timeout has passed
            opened_at = state.get("opened_at", 0)
            if time.time() - opened_at > self.circuit_breaker_timeout:
                # Try half-open state
                self._circuit_breaker_state[self.name] = {
                    "status": "half-open",
                    "failures": 0,
                }
                return False
            return True

        return False

    def _record_circuit_failure(self):
        """Record a failure for circuit breaker."""
        state = self._circuit_breaker_state.get(self.name, {"status": "closed", "failures": 0})

        state["failures"] += 1

        if state["failures"] >= self.circuit_breaker_errors:
            state["status"] = "open"
            state["opened_at"] = time.time()
            logger.error(
                f"Circuit breaker opened for {self.name} " f"after {state['failures']} failures"
            )

        self._circuit_breaker_state[self.name] = state

    def _reset_circuit_breaker(self):
        """Reset circuit breaker on success."""
        if self.name in self._circuit_breaker_state:
            old_state = self._circuit_breaker_state[self.name].get("status")
            if old_state == "open" or old_state == "half-open":
                logger.info(f"Circuit breaker closed for {self.name}")

            self._circuit_breaker_state[self.name] = {"status": "closed", "failures": 0}

    def _send_to_dlq(self, error_details: dict):
        """Send failed task to dead letter queue."""
        try:
            # Import here to avoid circular dependency
            from app.worker.tasks.maintenance import process_dead_letter_queue

            # Send to DLQ processing task
            process_dead_letter_queue.apply_async(
                args=[error_details], queue="dead_letter", priority=0  # Lowest priority
            )
        except Exception as e:
            logger.error(f"Failed to send task to DLQ: {e}")


class RetryableTask(BaseTask):
    """Task that automatically retries on specific exceptions."""

    autoretry_for = (
        OperationalError,
        ConnectionError,
        TimeoutError,
        IOError,
        # Add your custom exceptions here
    )

    max_retries = 5
    retry_backoff = True
    retry_backoff_max = 300  # Max 5 minutes


class CriticalTask(BaseTask):
    """Task for critical operations with higher priority and monitoring."""

    max_retries = 10  # More retries for critical tasks
    retry_backoff_max = 60  # Shorter max backoff

    # No circuit breaker for critical tasks
    circuit_breaker_errors = float("inf")

    # Longer time limits
    soft_time_limit = 900  # 15 minutes
    time_limit = 1800  # 30 minutes

    # Track in separate queue
    queue = "high_priority"
    priority = 10


class LongRunningTask(BaseTask):
    """Task for long-running operations like PDF processing."""

    # Extended time limits
    soft_time_limit = 1800  # 30 minutes
    time_limit = 3600  # 1 hour

    # Fewer retries (expensive operations)
    max_retries = 2

    # Longer backoff
    retry_backoff_max = 1800  # 30 minutes

    # Lower priority
    queue = "ingestion"
    priority = 3

    # One task at a time
    rate_limit = "1/s"


def with_task_monitoring(func):
    """
    Decorator to add monitoring to any task function.

    Usage:
        @celery_app.task(base=BaseTask)
        @with_task_monitoring
        def my_task(x, y):
            return x + y
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        task_name = func.__name__

        try:
            logger.debug(f"Executing {task_name} with args={args}, kwargs={kwargs}")
            result = func(*args, **kwargs)
            duration = time.time() - start_time

            logger.info(f"{task_name} completed in {duration:.2f}s")

            # You could also send metrics here
            return result

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"{task_name} failed after {duration:.2f}s: {e}", exc_info=True)
            raise

    return wrapper


def idempotent_task(get_key_func):
    """
    Decorator to make tasks idempotent using Redis locking.

    Usage:
        @celery_app.task(base=BaseTask)
        @idempotent_task(lambda x, y: f"add:{x}:{y}")
        def add(x, y):
            return x + y
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            redis = get_service("redis")

            # Generate unique key for this task execution
            key = f"celery:idempotent:{get_key_func(*args, **kwargs)}"

            # Try to acquire lock with TTL
            lock_acquired = redis.set(key, "1", nx=True, ex=3600)  # 1 hour TTL

            if not lock_acquired:
                # Task already running or completed recently
                logger.info(f"Task {func.__name__} already processed for key {key}")

                # Try to get cached result
                result_key = f"{key}:result"
                cached_result = redis.get(result_key)

                if cached_result:
                    # Handle bytes from Redis
                    if isinstance(cached_result, bytes):
                        cached_result = cached_result.decode("utf-8")

                    return json.loads(cached_result)
                else:
                    # No cached result, task might still be running
                    raise Retry("Task already running, retrying later")

            try:
                # Execute task
                result = func(*args, **kwargs)

                # Cache result
                result_key = f"{key}:result"

                redis.set(result_key, json.dumps(result), ex=3600)

                return result

            except Exception as e:
                # Release lock on failure
                redis.delete(key)
                raise

        return wrapper

    return decorator
