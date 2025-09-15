#!/bin/bash

# Standalone run script for AI Paralegal POC
# This script runs the application without Docker for testing purposes

echo "=========================================="
echo "AI Paralegal POC - Standalone Runner"
echo "=========================================="

# Check Python version
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "✓ Python version: $PYTHON_VERSION"

# Set up virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip --quiet

# Install dependencies
echo "Installing dependencies..."
if [ -f "requirements-short.txt" ]; then
    pip install -r requirements-short.txt --quiet
else
    echo "Warning: requirements-short.txt not found, using requirements.txt"
    pip install -r requirements.txt --quiet
fi

# Load environment variables
if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    export $(cat .env | grep -v '^#' | xargs)
fi

# Override settings for standalone mode
export ENVIRONMENT=development
export USE_CELERY=false
export LOG_LEVEL=INFO
export STANDALONE_MODE=true

# Check if critical environment variables are set
if [ -z "$OPENAI_API_KEY" ] || [ "$OPENAI_API_KEY" = "your-openai-api-key-here" ]; then
    echo ""
    echo "⚠️  WARNING: OPENAI_API_KEY is not set or is using placeholder value"
    echo "   The application will start but AI features won't work properly."
    echo "   Please update the OPENAI_API_KEY in .env file."
    echo ""
fi

# Create necessary directories
echo "Creating data directories..."
mkdir -p data/uploads data/chunks data/embeddings

# Display service warnings
echo ""
echo "⚠️  NOTICE: Running in standalone mode"
echo "   - PostgreSQL: Not available (using in-memory database)"
echo "   - Redis: Not available (caching disabled)"
echo "   - Qdrant: Not available (vector search disabled)"
echo "   - Celery: Disabled (background tasks will run synchronously)"
echo ""
echo "For full functionality, use Docker Compose:"
echo "   docker compose up"
echo ""

# Start the application
echo "Starting application on http://localhost:8000"
echo "Press Ctrl+C to stop"
echo ""

# Run with limited functionality message
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload