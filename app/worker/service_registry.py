"""
Worker Service Registry - Manages service lifecycle for Celery workers.

This module ensures services are initialized once per worker process and
shared across all tasks within that worker, fixing the critical architectural
flaw where each task created new service instances.
"""

import asyncio
import redis
from threading import Lock
from typing import Any, Dict, Optional

from celery.signals import worker_process_init, worker_process_shutdown

from app.core.config_service import ConfigService
from app.core.database_manager import DatabaseManager
from app.core.llm_manager import LLMManager
from app.core.logger_manager import get_logger
from app.repositories.case_repository import CaseRepository
# from app.repositories.ruling_repository import RulingRepository  # TODO: Create this repository
# from app.repositories.statute_repository import StatuteRepository  # TODO: Create this repository
from app.repositories.user_repository import UserRepository
from app.services.case_management_service import CaseManagementService
from app.services.document_generation_service import DocumentGenerationService
# from app.services.embedding_service import EmbeddingService  # TODO: Create this service
# from app.services.ruling_ingestion_service import RulingIngestionService  # TODO: Create this service
# from app.services.statute_ingestion_service import StatuteIngestionService  # TODO: Create this service
from app.services.statute_search_service import StatuteSearchService
from app.services.supreme_court_service import SupremeCourtService
# from app.services.user_service import UserService  # TODO: Create this service

logger = get_logger(__name__)


