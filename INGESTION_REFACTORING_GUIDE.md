# Ingestion Pipeline Refactoring Guide

## Overview

This guide documents the refactoring of the ingestion pipelines from standalone scripts to a service-oriented architecture that aligns with the refactored application design. The new architecture addresses critical issues identified in the analysis while maintaining all existing functionality.

## Problems Addressed

### Critical Issues Fixed

1. **Architectural Bypass (HIGH PRIORITY)**
   - **Problem**: Old pipelines bypassed `DatabaseManager` and used direct database connections
   - **Solution**: All services now use `DatabaseManager` with proper connection pooling and transaction management

2. **Configuration Fragmentation (HIGH PRIORITY)**
   - **Problem**: Multiple configuration systems and hardcoded values
   - **Solution**: Centralized configuration via `ConfigService` with proper validation and `SecretStr` for sensitive data

3. **Synchronous-Async Mismatch (MEDIUM PRIORITY)**
   - **Problem**: Sync code conflicted with async architecture
   - **Solution**: All operations converted to async/await pattern

4. **Missing Service Integration (MEDIUM PRIORITY)**
   - **Problem**: No health checks, monitoring, or service lifecycle management
   - **Solution**: All services implement `ServiceInterface` with proper health checks and shutdown procedures

## New Architecture

### Core Services

```
app/services/
├── statute_ingestion_service.py      # KC/KPC statute ingestion
├── supreme_court_ingest_service.py   # SN ruling processing
├── embedding_service.py              # Centralized embedding operations
└── __init__.py                       # Service registration
```

### Service Features

#### StatuteIngestionService
- **Purpose**: Ingest Polish civil law statutes (KC/KPC)
- **Features**:
  - Async PDF processing with existing `pdf2chunks` logic
  - Database operations via `DatabaseManager`
  - Health checks and monitoring
  - Tool registration for AI orchestration
  - Progress tracking and error handling

#### SupremeCourtIngestService  
- **Purpose**: Process Supreme Court rulings using o3 model
- **Features**:
  - Async batch processing with concurrency control
  - Integration with existing o3 pipeline
  - JSONL output management
  - Fallback processing for reliability
  - File merging and statistics

#### EmbeddingService
- **Purpose**: Centralized embedding generation and management
- **Features**:
  - Async embedding generation with batching
  - Qdrant integration with proper indexing
  - Support for both statutes and rulings
  - Resource management and cleanup
  - Performance optimization

### Tool Registration

All services register their key functions as tools for AI orchestration:

```python
@tool_registry.register(
    name="ingest_statute_pdf",
    description="Ingest a statute PDF (KC or KPC) into the system",
    category=ToolCategory.DOCUMENT,
    parameters=[...],
    returns="Dictionary with ingestion statistics"
)
async def ingest_statute_pdf(self, pdf_path: str, code_type: str, force_update: bool = False):
    # Implementation
```

## Usage

### Service Integration

Services are automatically registered during application startup:

```python
from app.services import initialize_services

# Initialize all services including ingestion
service_manager = initialize_services()
await service_manager.start_all()
```

### Direct Usage

```python
from app.services import StatuteIngestionService, DatabaseManager
from app.core.config_service import get_config

# Initialize dependencies
config = get_config()
db_manager = DatabaseManager()
await db_manager.initialize()

# Create and use service
service = StatuteIngestionService(db_manager)
await service.initialize()

# Ingest a statute
result = await service.ingest_statute_pdf("path/to/kc.pdf", "KC")
```

### Tool Execution

```python
from app.services import execute_tool

# Execute via tool registry
result = await execute_tool("ingest_statute_pdf", {
    "pdf_path": "path/to/kc.pdf",
    "code_type": "KC",
    "force_update": False
})
```

## Migration

### Migration Script

Use the provided migration script to transition from old to new architecture:

```bash
# Check old data structure
python ingest/migrate_to_new_architecture.py --check-old

# Run migration with file copying
python ingest/migrate_to_new_architecture.py --migrate --copy-files

# Validate migration
python ingest/migrate_to_new_architecture.py --validate --report migration_report.md
```

### Refactored Pipeline

The refactored pipeline provides a bridge between old and new systems:

```bash
# Run full pipeline with new architecture
python ingest/refactored_ingest_pipeline.py

# Run specific operations
python ingest/refactored_ingest_pipeline.py --health-check
python ingest/refactored_ingest_pipeline.py --validate-only
python ingest/refactored_ingest_pipeline.py --embeddings-only
```

## Configuration

### Environment Variables

All configuration now uses the centralized `ConfigService`:

```env
# Database
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=paralegal
POSTGRES_PASSWORD=secret
POSTGRES_DB=paralegal

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION_STATUTES=statutes
QDRANT_COLLECTION_RULINGS=sn_rulings

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_LLM_MODEL=o3-mini

# Storage
STORAGE_BASE_DIR=data
STORAGE_CHUNKS_DIR=chunks
STORAGE_PDFS_DIR=pdfs
STORAGE_JSONL_DIR=jsonl
```

### Storage Structure

