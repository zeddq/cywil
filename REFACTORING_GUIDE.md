# AI Paralegal POC - Refactoring Guide

This guide documents the refactoring from the monolithic architecture to a modular, service-based architecture.

## Overview of Changes

### Phase 1: Foundation Components

1. **Configuration Management** (`app/core/config_service.py`)
   - Hierarchical configuration with validation
   - Environment-specific settings
   - Type-safe configuration access
   - Backward compatibility through legacy wrapper

2. **Tool Registry** (`app/core/tool_registry.py`)
   - Dynamic tool registration with decorators
   - Automatic OpenAI schema generation
   - Tool validation and execution
   - Middleware support

3. **Service Infrastructure** (`app/core/service_interface.py`)
   - Base service class with lifecycle management
   - Health check framework
   - Dependency injection container
   - Service status tracking

4. **Database Management** (`app/core/database_manager.py`)
   - Connection pooling
   - Async context managers
   - Unit of Work pattern
   - Transaction management

### Phase 2: Service Decomposition

The monolithic `tools.py` (790+ lines) has been decomposed into:

1. **StatuteSearchService** (`app/services/statute_search_service.py`)
   - Hybrid vector/keyword search for KC/KPC
   - Article-specific searches
   - Passage summarization

2. **DocumentGenerationService** (`app/services/document_generation_service.py`)
   - Template-based document creation
   - AI enhancement with Supreme Court rulings
   - Document validation

3. **CaseManagementService** (`app/services/case_management_service.py`)
   - Case CRUD operations
   - Deadline computation
   - Reminder scheduling

4. **SupremeCourtService** (`app/services/supreme_court_service.py`)
   - SN rulings semantic search
   - Docket-specific queries
   - Ruling analysis and summarization

### Additional Infrastructure

1. **LLM Manager** (`app/core/llm_manager.py`)
   - Centralized LLM client management
   - Embedding generation with caching
   - Retry logic and error handling

2. **Exception Hierarchy** (`app/core/exceptions.py`)
   - Comprehensive error types
   - Structured error information
   - Service-specific exceptions

## Migration Steps

### Step 1: Update Configuration

Replace direct usage of `settings`:

```python
# Old
from app.config import settings
api_key = settings.openai_api_key

# New
from app.core import get_config
config = get_config()
api_key = config.openai.api_key.get_secret_value()
```

### Step 2: Initialize Services

In your application startup:

```python
from app.services import initialize_services

async def startup():
    lifecycle_manager = initialize_services()
    await lifecycle_manager.startup()

async def shutdown():
    await lifecycle_manager.shutdown()
```

### Step 3: Use Tool Registry

Replace direct tool function calls:

```python
# Old
from app.tools import search_statute
result = await search_statute(query="art. 415 KC")

# New
from app.services import execute_tool
result = await execute_tool("search_statute", {"query": "art. 415 KC"})
```

### Step 4: Update Orchestrator

See `app/orchestrator_refactored.py` for a complete example of how to refactor the orchestrator to use:
- Service injection
- Tool registry
- Streaming handler separation
- Conversation management

### Step 5: Error Handling

Use the new exception hierarchy:

```python
from app.core.exceptions import (
    ToolExecutionError,
    ServiceNotInitializedError,
    ValidationError
)

try:
    result = await execute_tool(name, args)
except ToolExecutionError as e:
    logger.error(f"Tool {e.tool_name} failed: {e.message}")
    # Handle error with recovery logic
```

## Benefits of Refactoring

1. **Improved Testability**
   - Services can be tested in isolation
   - Mock dependencies easily
   - Clear interfaces

2. **Better Maintainability**
   - Single responsibility principle
   - Clear separation of concerns
   - Consistent patterns

3. **Enhanced Scalability**
   - Services can be scaled independently
   - Better resource management
   - Connection pooling

4. **Easier Extension**
   - Add new tools via decorators
   - Implement new services following patterns
   - Middleware for cross-cutting concerns

## Testing the Refactored Code

Example test structure:

```python
import pytest
from app.core import service_container
from app.services import StatuteSearchService

@pytest.fixture
async def statute_service():
    service = StatuteSearchService()
    await service.initialize()
    yield service
    await service.shutdown()

async def test_search_statute(statute_service):
    results = await statute_service.search_statute("art. 415 KC")
    assert len(results) > 0
    assert results[0]["article"] == "415"
```

## Performance Considerations

