"""
Core infrastructure modules for the AI Paralegal system.
"""

from .config_service import AppConfig, ConfigService, get_config
from .database_manager import DatabaseManager, UnitOfWork
from .exceptions import (
    CaseError,
    ConfigurationError,
    DatabaseError,
    DocumentError,
    LLMError,
    ParalegalException,
    SearchError,
    ServiceError,
    ServiceNotInitializedError,
    ServiceUnavailableError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ValidationError,
)
from .llm_manager import LLMManager
from .service_interface import (
    HealthCheckResult,
    ServiceContainer,
    ServiceInterface,
    ServiceLifecycleManager,
    ServiceStatus,
)
from .tool_registry import (
    ToolCategory,
    ToolDefinition,
    ToolParameter,
    ToolRegistry,
    tool_registry,
)

__all__ = [
    # Configuration
    "get_config",
    "AppConfig",
    "ConfigService",
    # Database
    "DatabaseManager",
    "UnitOfWork",
    # Exceptions
    "ParalegalException",
    "ConfigurationError",
    "ServiceError",
    "ToolError",
    "ValidationError",
    "DatabaseError",
    "LLMError",
    "DocumentError",
    "SearchError",
    "CaseError",
    "ToolExecutionError",
    "ToolNotFoundError",
    "ServiceNotInitializedError",
    "ServiceUnavailableError",
    # LLM Management
    "LLMManager",
    # Service Infrastructure
    "ServiceInterface",
    "ServiceContainer",
    "ServiceLifecycleManager",
    "ServiceStatus",
    "HealthCheckResult",
    # Tool Registry
    "ToolRegistry",
    "ToolCategory",
    "ToolParameter",
    "ToolDefinition",
    "tool_registry",
]
