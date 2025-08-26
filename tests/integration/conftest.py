try:
    import pytest
except ImportError:
    # pytest not available - likely running static analysis
    class MockPytest:
        def fixture(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
    
    pytest = MockPytest()
import asyncio
import os
from typing import AsyncGenerator

try:
    import asyncpg
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    import redis.asyncio as redis
    from uuid import uuid4
    from app.core.config_service import ConfigService
    from app.core.database_manager import DatabaseManager
    # from app.services.embedding import EmbeddingService  # TODO: Create embedding service
except ModuleNotFoundError:
    pass


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_config():
    """Load test configuration"""
    # Load test environment
    if os.path.exists('.env.test'):
        from dotenv import load_dotenv
        load_dotenv('.env.test')
    
    config = ConfigService()
    return config


@pytest.fixture(scope="session")
async def test_db_pool(test_config):
    """Create test database connection pool"""
    db_manager = DatabaseManager(test_config)
    await db_manager.initialize()
    yield db_manager
    await db_manager.close()


@pytest.fixture(scope="function")
async def test_db_connection(test_db_pool):
    """Get database connection with transaction rollback"""
    async with test_db_pool.pool.acquire() as conn:
        async with conn.transaction():
            # Start a savepoint for rollback
            await conn.execute("SAVEPOINT test_savepoint")
            yield conn
            # Rollback to savepoint after test
            await conn.execute("ROLLBACK TO SAVEPOINT test_savepoint")


@pytest.fixture(scope="session")
async def test_redis_client(test_config):
    """Create test Redis client"""
    client = redis.from_url(test_config.redis_url)
    yield client
    await client.aclose()


@pytest.fixture(scope="function")
async def test_qdrant_collection(test_config):
    """Create ephemeral Qdrant collection for test"""
    client = QdrantClient(host=test_config.qdrant_host, port=test_config.qdrant_port)
    collection_name = f"test_collection_{uuid4()}"
    
    # Create collection
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )
    
    yield collection_name, client
    
    # Cleanup
    client.delete_collection(collection_name)


# TODO: Re-enable when EmbeddingService is implemented
# @pytest.fixture(scope="session")
# async def embedding_service():
#     """Create embedding service for integration tests"""
#     service = EmbeddingService()
#     return service