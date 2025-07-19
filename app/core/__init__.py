"""
Core infrastructure modules for the AI Paralegal system.
"""
from .config_service import get_config, get_config_service, AppConfig, ConfigService
from .database_manager import DatabaseManager, UnitOfWork
from .exceptions import (
    ParalegalException,
    ConfigurationError,
    ServiceError,
    ToolError,
    ValidationError,
    DatabaseError,
    LLMError,
    DocumentError,
    SearchError,
    CaseError,
    ToolExecutionError,
    ToolNotFoundError,
    ServiceNotInitializedError,
    ServiceUnavailableError
)
from .llm_manager import LLMManager
from .service_interface import (
    ServiceInterface,
    ServiceContainer,
    ServiceLifecycleManager,
    ServiceStatus,
    HealthCheckResult,
)
from .tool_registry import (
    ToolRegistry,
    ToolCategory,
    ToolParameter,
    ToolDefinition,
    tool_registry
)

__all__ = [
    # Configuration
    'get_config',
    'get_config_service',
    'AppConfig',
    'ConfigService',
    
    # Database
    'DatabaseManager',
    'UnitOfWork',
    
    # Exceptions
    'ParalegalException',
    'ConfigurationError',
    'ServiceError',
    'ToolError',
    'ValidationError',
    'DatabaseError',
    'LLMError',
    'DocumentError',
    'SearchError',
    'CaseError',
    'ToolExecutionError',
    'ToolNotFoundError',
    'ServiceNotInitializedError',
    'ServiceUnavailableError',
    
    # LLM Management
    'LLMManager',
    
    # Service Infrastructure
    'ServiceInterface',
    'ServiceContainer',
    'ServiceLifecycleManager',
    'ServiceStatus',
    'HealthCheckResult',
    
    # Tool Registry
    'ToolRegistry',
    'ToolCategory',
    'ToolParameter',
    'ToolDefinition',
    'tool_registry'
]
