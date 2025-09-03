# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Development Commands

### Environment Setup
```bash
# Bootstrap with Poetry (recommended)
./scripts/init_poetry.sh

# Manual setup
poetry config virtualenvs.in-project true
poetry install
cp .env.example .env
python init_database.py
```

### Running the Application
```bash
# Development API server
poetry run uvicorn app.main:app --reload

# Full stack with Docker
docker-compose up -d

# Individual services
docker-compose up postgres redis qdrant  # Infrastructure only
```

### Testing
```bash
# Run all tests
poetry run pytest

# Run specific test categories
poetry run pytest tests/unit/
poetry run pytest tests/integration/
poetry run pytest tests/celery/

# Run with coverage
poetry run pytest --cov=app --cov-report=html

# Run single test file
poetry run pytest tests/unit/test_llm_manager.py -v
```

### Code Quality
```bash
# Run all linters
./scripts/lint-all.sh

# Individual linters
poetry run pylint --rcfile=.pylintrc app/
poetry run flake8 --config=.flake8 app/
poetry run mypy --config-file=mypy.ini app/
poetry run pyright app/

# Auto-format code
poetry run black app/ tests/
poetry run isort app/ tests/
```

### Celery Operations (when USE_CELERY=true)
```bash
# Start Celery components
./scripts/start_celery.sh worker   # Worker only
./scripts/start_celery.sh beat     # Scheduler only
./scripts/start_celery.sh flower   # Monitoring UI
./scripts/start_celery.sh all      # All components

# Stop all Celery processes
./scripts/start_celery.sh stop
```

### MCP Server Operations
```bash
# Start all MCP servers
./scripts/launch_mcp_servers.sh

# Check status of MCP servers
./scripts/status_mcp_servers.sh

# Stop all MCP servers
./scripts/stop_mcp_servers.sh
```

#### Available MCP Servers

1. **Sequential Thinking** - Advanced reasoning and problem decomposition
   - Command: `npx -y @modelcontextprotocol/server-sequential-thinking`
   - Purpose: Breaks down complex problems into sequential steps

2. **Serena** - Interactive agent context management
   - Command: `uvx --from git+https://github.com/oraios/serena serena start-mcp-server`
   - Purpose: Manages agent context and state

3. **AI Paralegal (Zen)** - Legal assistant with multi-model support
   - Command: `uvx --from git+https://github.com/BeehiveInnovations/zen-mcp-server.git zen-mcp-server`
   - Requires: OPENAI_API_KEY, GOOGLE_API_KEY, XAI_API_KEY, REDIS_URL
   - Supports: GPT-5, Gemini 2.5, Grok-4 models

4. **Web RAG** - Web content retrieval and augmented generation
   - Command: `python -m rag_mcp.server`
   - Location: `/Users/cezary/ragger`
   - Uses: Chroma vector database for web content storage

### Database Operations
```bash
# Initialize/recreate tables
python init_database.py

# Alembic migrations
alembic upgrade head
alembic downgrade -1
alembic revision --autogenerate -m "migration message"
```

## Architecture Overview

### System Design
The AI Paralegal POC is a Polish legal assistant built on an orchestrator-agent pattern:

- **Orchestrator**: Main agent that routes requests to specialist tools via `ParalegalAgentSDK`
- **Specialist Tools**: Domain-specific functions (statute search, document drafting, validation, scheduling)
- **Storage Layer**: PostgreSQL for structured data, Qdrant for vector embeddings
- **Execution Modes**: Direct execution or Celery-based async processing

### Core Components

#### Service Architecture
- **ConfigService**: Environment configuration with Pydantic validation
- **DatabaseManager**: Async PostgreSQL connection pooling with SQLModel/SQLAlchemy
- **LLMManager**: OpenAI client management with retry logic
- **ConversationManager**: Thread-based conversation persistence
- **ToolExecutor**: Circuit breaker pattern for tool reliability

#### Data Processing Pipeline
1. **StatuteIngestionService**: Processes KC/KPC legal codes, chunking at article boundaries
2. **SupremeCourtIngestService**: Processes Supreme Court (SN) rulings with GPT-4
3. **EmbeddingService**: Uses `paraphrase-multilingual-mpnet-base-v2` for Polish text
4. **Vector Storage**: Qdrant with HNSW indexing for semantic search

#### API Patterns
- **Streaming Responses**: Server-Sent Events (`/chat/stream`) and WebSocket (`/ws/chat`)
- **Authentication**: JWT-based with optional user system
- **Monitoring**: Structured logging with correlation IDs and OpenTelemetry traces

### Key Services Integration

#### Celery Integration (Optional)
When `USE_CELERY=true`, services are wrapped in proxy objects that route method calls to Celery workers:
- **Queue-specific workers**: `ingestion`, `embeddings`, `search`, `documents`, `case_management`
- **Execution modes**: `CELERY_SYNC` (immediate results), `CELERY_ASYNC` (background processing)
- **Task monitoring**: Built-in endpoints for status tracking and cancellation

#### Tool System
The application uses a tool-based architecture where the orchestrator can call:
- `search_statute(query, top_k)`: Hybrid search over legal codes
- `draft_document(type, facts, goals)`: Generate legal documents
- `validate_against_statute(draft, citations)`: Verify legal accuracy
- `compute_deadline(event_type, date)`: Calculate legal deadlines
- `schedule_reminder(case_id, date, note)`: Case management

### Key Files to Understand

- `app/main.py`: FastAPI application entry point with service initialization
- `app/paralegal_agents/refactored_agent_sdk.py`: Main orchestrator agent
- `app/core/service_interface.py`: Dependency injection container
- `app/core/tool_executor.py`: Circuit breaker and tool execution logic
- `app/services/statute_search_service.py`: Legal code search implementation
- `app/worker/celery_app.py`: Celery configuration and task routing

### Environment Configuration

Critical environment variables (see `.env.example`):
- `OPENAI_API_KEY`: Required for LLM functionality
- `USE_CELERY`: Enable async processing (requires Redis)
- `DATABASE_URL`: PostgreSQL connection (auto-constructed from POSTGRES_* vars)
- `QDRANT_*`: Vector database configuration
- `LOG_FORMAT`: Use "json" for structured logging

### Development Patterns

#### Service Registration
Services are registered as singletons in `ServiceContainer` during startup. Use dependency injection to access services in routes and agents.

#### Async/Await
The codebase is fully async. All database operations, LLM calls, and service methods use `async`/`await`.

#### Error Handling
- Circuit breaker pattern prevents cascading failures
- Structured logging with correlation IDs for request tracking
- Graceful fallbacks when external services are unavailable

#### Testing Strategy
- Unit tests mock external dependencies (OpenAI, Qdrant, PostgreSQL)
- Integration tests use test database and fixtures
- Celery tests verify task execution and queue routing

This codebase focuses on Polish legal document analysis and generation, with emphasis on reliability, observability, and scalable processing patterns.
