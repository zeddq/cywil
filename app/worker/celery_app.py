
"""
Celery application with proper microservices configuration.
"""
from celery import Celery
from celery.signals import worker_ready, worker_shutting_down, task_failure, task_success, task_retry
import logging
import os

from app.worker.config import CeleryConfig

logger = logging.getLogger(__name__)

# Create Celery app with configuration
celery_app = Celery("ai_paralegal_worker")
celery_app.config_from_object(CeleryConfig)

# Include all task modules
celery_app.conf.imports = [
    "app.worker.tasks.example",
    "app.worker.tasks.ruling_tasks",
    "app.worker.tasks.statute_tasks",
    "app.worker.tasks.embedding_tasks",
    "app.worker.tasks.ingestion_pipeline",
    "app.worker.tasks.case_tasks",
    "app.worker.tasks.document_tasks",
    "app.worker.tasks.search_tasks",
    "app.worker.tasks.maintenance",
]

# Signal handlers for monitoring
@worker_ready.connect
def worker_ready_handler(sender, **kwargs):
    """Log when worker is ready to accept tasks."""
    logger.info(f"Worker {sender.hostname} is ready to accept tasks")

@worker_shutting_down.connect
def worker_shutting_down_handler(sender, **kwargs):
    """Log when worker is shutting down."""
    logger.info(f"Worker {sender.hostname} is shutting down")

@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, args=None, kwargs=None, traceback=None, einfo=None, **kw):
    """Log task failures for monitoring."""
    logger.error(f"Task {sender.name}[{task_id}] failed: {exception}")

@task_success.connect
def task_success_handler(sender=None, result=None, **kwargs):
    """Log task success for monitoring."""
    logger.info(f"Task {sender.name} completed successfully")

@task_retry.connect  
def task_retry_handler(sender=None, reason=None, **kwargs):
    """Log task retries for monitoring."""
    logger.warning(f"Task {sender.name} is being retried: {reason}")

if __name__ == "__main__":
    celery_app.start()
