#!/usr/bin/env bash
set -euo pipefail

echo "[poetry:export] Exporting requirements from Poetry"

if ! command -v poetry >/dev/null 2>&1; then
  echo "[poetry:export] Poetry not found. Install: https://python-poetry.org/docs/#installation" >&2
  exit 1
fi

echo "[poetry:export] requirements.txt (main)"
poetry export -f requirements.txt --only main --without-hashes -o requirements.txt

if poetry show --tree >/dev/null 2>&1; then
  echo "[poetry:export] requirements-test.txt (dev)"
  poetry export -f requirements.txt --with dev --without-hashes -o requirements-test.txt || true
fi

echo "[poetry:export] Done."