1. **Embedding Cache**: The LLMManager includes an in-memory cache for embeddings
2. **Connection Pooling**: Database connections are pooled and reused
3. **Lazy Initialization**: Services are initialized only when needed
4. **Async Operations**: All I/O operations are async for better concurrency

## Rollback Plan

The refactoring maintains backward compatibility:

1. The original `config.py` wraps the new configuration
2. Tool functions can still be imported directly (though deprecated)
3. Database schemas remain unchanged
4. API contracts are preserved

## Phase 3: Orchestrator Refactoring (Complete)

The orchestrator has been completely refactored with proper separation of concerns:

1. **StreamingHandler** (`app/core/streaming_handler.py`)
   - Cleanly separates OpenAI streaming protocol handling
   - Support for stream processors (middleware pattern)
   - Built-in processors: ContentAccumulator, MetricsCollector

2. **ConversationManager** (`app/core/conversation_manager.py`)
   - Redis-backed conversation state (with in-memory fallback)
   - Conversation history persistence
   - Case linking functionality
   - Automatic cleanup of expired conversations

3. **ToolExecutor** (`app/core/tool_executor.py`)
   - Circuit breaker pattern for fault tolerance
   - Configurable retry logic with exponential backoff
   - Execution metrics and monitoring
   - Middleware support for cross-cutting concerns

4. **RefactoredParalegalAgent** (`app/orchestrator_refactored.py`)
   - Uses dependency injection for all components
   - Clean separation of streaming, conversation, and tool execution
   - Enhanced error handling with recovery mechanisms
   - Full conversation context tracking

## Phase 4: Cross-Cutting Concerns (Complete)

1. **Structured Logging** (`app/core/logging_utils.py`)
   - JSON-formatted logs with correlation IDs
   - Context propagation across async boundaries
   - Structured log helpers for common events
   - Performance tracking decorators

2. **Logging Middleware** (`app/core/logging_middleware.py`)
   - Tool execution logging with correlation
   - API request/response logging
   - Service operation tracking
   - Error context enrichment

3. **Integration Example** (`app/main_refactored.py`)
   - FastAPI application with structured logging
   - WebSocket and SSE support
   - Health checks and metrics endpoints
   - Circuit breaker management

4. **Integration Tests** (`tests/test_integration_refactored.py`)
   - End-to-end chat flow testing
   - Conversation persistence verification
   - Circuit breaker behavior testing
   - Service orchestration validation

## Benefits Achieved

1. **Improved Observability**
   - Correlation IDs for distributed tracing
   - Structured logs for better searchability
   - Comprehensive metrics collection
   - Health monitoring at all levels

2. **Enhanced Reliability**
   - Circuit breakers prevent cascade failures
   - Retry logic for transient errors
   - Graceful degradation
   - Error recovery mechanisms

3. **Better Maintainability**
   - Clear separation of concerns
   - Dependency injection throughout
   - Consistent patterns
   - Comprehensive test coverage

4. **Production Readiness**
   - Proper logging for debugging
   - Performance monitoring
   - Resource management
   - Configuration management

## Migration to Production

1. **Environment Configuration**
   ```bash
   # .env.production
   LOG_LEVEL=INFO
   LOG_FORMAT=json
   REDIS_URL=redis://redis:6379/0
   DATABASE_URL=postgresql://user:pass@db/paralegal
   ```

2. **Deployment Considerations**
   - Use Redis for production conversation state
   - Configure circuit breakers based on SLAs
   - Set up log aggregation (ELK, CloudWatch, etc.)
   - Monitor metrics with Prometheus/Grafana

3. **Performance Tuning**
   - Adjust connection pool sizes
   - Configure cache TTLs
   - Tune circuit breaker thresholds
   - Optimize embedding cache size

## Next Steps

1. **Phase 5**: Performance optimization
   - Database query optimization
   - Caching strategy refinement
   - Async operation batching
   - Resource pool tuning

2. **Phase 6**: Documentation updates
   - API documentation with OpenAPI
   - Architecture diagrams
   - Deployment guide
   - Operations runbook

## Troubleshooting

### Service Not Initialized
```python
ServiceNotInitializedError: Service 'StatuteSearchService' not initialized
```
Solution: Ensure `initialize_services()` is called during startup

### Configuration Errors
```python
ConfigurationError: SECRET_KEY must be changed in production
```
Solution: Set proper environment variables in `.env` file

### Tool Not Found
```python
ToolNotFoundError: Tool 'unknown_tool' not found
```
Solution: Check tool is registered with `@tool_registry.register()`