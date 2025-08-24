import pytest
from unittest.mock import Mock, AsyncMock
import sys
import os
from pathlib import Path
# Add the app directory to the path
sys.path.append(str(Path(__file__).parent.parent))

from app.core.config_service import ConfigService


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
    """Mock configuration service for unit tests"""
    mock_config = Mock(spec=ConfigService)
    mock_config.postgres_host = "test_host"
    mock_config.postgres_port = 5432
    mock_config.postgres_user = "test_user"
    mock_config.postgres_password = "test_pass"
    mock_config.postgres_db = "test_db"
    mock_config.redis_url = "redis://localhost:6379/1"
    mock_config.qdrant_host = "localhost"
    mock_config.qdrant_port = 6333
    return mock_config


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
