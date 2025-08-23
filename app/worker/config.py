"""
Celery configuration for microservices architecture.
"""
import os
from kombu import Queue, Exchange
from datetime import timedelta

class CeleryConfig:
    """Centralized Celery configuration for all workers."""
    
    # Broker settings
    broker_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    result_backend = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Serialization
    task_serializer = "json"
    accept_content = ["json"]
    result_serializer = "json"
    timezone = "UTC"
    enable_utc = True
    
    # Task execution settings
    task_track_started = True
    task_time_limit = 1800  # 30 minutes hard limit
    task_soft_time_limit = 1500  # 25 minutes soft limit
    task_acks_late = True  # Tasks acknowledged after completion
    worker_prefetch_multiplier = 1  # One task at a time for heavy processing
    
    # Result settings
    result_expires = 86400  # Results expire after 24 hours
    result_persistent = True  # Store results persistently
    
    # Retry settings
    task_default_retry_delay = 60  # 1 minute
    task_max_retries = 3
    
    # Define exchanges
    default_exchange = Exchange("default", type="direct", durable=True)
    priority_exchange = Exchange("priority", type="direct", durable=True)
    dlx_exchange = Exchange("dlx", type="direct", durable=True)
    
    # Define queues with different priorities and DLX
    task_queues = (
        # High priority queue for urgent tasks
        Queue(
            "high_priority",
            exchange=priority_exchange,
            routing_key="high",
            priority=10,
            arguments={
                "x-max-priority": 10,
                "x-dead-letter-exchange": "dlx",
                "x-dead-letter-routing-key": "failed.high"
            }
        ),
        # Default queue for normal operations
        Queue(
            "default",
            exchange=default_exchange,
            routing_key="default",
            priority=5,
            arguments={
                "x-dead-letter-exchange": "dlx",
                "x-dead-letter-routing-key": "failed.default"
            }
        ),
        # Ingestion queue for heavy PDF processing
        Queue(
            "ingestion",
            exchange=default_exchange,
            routing_key="ingestion",
            priority=3,
            arguments={
                "x-dead-letter-exchange": "dlx",
                "x-dead-letter-routing-key": "failed.ingestion"
            }
        ),
        # Embedding queue for vector generation
        Queue(
            "embeddings",
            exchange=default_exchange,
            routing_key="embeddings",
            priority=3,
            arguments={
                "x-dead-letter-exchange": "dlx",
                "x-dead-letter-routing-key": "failed.embeddings"
            }
        ),
        # Case management queue
        Queue(
            "case_management",
            exchange=default_exchange,
            routing_key="case",
            priority=7,
            arguments={
                "x-dead-letter-exchange": "dlx",
                "x-dead-letter-routing-key": "failed.case"
            }
        ),
        # Document generation queue
        Queue(
            "documents",
            exchange=default_exchange,
            routing_key="documents",
            priority=6,
            arguments={
                "x-dead-letter-exchange": "dlx",
                "x-dead-letter-routing-key": "failed.documents"
            }
        ),
        # Search queue for statute and ruling searches
        Queue(
            "search",
            exchange=default_exchange,
            routing_key="search",
            priority=8,
            arguments={
                "x-dead-letter-exchange": "dlx",
                "x-dead-letter-routing-key": "failed.search"
            }
        ),
        # Dead letter queue for failed tasks
        Queue(
            "dead_letter",
            exchange=dlx_exchange,
            routing_key="failed.*",
            arguments={
                "x-message-ttl": 604800000  # 7 days in milliseconds
            }
        ),
    )
    
    # Task routing
    task_routes = {
        # Ingestion tasks
        "worker.tasks.statute_tasks.*": {"queue": "ingestion"},
        "worker.tasks.ruling_tasks.*": {"queue": "ingestion"},
        "worker.tasks.ingestion_pipeline.*": {"queue": "ingestion"},
        
        # Embedding tasks
        "worker.tasks.embedding_tasks.*": {"queue": "embeddings"},
        
        # Case management tasks
        "worker.tasks.case_tasks.*": {"queue": "case_management"},
        
        # Document generation tasks
        "worker.tasks.document_tasks.*": {"queue": "documents"},
        
        # Search tasks
        "worker.tasks.search_tasks.*": {"queue": "search"},
        
        # Default routing
        "worker.tasks.example.*": {"queue": "default"},
    }
    
    # Beat schedule for periodic tasks
    beat_schedule = {
        "cleanup-expired-results": {
            "task": "worker.tasks.maintenance.cleanup_expired_results",
            "schedule": timedelta(hours=6),
            "options": {"queue": "default"}
        },
        "health-check-services": {
            "task": "worker.tasks.maintenance.health_check_all_services",
            "schedule": timedelta(minutes=5),
            "options": {"queue": "high_priority"}
        },
        "process-dead-letters": {
            "task": "worker.tasks.maintenance.process_dead_letter_queue",
            "schedule": timedelta(hours=1),
            "options": {"queue": "default"}
        },
        "update-embeddings-index": {
            "task": "worker.tasks.embedding_tasks.update_vector_indices",
            "schedule": timedelta(hours=24),
            "options": {"queue": "embeddings"}
        },
    }
    
    # Worker settings
    worker_hijack_root_logger = False
    worker_log_format = "[%(asctime)s: %(levelname)s/%(processName)s] %(message)s"
    worker_task_log_format = "[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s"
    
    # Monitoring
    worker_send_task_events = True
    task_send_sent_event = True
    
    # Error handling
    task_reject_on_worker_lost = True
    task_ignore_result = False
    
    @classmethod
    def get_queue_config(cls, queue_name: str) -> dict:
        """Get configuration for a specific queue."""
        queue_configs = {
            "high_priority": {
                "max_workers": 4,
                "prefetch_multiplier": 2,
            },
            "default": {
                "max_workers": 2,
                "prefetch_multiplier": 1,
            },
            "ingestion": {
                "max_workers": 1,  # Heavy processing, one at a time
                "prefetch_multiplier": 1,
            },
            "embeddings": {
                "max_workers": 2,
                "prefetch_multiplier": 1,
            },
            "case_management": {
                "max_workers": 3,
                "prefetch_multiplier": 2,
            },
            "documents": {
                "max_workers": 2,
                "prefetch_multiplier": 1,
            },
            "search": {
                "max_workers": 4,
                "prefetch_multiplier": 2,
            },
        }
        return queue_configs.get(queue_name, {
            "max_workers": 2,
            "prefetch_multiplier": 1,
        })