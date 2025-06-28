#!/usr/bin/env python3
"""
Main entry point for the AI Paralegal API server
"""
import uvicorn
from app.routes import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )