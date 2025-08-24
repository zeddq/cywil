# Celery Worker Monitoring & Error Handling

## Overview

This document describes the refactored Celery implementation with comprehensive monitoring, error handling, and observability features.

## Key Features

### 1. Worker Signal Monitoring
- **Comprehensive signal handlers** for all Celery lifecycle events
- **Real-time task tracking** with detailed metrics
- **Worker health monitoring** with heartbeat detection
- **Automatic metric collection** for performance analysis

### 2. Dead Letter Queue (DLQ) Pattern
- **Automatic failed task routing** to DLQ after max retries
- **DLQ processing** with configurable requeue strategies  
- **Permanent failure storage** for manual review
- **Time-based DLQ expiration** to prevent unbounded growth

### 3. Enhanced Error Handling
- **Base task classes** with built-in retry logic
- **Exponential backoff** with jitter to prevent thundering herd
- **Circuit breaker pattern** for failing services
- **Detailed error tracking** with full context preservation

### 4. Structured Logging
- **JSON-formatted logs** for easy parsing and analysis
- **Celery context injection** (task_id, queue, retries, etc.)
- **Performance metrics logging** for each task execution
- **Error aggregation** for efficient batch processing

### 5. Monitoring API
- **RESTful endpoints** for health checks and metrics
- **Task submission and management** via API
- **Queue inspection** and worker statistics
- **Performance dashboards** with historical data

## Architecture Components

### Core Files

```
app/worker/
├── celery_app.py          # Main Celery application
├── config.py              # Celery configuration with DLQ setup
├── monitoring.py          # Signal handlers and metrics collection
├── base_task.py           # Enhanced base task classes
├── logging_config.py      # Structured logging configuration
└── tasks/
    ├── example.py         # Example tasks with monitoring
    └── maintenance.py     # System maintenance tasks
```

### Monitoring Service

The `CeleryMonitor` class provides:
- Real-time task tracking
- Worker health monitoring
- Performance metrics collection
- Error aggregation and reporting
- DLQ management

### Base Task Classes

1. **BaseTask**: Standard task with retry and monitoring
2. **RetryableTask**: Enhanced retry logic for transient failures
3. **CriticalTask**: High-priority tasks with more retries
4. **LongRunningTask**: Tasks with extended time limits

## Configuration

### Environment Variables

```bash
# Logging configuration
CELERY_LOG_LEVEL=INFO          # Log level (DEBUG, INFO, WARNING, ERROR)
CELERY_JSON_LOGS=true          # Enable JSON structured logging

# Redis configuration
REDIS_URL=redis://localhost:6379/0

# Worker configuration
CELERY_WORKER_CONCURRENCY=4    # Number of worker processes
CELERY_WORKER_PREFETCH=1       # Tasks to prefetch per worker
```

### Queue Configuration

Queues are configured with:
- **Priority levels** (0-10)
- **Dead letter exchange** routing
- **Message TTL** for expiration
- **Rate limiting** per queue

## Usage Examples

### Starting Workers

```bash
# Start worker with monitoring
celery -A app.worker.celery_app worker \
    --loglevel=info \
    --queues=default,high_priority \
    --concurrency=4

# Start beat scheduler
celery -A app.worker.celery_app beat \
    --loglevel=info
```

### Submitting Tasks with Monitoring

```python
from app.worker.tasks.example import add
from app.worker.monitoring import monitor

# Submit task
result = add.delay(5, 3)

# Check status via monitor
status = monitor.get_task_status(result.id)
print(f"Task status: {status}")

# Get performance stats
stats = monitor.get_performance_stats("example.add")
print(f"Average duration: {stats['avg_duration']}s")
```

### Using Base Task Classes

```python
from app.worker.celery_app import celery_app
from app.worker.base_task import RetryableTask

@celery_app.task(base=RetryableTask, name="my.retryable_task")
def my_task(param):
    # Task will automatically retry on connection errors
    # with exponential backoff
    return process_data(param)
```

### Monitoring API Endpoints

```python
# Health check
GET /api/v1/monitoring/health

# Worker status
GET /api/v1/monitoring/workers

# Task status
GET /api/v1/monitoring/tasks/{task_id}

# Performance metrics
GET /api/v1/monitoring/performance?task_name=example.add

# Recent errors
GET /api/v1/monitoring/errors?limit=10

# Process DLQ
POST /api/v1/monitoring/dlq/process?max_items=100&requeue=true
```

## Monitoring Signals

The system tracks these Celery signals:

### Worker Signals
- `worker_init`: Worker initialization
- `worker_ready`: Worker ready to accept tasks
- `worker_shutting_down`: Worker shutdown

### Task Signals
- `task_prerun`: Before task execution
- `task_postrun`: After task execution
- `task_success`: Task completed successfully
- `task_failure`: Task failed after retries
- `task_retry`: Task being retried
- `task_revoked`: Task cancelled

## Dead Letter Queue Processing

Failed tasks are automatically sent to DLQ when:
1. Max retries exceeded
2. Task terminated due to timeout
3. Unhandled exceptions occur

DLQ items contain:
- Original task details (name, args, kwargs)
- Failure information (exception, traceback)
- Retry history
- Timestamps

### DLQ Processing Strategies

1. **Automatic Requeue**: Retry failed tasks with backoff
2. **Manual Review**: Store for developer investigation
3. **Discard Old**: Remove tasks older than threshold

## Performance Optimization

### Circuit Breaker Pattern

Tasks use circuit breaker to prevent cascading failures:
- **Closed**: Normal operation
- **Open**: Failures exceeded threshold, reject new tasks
- **Half-Open**: Test if service recovered

### Rate Limiting

Control task execution rate:
```python
@celery_app.task(rate_limit="100/m")  # 100 per minute
def rate_limited_task():
    pass
```

### Idempotent Tasks

Prevent duplicate execution:
```python
from app.worker.base_task import idempotent_task

@celery_app.task
@idempotent_task(lambda x: f"process:{x}")
def process_once(item_id):
    # Will only run once per item_id within TTL
    return process_item(item_id)
```

## Troubleshooting

### Common Issues

1. **Tasks stuck in PENDING**
   - Check worker connectivity
   - Verify queue routing
   - Check Redis connection

2. **High retry rate**
   - Review circuit breaker status
   - Check external service health
   - Analyze error patterns in DLQ

3. **Memory issues**
   - Reduce prefetch multiplier
   - Limit concurrent tasks
   - Enable task result expiration

### Debug Commands

```bash
# Inspect active tasks
celery -A app.worker.celery_app inspect active

# Check queue lengths
celery -A app.worker.celery_app inspect reserved

# View worker stats
celery -A app.worker.celery_app inspect stats

# Purge all queues (CAREFUL!)
celery -A app.worker.celery_app purge
```

## Testing

Run the comprehensive test suite:

```bash
# Start workers
celery -A app.worker.celery_app worker --loglevel=info

# Run tests
python test_celery_monitoring.py
```

Tests cover:
- Basic task execution
- Retry mechanisms
- Time limits
- Batch processing
- Worker health
- Error tracking
- Performance monitoring
- Queue management

## Best Practices

1. **Always use base task classes** for automatic monitoring
2. **Set appropriate time limits** based on task complexity
3. **Configure retry strategies** for transient failures
4. **Monitor queue lengths** to prevent backlog
5. **Review DLQ regularly** for systemic issues
6. **Use structured logging** for better observability
7. **Implement circuit breakers** for external dependencies
8. **Set rate limits** to prevent resource exhaustion

## Metrics to Monitor

### Key Performance Indicators (KPIs)

1. **Task success rate**: `(successful_tasks / total_tasks) * 100`
2. **Average task duration**: Per task type
3. **Queue depth**: Number of pending tasks
4. **Worker utilization**: Active tasks per worker
5. **Retry rate**: `(retried_tasks / total_tasks) * 100`
6. **DLQ size**: Number of permanently failed tasks
7. **Circuit breaker trips**: Frequency of circuit opening

### Alerting Thresholds

- Task failure rate > 10%
- Queue depth > 1000 tasks
- Worker offline > 2 minutes
- DLQ size > 100 items
- Average duration > 2x baseline

## Future Enhancements

1. **Grafana dashboards** for visual monitoring
2. **Prometheus metrics** export
3. **Machine learning** for anomaly detection
4. **Auto-scaling** based on queue depth
5. **Task prioritization** algorithms
6. **Distributed tracing** with OpenTelemetry