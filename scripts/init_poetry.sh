#!/usr/bin/env bash
set -euo pipefail

echo "[poetry:init] AI Paralegal POC – Poetry bootstrap"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v poetry >/dev/null 2>&1; then
  echo "[poetry:init] Poetry not found. Install: https://python-poetry.org/docs/#installation" >&2
  exit 1
fi

echo "[poetry:init] Using in-project virtualenv (.venv)"
poetry config virtualenvs.in-project true

echo "[poetry:init] Installing dependencies"
poetry install

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    echo "[poetry:init] Creating .env from .env.example"
    cp .env.example .env
  else
    echo "[poetry:init] No .env.example found; create .env manually"
  fi
fi

echo "[poetry:init] Initializing database tables"
poetry run python init_database.py || {
  echo "[poetry:init] Database init failed. See docs/DATABASE_SETUP.md for options." >&2
}

echo
echo "[poetry:init] Done! Next steps:"
echo "  - Run API:    poetry run uvicorn app.main:app --reload"
echo "  - Or Docker:  docker-compose up -d"
echo "  - UI (opt.):  cd ui && npm install && npm run dev"

