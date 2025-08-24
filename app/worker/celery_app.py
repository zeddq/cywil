"""
Celery application with comprehensive monitoring, error handling, and structured logging.
"""

import os

from celery import Celery

from app.core.logger_manager import get_logger
from app.worker.config import CeleryConfig

# Initialize structured logging first
from app.worker.logging_config import configure_celery_logging

configure_celery_logging(
    log_level=os.getenv("CELERY_LOG_LEVEL", "INFO"),
    json_logs=os.getenv("CELERY_JSON_LOGS", "true").lower() == "true",
)

logger = get_logger(__name__)

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

# Import and initialize monitoring
# The monitor will auto-register all signals when imported

# Import service registry to register worker lifecycle signals
# This ensures services are initialized once per worker, not per task

logger.info(
    "Celery app initialized with comprehensive monitoring, structured logging, and service registry"
)

if __name__ == "__main__":
    celery_app.start()
