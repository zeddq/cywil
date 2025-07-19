"""
Base service interface and dependency injection framework.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, TypeVar, Generic, Type
from enum import Enum
import logging
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)

class ServiceStatus(Enum):
    """Service health status"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    INITIALIZING = "initializing"
    SHUTTING_DOWN = "shutting_down"


@dataclass
class HealthCheckResult:
    """Result of a service health check"""
    status: ServiceStatus
    message: str = ""
    details: Dict[str, Any] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.details is None:
            self.details = {}


class ServiceInterface(ABC):
    """
    Abstract base class for all services in the system.
    Provides common functionality for initialization, health checks, and lifecycle management.
    """
    
    def __init__(self, name: str):
        self.name = name
        self._status = ServiceStatus.INITIALIZING
        self._initialized = False
        logger.info(f"Creating service: {name}")
    
    async def initialize(self) -> None:
        """
        Initialize the service and its dependencies.
        Must be called before using the service.
        """
        if self._initialized:
            logger.warning(f"Service {self.name} already initialized")
            return
        
        try:
            logger.info(f"Initializing service: {self.name}")
            
            # Service-specific initialization
            await self._initialize_impl()
            
            self._initialized = True
            self._status = ServiceStatus.HEALTHY
            logger.info(f"Service {self.name} initialized successfully")
            
        except Exception as e:
            self._status = ServiceStatus.UNHEALTHY
            logger.error(f"Failed to initialize service {self.name}: {e}")
            raise
    
    @abstractmethod
    async def _initialize_impl(self) -> None:
        """Service-specific initialization logic"""
        pass
    
    async def shutdown(self) -> None:
        """
        Gracefully shutdown the service.
        """
        if not self._initialized:
            return
        
        try:
            logger.info(f"Shutting down service: {self.name}")
            self._status = ServiceStatus.SHUTTING_DOWN
            
            # Service-specific shutdown
            await self._shutdown_impl()
            
            self._initialized = False
            logger.info(f"Service {self.name} shutdown successfully")
            
        except Exception as e:
            logger.error(f"Error shutting down service {self.name}: {e}")
            raise
    
    @abstractmethod
    async def _shutdown_impl(self) -> None:
        """Service-specific shutdown logic"""
        pass
    
    async def health_check(self) -> HealthCheckResult:
        """
        Check the health of the service and its dependencies.
        """
        if not self._initialized:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message="Service not initialized"
            )
        
        try:
            # Service-specific health check
            service_result = await self._health_check_impl()
            
            overall_status = ServiceStatus.HEALTHY
            # Combine results
            if service_result.status == ServiceStatus.UNHEALTHY:
                overall_status = ServiceStatus.UNHEALTHY
            elif service_result.status == ServiceStatus.DEGRADED and overall_status == ServiceStatus.HEALTHY:
                overall_status = ServiceStatus.DEGRADED
            
            return HealthCheckResult(
                status=overall_status,
                message=service_result.message,
                details=service_result.details
            )
            
        except Exception as e:
            logger.error(f"Health check failed for service {self.name}: {e}")
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message=f"Health check error: {str(e)}"
            )
    
    @abstractmethod
    async def _health_check_impl(self) -> HealthCheckResult:
        """Service-specific health check logic"""
        pass
    
    @property
    def status(self) -> ServiceStatus:
        """Get current service status"""
        return self._status
    
    @property
    def is_healthy(self) -> bool:
        """Check if service is healthy"""
        return self._status == ServiceStatus.HEALTHY
    
    @asynccontextmanager
    async def transaction(self):
        """
        Context manager for service transactions.
        Override in services that support transactions.
        """
        yield self


T = TypeVar('T', bound=ServiceInterface)


class ServiceContainer:
    """
    Dependency injection container for managing service instances.
    """
    
    def __init__(self):
        self._services: Dict[Type[ServiceInterface], ServiceInterface] = {}
        self._singletons: Dict[Type[ServiceInterface], ServiceInterface] = {}
        self._factories: Dict[Type[ServiceInterface], callable] = {}
        logger.info("Service container initialized")
    
    def register_singleton(self, service_type: Type[T], instance: T) -> None:
        """Register a singleton service instance"""
        self._singletons[service_type] = instance
        logger.info(f"Registered singleton service: {service_type.__name__}")
    
    def register_factory(self, service_type: Type[T], factory: callable) -> None:
        """Register a factory function for creating service instances"""
        self._factories[service_type] = factory
        logger.info(f"Registered factory for service: {service_type.__name__}")
    
    def get(self, service_type: Type[T]) -> T:
        """Get a service instance"""
        # Check singletons first
        if service_type in self._singletons:
            return self._singletons[service_type]
        
        # Check if we have a factory
        if service_type in self._factories:
            instance = self._factories[service_type]()
            return instance
        
        raise ValueError(f"Service {service_type.__name__} not registered")
    
    async def initialize_all(self) -> None:
        """Initialize all singleton services"""
        for service in self._singletons.values():
            if not service._initialized:
                await service.initialize()
    
    async def shutdown_all(self) -> None:
        """Shutdown all services"""
        for service in self._singletons.values():
            await service.shutdown()
    
    async def health_check_all(self) -> Dict[str, HealthCheckResult]:
        """Run health checks on all services"""
        results = {}
        for service_type, service in self._singletons.items():
            results[service_type.__name__] = await service.health_check()
        return results


class ServiceLifecycleManager:
    """
    Manages the lifecycle of all services in the application.
    """
    
    def __init__(self, container: ServiceContainer):
        self.container = container
    
    async def startup(self):
        """Application startup routine"""
        logger.info("Starting application services...")
        await self.container.initialize_all()
        
        # Run health checks
        health_results = await self.container.health_check_all()
        unhealthy = [(name, result) for name, result in health_results.items() 
                     if result.status == ServiceStatus.UNHEALTHY]
        
        if unhealthy:
            logger.error(f"Unhealthy services detected: {unhealthy}")
            raise RuntimeError(f"Some services failed to start: {unhealthy}")
        
        logger.info("All services started successfully")
    
    async def shutdown(self):
        """Application shutdown routine"""
        logger.info("Shutting down application services...")
        await self.container.shutdown_all()
        logger.info("All services shut down successfully")

    def inject_service(self, service_type: Type[T]) -> T:
        """Dependency injection decorator/function"""
        return self.container.get(service_type)
