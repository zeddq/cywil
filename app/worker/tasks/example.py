"""
Example tasks demonstrating proper error handling and monitoring.
"""

import random
import time
from typing import Any, Dict

from app.core.logger_manager import get_logger
from app.worker.base_task import BaseTask, RetryableTask, with_task_monitoring
from app.worker.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(base=BaseTask, name="example.add")
@with_task_monitoring
def add(x: int, y: int) -> int:
    """
    Simple addition task with monitoring.

    Args:
        x: First number
        y: Second number

    Returns:
        Sum of x and y
    """
    time.sleep(2)  # Simulate processing
    result = x + y
    logger.info(f"Calculated {x} + {y} = {result}")
    return result


@celery_app.task(base=RetryableTask, name="example.unreliable_task")
def unreliable_task(failure_rate: float = 0.3) -> Dict[str, Any]:
    """
    Task that randomly fails to demonstrate retry mechanism.

    Args:
        failure_rate: Probability of failure (0.0 to 1.0)

    Returns:
        Success message or raises exception
    """
    logger.info(f"Running unreliable task with {failure_rate:.0%} failure rate")

    # Simulate random failure
    if random.random() < failure_rate:
        raise ConnectionError("Simulated connection failure")

    time.sleep(1)
    return {
        "status": "success",
        "message": "Task completed successfully",
        "timestamp": time.time(),
    }


@celery_app.task(base=BaseTask, name="example.long_running_task", soft_time_limit=10, time_limit=15)
def long_running_task(duration: int = 5) -> Dict[str, Any]:
    """
    Long-running task with time limits.

    Args:
        duration: How long to run in seconds

    Returns:
        Completion status
    """
    logger.info(f"Starting long-running task for {duration} seconds")

    start_time = time.time()

    # Simulate work with progress updates
    for i in range(duration):
        time.sleep(1)
        progress = (i + 1) / duration * 100
        logger.info(f"Progress: {progress:.0f}%")

    elapsed = time.time() - start_time

    return {
        "status": "completed",
        "duration": elapsed,
        "message": f"Task ran for {elapsed:.2f} seconds",
    }


@celery_app.task(
    base=BaseTask,
    name="example.batch_processor",
    rate_limit="10/m",  # Max 10 executions per minute
)
def batch_processor(items: list) -> Dict[str, Any]:
    """
    Process a batch of items with rate limiting.

    Args:
        items: List of items to process

    Returns:
        Processing results
    """
    logger.info(f"Processing batch of {len(items)} items")

    processed = []
    failed = []

    for item in items:
        try:
            # Simulate processing
            time.sleep(0.1)
            processed.append(item)
        except Exception as e:
            logger.error(f"Failed to process item {item}: {e}")
            failed.append({"item": item, "error": str(e)})

    return {
        "total": len(items),
        "processed": len(processed),
        "failed": len(failed),
        "failed_items": failed,
    }
