"""
Service wrapper to integrate Celery tasks with existing services.
Provides async/sync interface switching for microservices architecture.
"""

import threading
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, Optional, TypeVar

from celery.result import AsyncResult

from app.core.logger_manager import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class ExecutionMode(Enum):
    """Execution mode for service methods."""

    SYNC = "sync"  # Direct synchronous execution
    ASYNC = "async"  # Direct asynchronous execution
    CELERY_SYNC = "celery_sync"  # Celery with wait for result
    CELERY_ASYNC = "celery_async"  # Celery fire-and-forget


class CircuitBreakerState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failures exceeded threshold
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """Simple circuit breaker for Celery tasks."""

    def __init__(
        self, failure_threshold: int = 5, recovery_timeout: int = 60, success_threshold: int = 2
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before trying half-open
            success_threshold: Successes needed to close circuit
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self._lock = threading.Lock()

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function through circuit breaker."""
        with self._lock:
            if self.state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitBreakerState.HALF_OPEN
                    logger.info("Circuit breaker entering HALF_OPEN state")
                else:
                    raise Exception("Circuit breaker is OPEN - service unavailable")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try reset."""
        return self.last_failure_time is not None and datetime.now() - self.last_failure_time > timedelta(
            seconds=self.recovery_timeout
        )

    def _on_success(self):
        """Handle successful call."""
        with self._lock:
            self.failure_count = 0

            if self.state == CircuitBreakerState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.success_threshold:
                    self.state = CircuitBreakerState.CLOSED
                    self.success_count = 0
                    logger.info("Circuit breaker CLOSED - service recovered")

    def _on_failure(self):
        """Handle failed call."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now()
            self.success_count = 0

            if self.failure_count >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN
                logger.warning(f"Circuit breaker OPEN after {self.failure_count} failures")

    def reset(self):
        """Manually reset the circuit breaker."""
        with self._lock:
            self.state = CircuitBreakerState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_time = None
            logger.info("Circuit breaker manually reset")


class CeleryServiceWrapper:
    """
    Wrapper to make services work with Celery tasks.
    Provides transparent switching between direct and Celery execution.
    """

    def __init__(
        self,
        service_name: str,
        default_mode: ExecutionMode = ExecutionMode.CELERY_ASYNC,
        task_timeout: int = 300,
        result_ttl: int = 86400,
        use_circuit_breaker: bool = True,
    ):
        """
        Initialize the service wrapper.

        Args:
            service_name: Name of the service
            default_mode: Default execution mode
            task_timeout: Timeout for synchronous Celery tasks (seconds)
            result_ttl: Time to live for task results (seconds)
            use_circuit_breaker: Whether to use circuit breaker pattern
        """
        self.service_name = service_name
        self.default_mode = default_mode
        self.task_timeout = task_timeout
        self.result_ttl = result_ttl
        self._task_registry = {}
        self.use_circuit_breaker = use_circuit_breaker

        # Initialize circuit breakers per task
        self._circuit_breakers: Optional[Dict[str, CircuitBreaker]] = {} if use_circuit_breaker else None

    def register_task(
        self, method_name: str, task_name: str, queue: str = "default", priority: int = 5
    ):
        """
        Register a Celery task for a service method.

        Args:
            method_name: Name of the service method
            task_name: Celery task name
            queue: Queue to route the task to
            priority: Task priority
        """
        self._task_registry[method_name] = {
            "task_name": task_name,
            "queue": queue,
            "priority": priority,
        }
        logger.info(f"Registered task {task_name} for {self.service_name}.{method_name}")

    def _get_circuit_breaker(self, method_name: str) -> Optional[CircuitBreaker]:
        """Get or create circuit breaker for a method."""
        if not self.use_circuit_breaker:
            return None

        if self._circuit_breakers is not None and method_name not in self._circuit_breakers:
            self._circuit_breakers[method_name] = CircuitBreaker()

        return self._circuit_breakers[method_name] if self._circuit_breakers is not None else None

    def execute(
        self, method_name: str, *args, mode: Optional[ExecutionMode] = None, **kwargs
    ) -> Any:
        """
        Execute a service method either directly or via Celery.

        Args:
            method_name: Name of the method to execute
            mode: Execution mode (overrides default)
            *args: Method arguments
            **kwargs: Method keyword arguments

        Returns:
            Method result or AsyncResult for async Celery execution
        """
        execution_mode = mode or self.default_mode

        if method_name not in self._task_registry:
            raise ValueError(f"Method {method_name} not registered for Celery execution")

        task_config = self._task_registry[method_name]
        circuit_breaker = self._get_circuit_breaker(method_name)

        # For async mode, circuit breaker only checks if we can queue
        if execution_mode == ExecutionMode.CELERY_ASYNC:
            if circuit_breaker:
                try:
                    circuit_breaker.call(self._check_worker_availability)
                except Exception as e:
                    logger.error(f"Circuit breaker prevented task execution: {e}")
                    raise
            return self._execute_celery_async(task_config, *args, **kwargs)

        # For sync mode, circuit breaker wraps the entire execution
        elif execution_mode == ExecutionMode.CELERY_SYNC:
            if circuit_breaker:
                return circuit_breaker.call(self._execute_celery_sync, task_config, *args, **kwargs)
            else:
                return self._execute_celery_sync(task_config, *args, **kwargs)
        else:
            raise ValueError(f"Unsupported execution mode: {execution_mode}")

    def _check_worker_availability(self) -> bool:
        """Check if Celery workers are available."""
        try:
            from app.worker.celery_app import celery_app

            inspect = celery_app.control.inspect()
            active_workers = inspect.active_queues()

            if not active_workers:
                logger.warning("No active Celery workers found!")
                return False

            logger.debug(f"Found {len(active_workers)} active workers")
            return True
        except Exception as e:
            logger.error(f"Failed to check worker availability: {e}")
            return False

    def _execute_celery_async(self, task_config: Dict[str, Any], *args, **kwargs) -> AsyncResult:
        """Execute task asynchronously via Celery."""
        from app.worker.celery_app import celery_app

        # Check worker availability before queuing
        if not self._check_worker_availability():
            logger.warning(f"Queuing task {task_config['task_name']} but no workers available")

        result = celery_app.send_task(
            task_config["task_name"],
            args=args,
            kwargs=kwargs,
            queue=task_config["queue"],
            priority=task_config["priority"],
            expires=self.result_ttl,
        )

        logger.info(f"Queued task {task_config['task_name']} with ID {result.id}")
        return result

    def _execute_celery_sync(self, task_config: Dict[str, Any], *args, **kwargs) -> Any:
        """Execute task via Celery and wait for result."""
        from celery.exceptions import TaskRevokedError, TimeoutError

        result = self._execute_celery_async(task_config, *args, **kwargs)

        try:
            # Wait for result with timeout
            return result.get(timeout=self.task_timeout)
        except TimeoutError:
            logger.error(f"Task {task_config['task_name']} timed out after {self.task_timeout}s")
            # Attempt to revoke the task
            result.revoke(terminate=True)
            raise TimeoutError(f"Task {result.id} exceeded timeout of {self.task_timeout} seconds")
        except TaskRevokedError:
            logger.error(f"Task {task_config['task_name']} was revoked")
            raise
        except Exception as e:
            logger.error(f"Task {task_config['task_name']} failed: {e}", exc_info=True)
            # Check if workers are available
            self._check_worker_availability()
            raise


class ServiceProxy:
    """
    Proxy for service classes that routes method calls through Celery.
    """

    def __init__(
        self,
        service_instance: Any,
        wrapper: CeleryServiceWrapper,
        mode: ExecutionMode = ExecutionMode.CELERY_ASYNC,
    ):
        """
        Initialize service proxy.

        Args:
            service_instance: The actual service instance
            wrapper: CeleryServiceWrapper instance
            mode: Default execution mode
        """
        self._service = service_instance
        self._wrapper = wrapper
        self._mode = mode

    def __getattr__(self, name: str) -> Callable:
        """
        Intercept method calls and route through wrapper.
        """
        # Check if the service has this attribute
        if not hasattr(self._service, name):
            raise AttributeError(
                f"Service {self._service.__class__.__name__} has no attribute {name}"
            )

        attr = getattr(self._service, name)

        # If it's not a method, return it directly
        if not callable(attr):
            return attr

        # If it's a registered Celery task, wrap it
        if name in self._wrapper._task_registry:

            def wrapped_method(*args, **kwargs):
                return self._wrapper.execute(name, *args, mode=self._mode, **kwargs)

            return wrapped_method

        # Otherwise, call the method directly
        return attr


def celery_task(
    task_name: str,
    queue: str = "default",
    priority: int = 5,
    mode: ExecutionMode = ExecutionMode.CELERY_ASYNC,
):
    """
    Decorator to mark a service method for Celery execution.

    Args:
        task_name: Celery task name
        queue: Queue to route the task to
        priority: Task priority
        mode: Default execution mode
    """

    def decorator(func: Callable) -> Callable:
        func._celery_config = {
            "task_name": task_name,
            "queue": queue,
            "priority": priority,
            "mode": mode,
        }
        return func

    return decorator


class CeleryServiceManager:
    """
    Manager for all Celery-enabled services.
    """

    def __init__(self):
        """Initialize the service manager."""
        self._services = {}
        self._wrappers = {}
        self._proxies = {}

    def register_service(
        self,
        service_name: str,
        service_instance: Any,
        default_mode: ExecutionMode = ExecutionMode.CELERY_ASYNC,
    ) -> ServiceProxy:
        """
        Register a service for Celery execution.

        Args:
            service_name: Name of the service
            service_instance: Service instance
            default_mode: Default execution mode

        Returns:
            ServiceProxy for the service
        """
        # Create wrapper
        wrapper = CeleryServiceWrapper(service_name=service_name, default_mode=default_mode)

        # Auto-register methods with @celery_task decorator
        for method_name in dir(service_instance):
            if not method_name.startswith("_"):
                method = getattr(service_instance, method_name)
                if hasattr(method, "_celery_config"):
                    config = method._celery_config
                    wrapper.register_task(
                        method_name=method_name,
                        task_name=config["task_name"],
                        queue=config["queue"],
                        priority=config["priority"],
                    )

        # Create proxy
        proxy = ServiceProxy(service_instance=service_instance, wrapper=wrapper, mode=default_mode)

        # Store references
        self._services[service_name] = service_instance
        self._wrappers[service_name] = wrapper
        self._proxies[service_name] = proxy

        logger.info(f"Registered service {service_name} with Celery manager")

        return proxy

    def get_service(self, service_name: str) -> ServiceProxy:
        """
        Get a service proxy by name.

        Args:
            service_name: Name of the service

        Returns:
            ServiceProxy for the service
        """
        if service_name not in self._proxies:
            raise ValueError(f"Service {service_name} not registered")
        return self._proxies[service_name]

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Get the status of a Celery task.

        Args:
            task_id: Celery task ID

        Returns:
            Task status information
        """
        from app.worker.celery_app import celery_app

        result = AsyncResult(task_id, app=celery_app)

        return {
            "task_id": task_id,
            "status": result.status,
            "result": result.result if result.ready() else None,
            "traceback": result.traceback if result.failed() else None,
            "info": result.info,
        }

    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a Celery task.

        Args:
            task_id: Celery task ID

        Returns:
            True if task was cancelled
        """
        from app.worker.celery_app import celery_app

        result = AsyncResult(task_id, app=celery_app)
        result.revoke(terminate=True)

        logger.info(f"Cancelled task {task_id}")
        return True

    def get_queue_stats(self) -> Dict[str, Any]:
        """
        Get statistics for all Celery queues.

        Returns:
            Queue statistics
        """
        from app.worker.celery_app import celery_app

        inspect = celery_app.control.inspect()

        return {
            "active_queues": inspect.active_queues(),
            "scheduled": inspect.scheduled(),
            "active": inspect.active(),
            "reserved": inspect.reserved(),
            "stats": inspect.stats(),
        }


# Global service manager instance
celery_service_manager = CeleryServiceManager()
