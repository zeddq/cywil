# AI Paralegal POC

A proof of concept for an AI-powered paralegal assistant that helps with document analysis, legal research, and case management.

## Project Structure

```
ai-paralegal-poc/
├─ app/                  # FastAPI backend + orchestration
│  ├─ main.py            # API entrypoint (uvicorn app.main:app)
│  ├─ routes/            # API route modules
│  ├─ services/          # Domain services
│  ├─ core/              # Config, DB, logging, tools
│  └─ worker/            # Celery worker and tasks (optional)
├─ ingest/               # Ingestion utilities and pipelines
├─ ui/                   # Next.js UI (optional)
├─ docs/                 # Architecture and ops docs
└─ docker-compose.yml    # Local dev stack
```

## Quickstart

1) Poetry environment

- Install Poetry: https://python-poetry.org/docs/#installation
- Ensure in-project venvs: `poetry config virtualenvs.in-project true`
- Install deps: `poetry install`

2) Environment variables

- `cp .env.example .env` and edit values as needed
- Set `OPENAI_API_KEY` if using LLM features

3) Database initialization

- Ensure Postgres is running (local or Docker)
- Initialize tables: `poetry run python init_database.py`
- See `docs/DATABASE_SETUP.md` for Alembic/manual options

4) Run the API

- Uvicorn: `poetry run uvicorn app.main:app --reload`
- Docker: `docker-compose up -d`

### Poetry helper

- Bootstrap script: `./scripts/init_poetry.sh` (installs deps, creates .env if missing, initializes DB)

## Features

- Document processing and chunking
- Semantic search and retrieval
- AI-powered legal analysis
- Case management assistance

## Development Notes

- FastAPI powers the backend API
- Optional Celery integration for async/background tasks (`USE_CELERY=true`)
- Next.js UI lives in `ui/` (see `ui/README.md`)

## License

MIT

