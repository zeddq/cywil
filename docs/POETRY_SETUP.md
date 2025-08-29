# Poetry Setup Guide

This project uses Poetry for dependency management and virtual environments.

## Install and Configure

- Install Poetry: https://python-poetry.org/docs/#installation
- Use in-project virtualenvs for clarity: `poetry config virtualenvs.in-project true`

## Common Tasks

- Install dependencies: `poetry install`
- Add a dependency: `poetry add <package>`
- Add a dev dependency: `poetry add --group dev <package>`
- Run a command in the venv: `poetry run <cmd>`
- Spawn a shell in the venv: `poetry shell`

## Running the App

1) Copy env: `cp .env.example .env` and update values
2) Initialize DB: `poetry run python init_database.py`
3) Start API: `poetry run uvicorn app.main:app --reload`

## Exporting requirements.txt (for Docker/CI)

Some Dockerfiles/CI pipelines rely on `requirements.txt`. Export from Poetry:

```
# App (main) dependencies
poetry export -f requirements.txt --only main --without-hashes -o requirements.txt

# Dev dependencies (optional, for tests/CI)
poetry export -f requirements.txt --with dev --without-hashes -o requirements-test.txt
```

See `scripts/poetry_export_requirements.sh` for a helper.