class WorkerServiceRegistry:
    """
    Thread-safe registry for worker-level service instances.
    Ensures services are initialized once and shared across all tasks.
    """

    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._initialized = False
        self._lock = Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _run_async(self, coro):
        """Helper to run async code in sync context."""
        if not self._loop:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop.run_until_complete(coro)

    async def _initialize_services(self):
        """Initialize all services with proper lifecycle management."""
        logger.info("Initializing worker services...")

        try:
            # Core services
            self._services["config"] = ConfigService()
            config_service = self._services["config"]

            # Database manager
            self._services["db_manager"] = DatabaseManager(config_service)
            db_manager = self._services["db_manager"]
            await db_manager.initialize()

            # Redis client
            self._services["redis_pool"] = redis.ConnectionPool.from_url(
                config_service.config.redis.url,
                decode_responses=True,
                max_connections=50,
                health_check_interval=30,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            self._services["redis"] = redis.Redis(connection_pool=self._services["redis_pool"])
            self._services["redis"].ping()

            # LLM manager
            self._services["llm_manager"] = LLMManager(config_service)
            llm_manager = self._services["llm_manager"]
            await llm_manager.initialize()

            # Repositories
            self._services["case_repository"] = CaseRepository()
            # self._services["ruling_repository"] = RulingRepository(db_manager)  # TODO: Create repository
            # self._services["statute_repository"] = StatuteRepository(db_manager)  # TODO: Create repository
            self._services["user_repository"] = UserRepository()

            # Services
            # self._services["embedding_service"] = EmbeddingService(config_service)  # TODO: Create service
            # embedding_service = self._services["embedding_service"]
            # await embedding_service.initialize()

            self._services["statute_search"] = StatuteSearchService(config_service, llm_manager)
            statute_search = self._services["statute_search"]
            await statute_search.initialize()

            self._services["supreme_court"] = SupremeCourtService(db_manager, config_service, llm_manager)
            supreme_court = self._services["supreme_court"]
            await supreme_court.initialize()

            self._services["document_generation"] = DocumentGenerationService(
                db_manager, statute_search, supreme_court
            )
            doc_service = self._services["document_generation"]
            await doc_service.initialize()

            # Case management service
            self._services["case_service"] = (
                CaseManagementService(db_manager).with_case_repository(self._services["case_repository"])  # type: ignore[reportUnknownMemberType]
            )
            case_service = self._services["case_service"]
            # await case_service.initialize()  # No explicit initialize needed currently

            # self._services["user_service"] = UserService(self._services["user_repository"])  # TODO: Create service
            # user_service = self._services["user_service"]
            # await user_service.initialize()

            # Ingestion services (TODO: Create these services)
            # self._services["ruling_ingestion"] = RulingIngestionService(
            #     db_manager, None, llm_manager, config_service  # TODO: Pass embedding_service when available
            # )
            # ruling_ingestion = self._services["ruling_ingestion"]
            # await ruling_ingestion.initialize()

            # self._services["statute_ingestion"] = StatuteIngestionService(
            #     db_manager, None, config_service  # TODO: Pass embedding_service when available
            # )
            # statute_ingestion = self._services["statute_ingestion"]
            # await statute_ingestion.initialize()

            logger.info("All worker services initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize worker services: {e}", exc_info=True)
            raise

    def initialize(self):
        """Initialize all services (called once per worker process)."""
        with self._lock:
            if self._initialized:
                logger.warning("Services already initialized for this worker")
                return

            try:
                self._run_async(self._initialize_services())
                self._initialized = True
                logger.info("Worker service registry initialized")
            except Exception as e:
                logger.error(f"Failed to initialize service registry: {e}")
                raise

    async def _shutdown_services(self):
        """Shutdown all services with proper cleanup."""
        logger.info("Shutting down worker services...")

        shutdown_order = [
            "document_generation",
            "case_service",
            "user_service",
            "ruling_ingestion",
            "statute_ingestion",
            "supreme_court",
            "statute_search",
            "embedding_service",
            "llm_manager",
            "db_manager",
        ]

        for service_name in shutdown_order:
            if service_name in self._services:
                service = self._services[service_name]
                if hasattr(service, "shutdown"):
                    try:
                        await service.shutdown()
                        logger.info(f"Shutdown {service_name}")
                    except Exception as e:
                        logger.error(f"Error shutting down {service_name}: {e}")

        # Close Redis resources last
        try:
            if "redis" in self._services and self._services["redis"] is not None:
                try:
                    self._services["redis"].close()
                except Exception as e:
                    logger.error(f"Error closing Redis client: {e}")
            if "redis_pool" in self._services and self._services["redis_pool"] is not None:
                try:
                    self._services["redis_pool"].disconnect()
                except Exception as e:
                    logger.error(f"Error disconnecting Redis pool: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during Redis shutdown: {e}")

        self._services.clear()
        logger.info("All worker services shut down")

    def shutdown(self):
        """Shutdown all services (called when worker stops)."""
        with self._lock:
            if not self._initialized:
                return

            try:
                self._run_async(self._shutdown_services())
                if self._loop:
                    self._loop.close()
                    self._loop = None
                self._initialized = False
                logger.info("Worker service registry shutdown complete")
            except Exception as e:
                logger.error(f"Error during service registry shutdown: {e}")

    def get(self, service_name: str) -> Any:
        """Get a service instance by name."""
        if not self._initialized:
            raise RuntimeError("Service registry not initialized")

        if service_name not in self._services:
            raise KeyError(f"Service '{service_name}' not found in registry")

        return self._services[service_name]

    @property
    def config_service(self) -> ConfigService:
        return self.get("config")

    @property
    def db_manager(self) -> DatabaseManager:
        return self.get("db_manager")

    @property
    def llm_manager(self) -> LLMManager:
        return self.get("llm_manager")

    @property
    def document_generation(self) -> DocumentGenerationService:
        return self.get("document_generation")

    @property
    def statute_search(self) -> StatuteSearchService:
        return self.get("statute_search")

    @property
    def supreme_court(self) -> SupremeCourtService:
        return self.get("supreme_court")

    @property
    def case_service(self) -> CaseManagementService:
        return self.get("case_service")

    @property
    def redis(self) -> redis.Redis:
        return self.get("redis")

    def health_check(self) -> Dict[str, Any]:
        """Check health of all services."""
        if not self._initialized:
            return {"status": "unhealthy", "reason": "Not initialized"}

        health_status = {"status": "healthy", "services": {}}

        for name, service in self._services.items():
            if hasattr(service, "health_check"):
                try:
                    result = self._run_async(service.health_check())
                    health_status["services"][name] = result
                except Exception as e:
                    health_status["services"][name] = {
                        "status": "unhealthy",
                        "error": str(e),
                    }
                    health_status["status"] = "degraded"

        return health_status


# Global registry instance (one per worker process)
worker_services = WorkerServiceRegistry()


# Celery signal handlers
@worker_process_init.connect
def initialize_worker_services(sender=None, **kwargs):
    """
    Initialize services when a worker process starts.
    This ensures services are created once per worker, not per task.
    """
    logger.info("Worker process starting - initializing services")
    try:
        worker_services.initialize()
        logger.info("Worker services initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize worker services: {e}", exc_info=True)
        raise


@worker_process_shutdown.connect
def shutdown_worker_services(sender=None, **kwargs):
    """
    Cleanup services when a worker process stops.
    This ensures proper resource cleanup and connection closing.
    """
    logger.info("Worker process stopping - shutting down services")
    try:
        worker_services.shutdown()
        logger.info("Worker services shut down successfully")
    except Exception as e:
        logger.error(f"Error during worker service shutdown: {e}", exc_info=True)


def get_service(service_name: str) -> Any:
    """
    Get a service from the worker registry.
    This is the main interface for tasks to access services.
    """
    return worker_services.get(service_name)


def get_worker_services() -> WorkerServiceRegistry:
    """Get the worker service registry instance."""
    return worker_services
