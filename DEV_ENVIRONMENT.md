# AI Paralegal Development Environment

This document describes the development environment setup with all necessary tools and fixes applied.

## Environment Overview

The development environment includes:
- Ubuntu 22.04 base image
- Python 3.13 with virtual environment
- Docker and Docker Compose (with network bridge fixes)
- All required Python dependencies
- PostgreSQL, Redis, and Qdrant services

## Building the Development Environment

### Option 1: Using Docker Compose (Recommended)

```bash
# Build and start the complete development environment
docker compose -f docker-compose.dev-env.yml up -d

# Enter the development container
docker exec -it ai-paralegal-dev bash

# Inside the container, services are already available
source .venv/bin/activate
```

### Option 2: Using Dockerfile Directly

```bash
# Build the development image
docker build -f Dockerfile.dev -t ai-paralegal-dev .

# Run the container with necessary mounts
docker run -it --rm \
  -v $(pwd):/workspace \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --network host \
  ai-paralegal-dev
```

## Important Notes

### Docker Commands Require Sudo

In the development environment, all Docker commands must be run with `sudo`:

```bash
# Check Docker status
sudo docker ps

# Start services
sudo docker compose -f docker-compose.dev.yml up -d

# View logs
sudo docker logs <container-name>
```

### Python Virtual Environment

The virtual environment is pre-installed at `.venv` and must be activated:

```bash
source .venv/bin/activate
```

### Environment Variables

The following environment variables are pre-configured:
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `QDRANT_HOST` and `QDRANT_PORT`: Qdrant connection settings
- `USE_CELERY`: Set to "false" for development
- `ENVIRONMENT`: Set to "development"

## Running Tests

After activating the virtual environment:

```bash
# Run specific test suites
python -m pytest tests/unit/test_performance_utils.py -v --no-cov

# Run all unit tests
python -m pytest tests/unit/ -v --no-cov

# Run with specific markers
python -m pytest -m "not slow" -v --no-cov
```

## Starting the API

```bash
# Make sure services are running
sudo docker compose -f docker-compose.dev.yml ps

# Start the API
source .venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Troubleshooting

### Docker Network Issues

If you encounter network bridge errors, the Dockerfile includes a fix that disables iptables:
```json
{
  "iptables": false,
  "bridge": "none"
}
```

### Permission Issues

The development user has sudo privileges without password. Use `sudo` for Docker commands.

### Database Migrations

If the database needs initialization:
```bash
source .venv/bin/activate
alembic upgrade head
```

## Sub-Agent Tasks

There are 5 sub-agent task files for fixing test failures:
1. `fix_batchprocessor_tests.md` - Async startup issues
2. `fix_embeddingbatcher_tests.md` - Future handling issues
3. `fix_toolregistry_tests.md` - API compatibility issues
4. `fix_agentsdk_tests.md` - Dependency injection issues
5. `fix_toolexecutor_tests.md` - Configuration mocking issues

Each file contains specific instructions for fixing the respective test failures.