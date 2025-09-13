#!/usr/bin/env python3
"""
Minimal run script for the AI Paralegal application
This runs the app without external services for testing
"""

import os
import sys
import asyncio
from pathlib import Path

# Set up minimal environment
os.environ["ENVIRONMENT"] = "development"
os.environ["USE_CELERY"] = "false"
os.environ["STANDALONE_MODE"] = "true"
os.environ["LOG_LEVEL"] = "INFO"

# Use SQLite for testing if DATABASE_URL is not set properly
if "postgresql" in os.environ.get("DATABASE_URL", ""):
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/app.db"

# Create necessary directories
Path("data/uploads").mkdir(parents=True, exist_ok=True)
Path("data/chunks").mkdir(parents=True, exist_ok=True)
Path("data/embeddings").mkdir(parents=True, exist_ok=True)

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("Starting AI Paralegal in minimal mode...")
print("Note: External services (PostgreSQL, Redis, Qdrant) are not available")
print("Some features will be limited or disabled")
print()

# Import and run the application
try:
    import uvicorn
    from app.main import app
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Make sure you've activated the virtual environment and installed dependencies:")
    print("  source .venv/bin/activate")
    print("  pip install -r requirements-short.txt")
except Exception as e:
    print(f"Error starting application: {e}")
    import traceback
    traceback.print_exc()