# AI Paralegal Ingestion Service

This service provides asynchronous document ingestion capabilities using Celery for task management.

## Architecture

The ingestion service consists of:
- **FastAPI API**: REST endpoints for triggering ingestion tasks
- **Celery Workers**: Process ingestion tasks asynchronously
- **Celery Beat**: Handles scheduled tasks
- **Flower**: Web UI for monitoring Celery tasks
- **Redis**: Message broker for Celery

## Directory Structure

```
app/worker/
├── celery_app.py           # Celery configuration
├── ingestion_api.py        # FastAPI application
├── (uses top-level Poetry) # Dependencies managed via pyproject.toml
├── tasks/
│   ├── __init__.py
│   ├── example.py          # Example task
│   ├── statute_tasks.py    # Statute ingestion tasks
│   ├── ruling_tasks.py     # Supreme Court ruling tasks
│   ├── embedding_tasks.py  # Embedding generation tasks
│   ├── ingestion_pipeline.py # Pipeline orchestration
│   │
│   # Ingestion modules (moved from ingest/)
│   ├── pdf2chunks.py       # PDF parsing for statutes
│   ├── preprocess_sn_o3.py # Supreme Court ruling processing
│   ├── embed.py            # Embedding generation
│   └── sn.py               # Ruling database operations
```

## Components

### API Endpoints

- `POST /ingest/statutes` - Trigger statute (KC/KPC) ingestion
- `POST /ingest/rulings` - Trigger Supreme Court ruling ingestion
- `POST /pipeline/full` - Run complete ingestion pipeline
- `GET /tasks/{task_id}` - Check task status
- `GET /tasks` - List active tasks

### Celery Tasks

**Statute Tasks** (`statute_tasks.py`):
- `ingest_statute_pdf` - Process single statute PDF
- `ingest_all_statutes` - Process all statute PDFs
- `get_statute_ingestion_status` - Get ingestion status

**Ruling Tasks** (`ruling_tasks.py`):
- `process_single_ruling` - Process single ruling PDF
- `process_ruling_batch` - Batch process ruling PDFs
- `get_ruling_processing_status` - Get processing status

**Embedding Tasks** (`embedding_tasks.py`):
- `generate_statute_embeddings` - Generate statute embeddings
- `generate_ruling_embeddings` - Generate ruling embeddings
- `batch_generate_embeddings` - Batch embedding generation

**Pipeline Tasks** (`ingestion_pipeline.py`):
- `run_full_pipeline` - Orchestrate complete ingestion
- `run_statute_pipeline` - Run statute-only pipeline
- `run_ruling_pipeline` - Run ruling-only pipeline

## Local Development

### Prerequisites
- Redis running locally (default: localhost:6379)
- PostgreSQL database
- Qdrant vector database

### Running the Services

1. **Start Redis**:
```bash
docker run -d -p 6379:6379 redis:7-alpine
```

2. **Start Celery Worker**:
```bash
python run_celery_worker.py
# or
celery -A app.worker.celery_app worker --loglevel=info
```

3. **Start Celery Beat** (for scheduled tasks):
```bash
celery -A app.worker.celery_app beat --loglevel=info
```

4. **Start Flower** (monitoring UI):
```bash
celery -A app.worker.celery_app flower
```

5. **Start Ingestion API**:
```bash
uvicorn app.worker.ingestion_api:app --reload --port 8001
```

## Docker Build

Dependencies are managed with Poetry from the project lockfile. The ingestion image is built via the Poetry-based Dockerfile:

```bash
docker build -f deployment/docker/Dockerfile.ingestion -t ai-paralegal/ingestion:latest .
```

## Kubernetes Deployment

### Deploy to Kubernetes
```bash
kubectl apply -f deployment/k8s/ingestion-deployment.yaml
kubectl apply -f deployment/k8s/ingestion-ingress.yaml
```

### Access Services
- Ingestion API: http://ingestion.ai-paralegal.local
- Flower UI: http://flower.ai-paralegal.local

## Usage Examples

### Trigger Full Pipeline
```bash
curl -X POST http://localhost:8001/pipeline/full \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "statute_force_update": false,
    "ruling_pdf_directory": "/app/data/pdfs/sn-rulings"
  }'
```

### Check Task Status
```bash
curl http://localhost:8001/tasks/<task_id> \
  -H "Authorization: Bearer <token>"
```

### Monitor with Flower
Open http://localhost:5555 in your browser to monitor:
- Active tasks
- Task history
- Worker status
- Task failures

## Configuration

Environment variables:
- `REDIS_URL` - Redis connection URL
- `DATABASE_URL` - PostgreSQL connection URL
- `QDRANT_HOST` - Qdrant host (default: "qdrant")
- `QDRANT_PORT` - Qdrant port (default: 6333)
- `OPENAI_API_KEY` - OpenAI API key for embeddings
- `JWT_SECRET_KEY` - JWT secret for authentication

## Troubleshooting

### Common Issues

1. **Tasks stuck in PENDING**:
   - Check if Celery workers are running
   - Verify Redis connectivity
   - Check worker logs for errors

2. **Memory issues**:
   - Adjust worker concurrency
   - Increase resource limits in K8s
   - Use smaller batch sizes

3. **Slow ingestion**:
   - Increase number of workers
   - Enable HPA for auto-scaling
   - Optimize batch sizes

### Monitoring

Check logs:
```bash
# API logs
kubectl logs -n ai-paralegal deployment/ingestion-api

# Worker logs
kubectl logs -n ai-paralegal deployment/celery-worker

# Flower logs
kubectl logs -n ai-paralegal deployment/celery-flower
```
