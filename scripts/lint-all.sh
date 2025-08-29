#!/bin/bash

# Lint all Python files in the workspace
# This script runs all configured linters and shows results in VS Code Problems tab

set -e

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WORKSPACE_ROOT"

# Activate virtual environment
# shellcheck source=/dev/null
source .venv/bin/activate

echo "Running linters on all Python files..."
echo "====================================="

# Run Pylint
echo "Running Pylint..."
pylint --rcfile=.pylintrc . || true

# Run Flake8  
echo -e "\nRunning Flake8..."
flake8 --config=.flake8 . || true

# Run Mypy
echo -e "\nRunning Mypy..."
mypy --config-file=mypy.ini . || true

# Run Pyright
echo -e "\nRunning Pyright..."
pyright || true

echo -e "\n====================================="
echo "All linters completed. Check VS Code Problems tab for results."
