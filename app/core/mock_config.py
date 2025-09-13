"""
Mock configuration for running without external services
"""

import os
from typing import Optional

def setup_mock_environment():
    """Set up environment for running without external services"""
    
    # Check if we're in standalone mode
    if os.getenv("STANDALONE_MODE", "false").lower() == "true":
        print("🔧 Setting up mock environment for standalone mode...")
        
        # Use SQLite instead of PostgreSQL
        if not os.getenv("DATABASE_URL"):
            os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/app.db"
        
        # Disable external services
        os.environ["USE_CELERY"] = "false"
        os.environ["MOCK_SERVICES"] = "true"
        
        # Set dummy values for required services
        if not os.getenv("REDIS_URL"):
            os.environ["REDIS_URL"] = "redis://localhost:6379/0"  # Won't be used
        
        if not os.getenv("QDRANT_HOST"):
            os.environ["QDRANT_HOST"] = "localhost"
            os.environ["QDRANT_PORT"] = "6333"
        
        print("✅ Mock environment configured")

class MockRedis:
    """Mock Redis client for when Redis is not available"""
    
    def __init__(self):
        self._cache = {}
    
    async def get(self, key: str) -> Optional[str]:
        return self._cache.get(key)
    
    async def set(self, key: str, value: str, ex: Optional[int] = None):
        self._cache[key] = value
    
    async def delete(self, key: str):
        self._cache.pop(key, None)
    
    async def ping(self):
        return True

class MockQdrant:
    """Mock Qdrant client for when Qdrant is not available"""
    
    def __init__(self):
        self._collections = {}
    
    async def search(self, collection: str, query_vector: list, limit: int = 10):
        # Return empty results
        return []
    
    async def upsert(self, collection: str, points: list):
        # Store in memory (simplified)
        if collection not in self._collections:
            self._collections[collection] = []
        self._collections[collection].extend(points)
    
    async def create_collection(self, collection: str, vector_size: int):
        self._collections[collection] = []