```
data/
├── chunks/          # Processed statute chunks
├── pdfs/           # PDF files
│   ├── statutes/   # KC/KPC statute PDFs
│   └── sn-rulings/ # Supreme Court ruling PDFs
├── jsonl/          # Processed ruling records
└── embeddings/     # Backup embedding files
```

## Health Checks

All services implement comprehensive health checks:

```python
# Check individual service
health = await service.health_check()
print(f"Status: {health.status}")
print(f"Message: {health.message}")
print(f"Details: {health.details}")

# Check all services
from ingest.refactored_ingest_pipeline import RefactoredIngestOrchestrator
orchestrator = RefactoredIngestOrchestrator()
await orchestrator.initialize()
health = await orchestrator.health_check()
```

## Monitoring

### Service Status

```python
# Get ingestion status
statute_status = await statute_service.get_ingestion_status()
court_status = await court_service.get_sn_processing_status()
embedding_stats = await embedding_service.get_embedding_statistics()
```

### Performance Metrics

- Processing time tracking
- Success/failure rates
- File counts and sizes
- Embedding generation statistics
- Database connection pool status

## Error Handling

### Structured Logging

All services use structured logging:

```python
from app.core.logger_manager import get_logger


logger = get_logger(__name__)
logger.info("Processing started", extra={"pdf_path": pdf_path, "code_type": code_type})
logger.error("Processing failed", exc_info=True, extra={"error_context": context})
```

### Graceful Degradation

- Fallback processing when o3 fails
- Retry mechanisms for network operations
- Partial success handling
- Resource cleanup on errors

## Testing

### Unit Tests

```python
import pytest
from app.services import StatuteIngestionService
from app.core.database_manager import DatabaseManager

@pytest.fixture
async def service():
    db_manager = DatabaseManager()
    await db_manager.initialize()
    service = StatuteIngestionService(db_manager)
    await service.initialize()
    yield service
    await service.shutdown()
    await db_manager.shutdown()

async def test_statute_ingestion(service):
    result = await service.ingest_statute_pdf("test.pdf", "KC")
    assert result["status"] == "success"
```

### Integration Tests

```python
async def test_full_pipeline():
    orchestrator = RefactoredIngestOrchestrator()
    await orchestrator.initialize()
    
    result = await orchestrator.run_full_pipeline()
    assert result["steps"]["health_check"]["database"]["status"] == "healthy"
    
    await orchestrator.shutdown()
```

## Performance Optimizations

### Async Processing

- All I/O operations are async
- Concurrent processing with semaphores
- Thread pool for CPU-intensive tasks
- Proper resource management

### Batch Processing

- Configurable batch sizes
- Memory-efficient processing
- Progress tracking
- Interrupt handling

### Connection Pooling

- Database connection pooling via `DatabaseManager`
- Qdrant client reuse
- Proper connection lifecycle management

## Security Improvements

### Secure Configuration

- `SecretStr` for sensitive data
- Environment-based configuration
- Input validation
- SQL injection prevention

### Access Control

- Service-level authentication
- Role-based access control
- Audit logging
- Secure defaults

## Backward Compatibility

### Legacy Support

The old ingest scripts remain functional but are deprecated:

```python
# Old way (deprecated)
from ingest.ingest_pipeline import StatuteIngestionPipeline

# New way (recommended)
from app.services import StatuteIngestionService
```

### Migration Path

1. **Phase 1**: Run both systems in parallel
2. **Phase 2**: Migrate data using migration script
3. **Phase 3**: Switch to new services
4. **Phase 4**: Remove old scripts

## Troubleshooting

### Common Issues

1. **Service not initializing**
   - Check database connectivity
   - Verify configuration values
   - Check API key validity

2. **Performance issues**
   - Monitor connection pool usage
   - Adjust batch sizes
   - Check resource limits

3. **Data inconsistencies**
   - Run validation scripts
   - Check migration status
   - Verify database integrity

### Debug Commands

```bash
# Check service health
python ingest/refactored_ingest_pipeline.py --health-check

# Validate data integrity
python ingest/refactored_ingest_pipeline.py --validate-only

# Check migration status
python ingest/migrate_to_new_architecture.py --validate
```

## Future Enhancements

### Planned Features

1. **Real-time Processing**
   - Event-driven ingestion
   - WebSocket status updates
   - Live progress tracking

2. **Advanced Monitoring**
   - Metrics collection
   - Dashboard integration
   - Alerting system

3. **Scalability**
   - Distributed processing
   - Message queue integration
   - Horizontal scaling

### Extension Points

- Custom PDF processors
- Additional embedding models
- New document types
- Integration with external systems

## Conclusion

The refactored ingestion pipeline provides a robust, scalable, and maintainable solution that aligns with the application's service-oriented architecture. The new design addresses all identified issues while maintaining compatibility and providing enhanced features for monitoring, error handling, and performance optimization.

Key benefits:
- **Consistency**: All services follow the same patterns
- **Monitoring**: Comprehensive health checks and metrics
- **Scalability**: Async operations and connection pooling
- **Maintainability**: Centralized configuration and error handling
- **Integration**: Tool registration enables AI orchestration
- **Quality**: Proper testing and validation frameworks
