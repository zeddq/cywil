# Celery Integration Guide

## Overview

The AI Paralegal POC now supports both synchronous and asynchronous task execution through Celery workers. This allows for better scalability, background processing, and distributed task execution.

## Configuration

### Environment Variables

```bash
# Enable/Disable Celery (default: false)
USE_CELERY=true

# Redis Configuration (used as Celery broker)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=your_redis_password  # Optional
```

## Running the Application

### Without Celery (Default)

```bash
# Standard mode - all tasks execute synchronously
USE_CELERY=false python -m uvicorn app.main:app --reload
```

### With Celery

#### 1. Start Redis

```bash
# Using Docker
docker run -d -p 6379:6379 redis:7-alpine

# Or using system Redis
redis-server
```

#### 2. Start Celery Workers

```bash
# Start a general worker
./scripts/start_celery.sh worker

# Or start all components (worker + beat + flower)
./scripts/start_celery.sh all
```

#### 3. Start the Application

```bash
USE_CELERY=true python -m uvicorn app.main:app --reload
```

#### 4. Monitor Tasks (Optional)

```bash
# Start Flower monitoring UI
./scripts/start_celery.sh flower

# Access at http://localhost:5555
```

## Using Docker Compose

### Complete Stack with Celery

```bash
# Start all services including Celery workers
docker-compose -f docker-compose.celery.yml up

# Services started:
# - Redis (port 6379)
# - PostgreSQL (port 5432)
# - Qdrant (port 6333)
# - Celery Worker (general tasks)
# - Celery Worker Heavy (ingestion/embeddings)
# - Celery Beat (scheduled tasks)
# - Flower (port 5555)
# - FastAPI App (port 8000)
```

## API Endpoints

### Celery-Specific Endpoints

When `USE_CELERY=true`, additional endpoints are available:

#### Health & Monitoring

```bash
# Check Celery workers health
GET /celery/health

# Get worker statistics
GET /celery/stats

# Get specific task status
GET /celery/task/{task_id}

# Cancel a running task
DELETE /celery/task/{task_id}
```

#### Async Operations

```bash
# Async search (returns task_id)
POST /celery/search/async
{
  "query": "your search query",
  "search_type": "hybrid"  # or "statutes", "rulings"
}

# Async document generation
POST /celery/document/generate/async
{
  "document_type": "pozew_upominawczy",
  "context": {...}
}

# Trigger ingestion pipeline
POST /celery/ingest/trigger
{
  "ingestion_type": "all",
  "force_update": false
}
```

## Task Queues

The system uses specialized queues for different task types:

| Queue | Priority | Purpose | Concurrency |
|-------|----------|---------|-------------|
| high_priority | 10 | Urgent tasks | 4 workers |
| search | 8 | Search operations | 4 workers |
| case_management | 7 | Case operations | 3 workers |
| documents | 6 | Document generation | 2 workers |
| default | 5 | General tasks | 2 workers |
| ingestion | 3 | PDF processing | 1 worker |
| embeddings | 3 | Vector generation | 2 workers |

## Scheduled Tasks

When Celery Beat is running, the following tasks execute periodically:

- **Cleanup expired results**: Every 6 hours
- **Health check services**: Every 5 minutes
- **Process dead letter queue**: Every hour
- **Update embeddings index**: Every 24 hours

## Development Tips

### Testing Celery Integration

```python
# Check if Celery is enabled
import os
USE_CELERY = os.getenv("USE_CELERY", "false").lower() == "true"

# Verify workers are running
from app.worker.celery_app import celery_app
inspect = celery_app.control.inspect()
active_workers = inspect.active_queues()
print(f"Active workers: {len(active_workers)}")
```

### Debugging Tasks

```bash
# View task logs
celery -A app.worker.celery_app events

# Inspect running tasks
celery -A app.worker.celery_app inspect active

# Check reserved tasks
celery -A app.worker.celery_app inspect reserved
```

## Troubleshooting

### No Workers Available

```bash
# Check if Redis is running
redis-cli ping

# Check worker logs
celery -A app.worker.celery_app worker --loglevel=debug
```

### Tasks Not Executing

```bash
# Check task routing
celery -A app.worker.celery_app inspect registered

# Purge all pending tasks (development only!)
celery -A app.worker.celery_app purge
```

### Memory Issues

```bash
# Limit worker memory usage
celery -A app.worker.celery_app worker --max-memory-per-child=512000
```

## Architecture Benefits

1. **Scalability**: Distribute heavy tasks across multiple workers
2. **Reliability**: Automatic retry and dead letter queue for failed tasks
3. **Performance**: Non-blocking operations for long-running tasks
4. **Monitoring**: Real-time task tracking and metrics
5. **Flexibility**: Easy switch between sync/async modes

## Migration Path

The application supports gradual migration to Celery:

1. **Phase 1**: Run with `USE_CELERY=false` (current behavior)
2. **Phase 2**: Enable for specific heavy operations (ingestion, embeddings)
3. **Phase 3**: Full async mode for all supported operations

## Security Considerations

- Redis should be password-protected in production
- Use SSL/TLS for Redis connections in production
- Implement task result encryption for sensitive data
- Set appropriate task timeouts to prevent resource exhaustion
- Monitor dead letter queue for failed sensitive operations