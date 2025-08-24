try:
    import pytest
except ImportError:
    # pytest not available - likely running static analysis
    pytest = None
from unittest.mock import Mock, AsyncMock
from types import SimpleNamespace

import sys
from pathlib import Path
# Add the app directory to the path
sys.path.append(str(Path(__file__).parent.parent))


@pytest.fixture
def mock_db_connection():
    """Mock database connection for unit tests"""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetchone = AsyncMock()
    mock_conn.fetchall = AsyncMock()
    return mock_conn


@pytest.fixture
def mock_config_service():
    """Lightweight configuration object for unit tests"""
    return SimpleNamespace(
        postgres_host="test_host",
        postgres_port=5432,
        postgres_user="test_user",
        postgres_password="test_pass",
        postgres_db="test_db",
        redis_url="redis://localhost:6379/1",
        qdrant_host="localhost",
        qdrant_port=6333,
    )


@pytest.fixture
def mock_embedding_service():
    """Mock embedding service for unit tests"""
    mock_service = AsyncMock()
    mock_service.generate_embedding = AsyncMock(return_value=[0.1, 0.2, 0.3])
    return mock_service


@pytest.fixture
def mock_vector_db():
    """Mock vector database client for unit tests"""
    mock_client = AsyncMock()
    mock_client.search = AsyncMock()
    mock_client.upsert = AsyncMock()
    mock_client.delete = AsyncMock()
    return mock_client
