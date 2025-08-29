# AI Paralegal Deployment Guide

## Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- Python 3.11+
- PostgreSQL 14+
- Redis 7+
- Qdrant 1.7+
- 8GB RAM minimum (16GB recommended)
- 20GB disk space

## Environment Setup

### 1. Clone Repository

```bash
git clone https://github.com/your-org/ai-paralegal-poc.git
cd ai-paralegal-poc
```

### 2. Environment Variables

Create `.env.production`:

```bash
# Application
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8000
SECRET_KEY=your-secret-key-here

# OpenAI
OPENAI_API_KEY=sk-your-openai-api-key
OPENAI_ORCHESTRATOR_MODEL=gpt-4-turbo-preview
OPENAI_VALIDATOR_MODEL=gpt-4-turbo-preview
OPENAI_EMBEDDING_MODEL=text-embedding-3-large

# PostgreSQL
POSTGRES_USER=paralegal_user
POSTGRES_PASSWORD=secure-password
POSTGRES_DB=paralegal_prod
DATABASE_URL=postgresql://paralegal_user:secure-password@postgres:5432/paralegal_prod

# Redis
REDIS_URL=redis://redis:6379/0
REDIS_PASSWORD=redis-secure-password

# Qdrant
QDRANT_HOST=qdrant
QDRANT_PORT=6333
QDRANT_API_KEY=qdrant-api-key
QDRANT_COLLECTION_STATUTES=statutes_prod
QDRANT_COLLECTION_RULINGS=rulings_prod

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Performance
CONNECTION_POOL_SIZE=20
CONNECTION_POOL_MAX_OVERFLOW=10
CACHE_TTL_MINUTES=30
EMBEDDING_CACHE_SIZE=1000
```

## Docker Deployment

### 1. Create Docker Network

```bash
docker network create paralegal-network
```

### 2. Docker Compose Configuration

Create `docker-compose.prod.yml`:

```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: paralegal-app
    env_file: .env.production
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      qdrant:
        condition: service_healthy
    networks:
      - paralegal-network
    volumes:
      - ./logs:/app/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  postgres:
    image: postgres:14-alpine
    container_name: paralegal-postgres
    env_file: .env.production
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init_db.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - paralegal-network
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $POSTGRES_USER"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: paralegal-redis
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data
    networks:
      - paralegal-network
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  qdrant:
    image: qdrant/qdrant:v1.7.4
    container_name: paralegal-qdrant
    environment:
      - QDRANT__SERVICE__API_KEY=${QDRANT_API_KEY}
    volumes:
      - qdrant_data:/qdrant/storage
    networks:
      - paralegal-network
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  nginx:
    image: nginx:alpine
    container_name: paralegal-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./nginx/ssl:/etc/nginx/ssl
    depends_on:
      - app
    networks:
      - paralegal-network
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
  qdrant_data:

networks:
  paralegal-network:
    external: true
```

### 3. Dockerfile (Poetry-based)

Create `Dockerfile` using Poetry and the lockfile for reproducible installs:

```dockerfile
FROM python:3.11-slim

# Install system dependencies and Poetry
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "poetry>=1.8,<2.0"

WORKDIR /app

# Configure Poetry to install into the system env (no venv)
ENV POETRY_VIRTUALENVS_CREATE=false
ENV POETRY_NO_INTERACTION=1

# Reduce installer concurrency on low-RAM hosts
RUN poetry config installer.max-workers 2

# Copy dependency files and install main deps only
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-ansi --no-root --sync

# Copy application code
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Create non-root user
RUN useradd -m -u 1000 paralegal && chown -R paralegal:paralegal /app
USER paralegal

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### 4. Nginx Configuration

Create `nginx/nginx.conf`:

```nginx
events {
    worker_connections 1024;
}

http {
    upstream app {
        server app:8000;
    }

    server {
        listen 80;
        server_name your-domain.com;
        return 301 https://$server_name$request_uri;
    }

    server {
        listen 443 ssl http2;
        server_name your-domain.com;

        ssl_certificate /etc/nginx/ssl/cert.pem;
        ssl_certificate_key /etc/nginx/ssl/key.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        client_max_body_size 10M;

        location / {
            proxy_pass http://app;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # WebSocket support
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            
            # Timeouts
            proxy_connect_timeout 60s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }

        # Health check endpoint
        location /health {
            proxy_pass http://app/health;
            access_log off;
        }
    }
}
```

## Database Setup

### 1. Initialize Database

Create `scripts/init_db.sql`:

```sql
-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Create indexes for performance
CREATE INDEX idx_response_history_thread_created 
ON response_history(thread_id, created_at DESC);

CREATE INDEX idx_cases_reference_number 
ON cases(reference_number);

CREATE INDEX idx_cases_client_name_trgm 
ON cases USING gin(client_name gin_trgm_ops);

-- Create text search configuration
CREATE TEXT SEARCH CONFIGURATION polish (COPY = simple);
```

### 2. Run Migrations

```bash
docker-compose exec app alembic upgrade head
```

## Vector Database Setup

### 1. Initialize Collections

```python
# scripts/init_qdrant.py
import asyncio
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance

async def init_collections():
    client = QdrantClient(
        host="qdrant",
        port=6333,
        api_key="qdrant-api-key"
    )
    
    # Create statutes collection
    await client.create_collection(
        collection_name="statutes_prod",
        vectors_config=VectorParams(
            size=3072,  # text-embedding-3-large
            distance=Distance.COSINE
        )
    )
    
    # Create rulings collection
    await client.create_collection(
        collection_name="rulings_prod",
        vectors_config=VectorParams(
            size=3072,
            distance=Distance.COSINE
        )
    )

asyncio.run(init_collections())
```

### 2. Load Initial Data

```bash
# Load KC/KPC statutes
docker-compose exec app python scripts/load_statutes.py

# Load Supreme Court rulings
docker-compose exec app python scripts/load_rulings.py
```

## Deployment Steps

### 1. Build and Start Services

```bash
# Build images
docker-compose -f docker-compose.prod.yml build

# Start services
docker-compose -f docker-compose.prod.yml up -d

# Check status
docker-compose -f docker-compose.prod.yml ps

# View logs
docker-compose -f docker-compose.prod.yml logs -f app
```

### 2. Verify Deployment

```bash
# Check health
curl http://localhost/health

# Test API
curl -X POST http://localhost/chat \
  -H "Content-Type: application/json" \
  -H "X-User-ID: test" \
  -d '{"message": "Czym jest art. 415 KC?"}'
```

## Kubernetes Deployment

### 1. Create Namespace

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: paralegal
```

### 2. ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: paralegal-config
  namespace: paralegal
data:
  APP_ENV: "production"
  APP_HOST: "0.0.0.0"
  APP_PORT: "8000"
  LOG_LEVEL: "INFO"
  LOG_FORMAT: "json"
```

### 3. Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: paralegal-secrets
  namespace: paralegal
type: Opaque
stringData:
  OPENAI_API_KEY: "sk-your-key"
  DATABASE_URL: "postgresql://user:pass@postgres:5432/db"
  REDIS_URL: "redis://redis:6379/0"
  SECRET_KEY: "your-secret-key"
```

### 4. Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: paralegal-app
  namespace: paralegal
spec:
  replicas: 3
  selector:
    matchLabels:
      app: paralegal
  template:
    metadata:
      labels:
        app: paralegal
    spec:
      containers:
      - name: app
        image: your-registry/paralegal:latest
        ports:
        - containerPort: 8000
        env:
        - name: APP_ENV
          valueFrom:
            configMapKeyRef:
              name: paralegal-config
              key: APP_ENV
        envFrom:
        - secretRef:
            name: paralegal-secrets
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
```

### 5. Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: paralegal-service
  namespace: paralegal
spec:
  selector:
    app: paralegal
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer
```

## Monitoring Setup

### 1. Prometheus Metrics

Add to `app/metrics.py`:

```python
from prometheus_client import Counter, Histogram, Gauge

# Metrics
request_count = Counter('paralegal_requests_total', 'Total requests')
request_duration = Histogram('paralegal_request_duration_seconds', 'Request duration')
active_connections = Gauge('paralegal_active_connections', 'Active connections')
```

### 2. Grafana Dashboard

Import dashboard JSON from `monitoring/grafana-dashboard.json`

### 3. Alerts

Create `monitoring/alerts.yml`:

```yaml
groups:
- name: paralegal
  rules:
  - alert: HighErrorRate
    expr: rate(paralegal_errors_total[5m]) > 0.05
    for: 5m
    annotations:
      summary: "High error rate detected"
      
  - alert: CircuitBreakerOpen
    expr: paralegal_circuit_breaker_state{state="open"} > 0
    for: 1m
    annotations:
      summary: "Circuit breaker is open"
```

## Backup and Recovery

### 1. Database Backup

```bash
# Backup script
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
docker exec paralegal-postgres pg_dump -U paralegal_user paralegal_prod | gzip > backup_$DATE.sql.gz

# Upload to S3
aws s3 cp backup_$DATE.sql.gz s3://your-bucket/backups/
```

### 2. Restore Database

```bash
# Restore from backup
gunzip -c backup_20240115_120000.sql.gz | docker exec -i paralegal-postgres psql -U paralegal_user paralegal_prod
```

## Troubleshooting

### Common Issues

1. **Connection Refused**
   - Check if all services are running: `docker-compose ps`
   - Verify network connectivity: `docker network ls`

2. **Database Connection Error**
   - Check PostgreSQL logs: `docker logs paralegal-postgres`
   - Verify credentials in `.env.production`

3. **Redis Connection Error**
   - Check Redis password: `docker exec paralegal-redis redis-cli AUTH password`
   - Verify Redis is running: `docker exec paralegal-redis redis-cli ping`

4. **High Memory Usage**
   - Check container stats: `docker stats`
   - Adjust pool sizes in configuration

### Debug Commands

```bash
# Enter container shell
docker exec -it paralegal-app /bin/bash

# View real-time logs
docker-compose logs -f app

# Check service health
curl http://localhost:8000/health | jq

# Monitor metrics
curl http://localhost:8000/metrics
```

## Security Checklist

- [ ] Change all default passwords
- [ ] Enable SSL/TLS for all connections
- [ ] Configure firewall rules
- [ ] Set up API rate limiting
- [ ] Enable audit logging
- [ ] Configure backup encryption
- [ ] Set up monitoring alerts
- [ ] Review CORS settings
- [ ] Enable security headers
- [ ] Set up WAF rules

## Performance Tuning

### 1. Database

```sql
-- Adjust PostgreSQL settings
ALTER SYSTEM SET shared_buffers = '2GB';
ALTER SYSTEM SET effective_cache_size = '6GB';
ALTER SYSTEM SET maintenance_work_mem = '512MB';
```

### 2. Application

```python
# Adjust in .env.production
CONNECTION_POOL_SIZE=30
CONNECTION_POOL_MAX_OVERFLOW=20
WORKERS=8
```

### 3. Redis

```bash
# redis.conf
maxmemory 2gb
maxmemory-policy allkeys-lru
```

## Scaling Guidelines

1. **Horizontal Scaling**
   - Add more app replicas
   - Use load balancer
   - Implement session affinity for WebSockets

2. **Vertical Scaling**
   - Increase container resources
   - Upgrade database instance
   - Add more Redis memory

3. **Caching Strategy**
   - Increase cache TTL for stable data
   - Implement CDN for static assets
   - Use Redis cluster for larger deployments
