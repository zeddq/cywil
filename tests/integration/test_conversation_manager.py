"""
Comprehensive tests for ConversationManager with Redis and PostgreSQL.
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
import json
import redis.asyncio as redis
from sqlalchemy import select

from app.core.conversation_manager import ConversationManager, ConversationState
from app.core.database_manager import DatabaseManager
from app.core.config_service import ConfigService
from app.core.service_interface import ServiceStatus
from app.models import ResponseHistory, Case


@pytest.fixture
def mock_config():
    """Mock configuration for testing"""
    config = Mock()
    config.redis.url = "redis://localhost:6379/0"
    return config


@pytest.fixture
def mock_config_service():
    """Mock config service"""
    config_service = Mock(spec=ConfigService)
    config_service.config = Mock()
    config_service.config.redis.url = "redis://localhost:6379/0"
    return config_service


@pytest.fixture
def mock_db_manager():
    """Mock database manager"""
    db_manager = Mock(spec=DatabaseManager)
    db_manager._initialized = True
    db_manager.name = "DatabaseManager"
    return db_manager


@pytest.fixture
async def conversation_manager(mock_config_service, mock_db_manager):
    """Create ConversationManager instance"""
    manager = ConversationManager(mock_db_manager, mock_config_service)
    yield manager


class TestConversationStateManagement:
    """Test ConversationState dataclass"""
    
    def test_conversation_state_creation(self):
        """Test creating conversation state"""
        state = ConversationState(
            conversation_id="conv_123",
            last_response_id="resp_456",
            case_id="case_789",
            user_id="user_abc"
        )
        
        assert state.conversation_id == "conv_123"
        assert state.last_response_id == "resp_456"
        assert state.case_id == "case_789"
        assert state.user_id == "user_abc"
        assert isinstance(state.created_at, datetime)
        assert isinstance(state.updated_at, datetime)
        assert state.metadata == {}
    
    def test_conversation_state_serialization(self):
        """Test serialization to dict"""
        state = ConversationState(
            conversation_id="conv_123",
            metadata={"key": "value"}
        )
        
        data = state.to_dict()
        
        assert data["conversation_id"] == "conv_123"
        assert data["metadata"] == {"key": "value"}
        assert "created_at" in data
        assert "updated_at" in data
    
    def test_conversation_state_deserialization(self):
        """Test deserialization from dict"""
        data = {
            "conversation_id": "conv_123",
            "last_response_id": "resp_456",
            "case_id": "case_789",
            "user_id": "user_abc",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "metadata": {"key": "value"}
        }
        
        state = ConversationState.from_dict(data)
        
        assert state.conversation_id == "conv_123"
        assert state.last_response_id == "resp_456"
        assert state.metadata == {"key": "value"}


class TestInitialization:
    """Test ConversationManager initialization"""
    
    @pytest.mark.asyncio
    async def test_successful_redis_initialization(self, conversation_manager):
        """Test successful Redis connection"""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        
        with patch('redis.asyncio.from_url', return_value=mock_redis):
            await conversation_manager.initialize()
            
            assert conversation_manager._redis_client == mock_redis
            assert conversation_manager._initialized
            mock_redis.ping.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_redis_failure_fallback(self, conversation_manager):
        """Test fallback to memory cache when Redis fails"""
        with patch('redis.asyncio.from_url', side_effect=Exception("Redis connection failed")):
            await conversation_manager.initialize()
            
            assert conversation_manager._redis_client is None
            assert hasattr(conversation_manager, '_memory_cache')
            assert conversation_manager._memory_cache == {}
            assert conversation_manager._initialized


class TestCachingStrategy:
    """Test caching with Redis and memory fallback"""
    
    @pytest.mark.asyncio
    async def test_redis_cache_hit(self, conversation_manager):
        """Test getting conversation from Redis cache"""
        conversation_manager._redis_client = AsyncMock()
        
        # Mock Redis get
        cached_data = {
            "conversation_id": "conv_123",
            "last_response_id": "resp_456",
            "case_id": "case_789",
            "user_id": "user_abc",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "metadata": {}
        }
        conversation_manager._redis_client.get = AsyncMock(return_value=json.dumps(cached_data))
        
        state = await conversation_manager._get_from_cache("conv_123")
        
        assert state is not None
        assert state.conversation_id == "conv_123"
        assert state.last_response_id == "resp_456"
        conversation_manager._redis_client.get.assert_called_once_with("conversation:conv_123")
    
    @pytest.mark.asyncio
    async def test_redis_cache_miss(self, conversation_manager):
        """Test cache miss in Redis"""
        conversation_manager._redis_client = AsyncMock()
        conversation_manager._redis_client.get = AsyncMock(return_value=None)
        
        state = await conversation_manager._get_from_cache("conv_123")
        
        assert state is None
    
    @pytest.mark.asyncio
    async def test_memory_cache_fallback(self, conversation_manager):
        """Test memory cache when Redis is not available"""
        conversation_manager._redis_client = None
        conversation_manager._memory_cache = {}
        
        # Add to memory cache
        state = ConversationState("conv_123")
        conversation_manager._memory_cache["conv_123"] = state
        
        retrieved = await conversation_manager._get_from_cache("conv_123")
        
        assert retrieved == state
    
    @pytest.mark.asyncio
    async def test_save_to_redis_cache(self, conversation_manager):
        """Test saving to Redis cache with TTL"""
        conversation_manager._redis_client = AsyncMock()
        conversation_manager._cache_ttl = timedelta(hours=24)
        
        state = ConversationState("conv_123", user_id="user_abc")
        
        await conversation_manager._save_to_cache(state)
        
        # Verify Redis setex was called with correct parameters
        conversation_manager._redis_client.setex.assert_called_once()
        call_args = conversation_manager._redis_client.setex.call_args
        
        assert call_args[0][0] == "conversation:conv_123"  # key
        assert call_args[0][1] == 86400  # 24 hours in seconds
        
        # Verify JSON data
        saved_data = json.loads(call_args[0][2])
        assert saved_data["conversation_id"] == "conv_123"
        assert saved_data["user_id"] == "user_abc"
    
    @pytest.mark.asyncio
    async def test_save_to_memory_cache(self, conversation_manager):
        """Test saving to memory cache when Redis unavailable"""
        conversation_manager._redis_client = None
        conversation_manager._memory_cache = {}
        
        state = ConversationState("conv_123")
        
        await conversation_manager._save_to_cache(state)
        
        assert "conv_123" in conversation_manager._memory_cache
        assert conversation_manager._memory_cache["conv_123"] == state


class TestDatabasePersistence:
    """Test database persistence operations"""
    
    @pytest.mark.asyncio
    async def test_get_from_database(self, conversation_manager, mock_db_manager):
        """Test retrieving conversation from database"""
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        # Mock query result
        mock_history = Mock(spec=ResponseHistory)
        mock_history.thread_id = "conv_123"
        mock_history.response_id = "resp_456"
        mock_history.case_id = "case_789"
        mock_history.user_id = "user_abc"
        mock_history.created_at = datetime.now()
        
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_history)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        mock_db_manager.get_session.return_value = mock_session
        
        state = await conversation_manager._get_from_db("conv_123")
        
        assert state is not None
        assert state.conversation_id == "conv_123"
        assert state.last_response_id == "resp_456"
        assert state.case_id == "case_789"
    
    @pytest.mark.asyncio
    async def test_save_conversation_history(self, conversation_manager, mock_db_manager):
        """Test saving conversation history to database"""
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_db_manager.get_session.return_value = mock_session
        
        # Mock response history ID generation
        with patch('app.core.conversation_manager.generate_uuid', return_value="hist_123"):
            await conversation_manager.save_conversation_turn(
                conversation_id="conv_123",
                input_messages=[{"role": "user", "content": "Hello"}],
                output="Hi there!",
                response_id="resp_456",
                user_id="user_abc",
                case_id="case_789"
            )
        
        # Verify database operations
        mock_session.add.assert_called_once()
        added_history = mock_session.add.call_args[0][0]
        
        assert added_history.id == "hist_123"
        assert added_history.thread_id == "conv_123"
        assert added_history.response_id == "resp_456"
        assert added_history.output == "Hi there!"
    
    @pytest.mark.asyncio
    async def test_get_conversation_history(self, conversation_manager, mock_db_manager):
        """Test retrieving conversation history with limit"""
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        # Mock history records
        histories = []
        for i in range(3):
            hist = Mock(spec=ResponseHistory)
            hist.input = [{"role": "user", "content": f"Message {i}"}]
            hist.output = f"Response {i}"
            hist.created_at = datetime.now() - timedelta(minutes=i)
            histories.append(hist)
        
        mock_result = Mock()
        mock_result.scalars = Mock(return_value=Mock(all=Mock(return_value=histories)))
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        mock_db_manager.get_session.return_value = mock_session
        
        history = await conversation_manager.get_conversation_history("conv_123", limit=5)
        
        assert len(history) == 3
        assert history[0]["output"] == "Response 0"
        assert history[2]["output"] == "Response 2"


class TestConversationContext:
    """Test conversation context manager"""
    
    @pytest.mark.asyncio
    async def test_conversation_context_new(self, conversation_manager):
        """Test creating new conversation in context"""
        conversation_manager._get_from_cache = AsyncMock(return_value=None)
        conversation_manager._get_from_db = AsyncMock(return_value=None)
        conversation_manager._save_to_cache = AsyncMock()
        
        async with conversation_manager.conversation_context("conv_123") as state:
            assert state.conversation_id == "conv_123"
            assert state.updated_at <= datetime.now()
        
        # Should save to cache on exit
        conversation_manager._save_to_cache.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_conversation_context_existing(self, conversation_manager):
        """Test using existing conversation in context"""
        existing_state = ConversationState(
            conversation_id="conv_123",
            last_response_id="resp_456"
        )
        
        conversation_manager._get_from_cache = AsyncMock(return_value=existing_state)
        conversation_manager._save_to_cache = AsyncMock()
        
        async with conversation_manager.conversation_context("conv_123") as state:
            assert state.conversation_id == "conv_123"
            assert state.last_response_id == "resp_456"
            
            # Modify state
            state.last_response_id = "resp_789"
        
        # Should save updated state
        conversation_manager._save_to_cache.assert_called_once()
        saved_state = conversation_manager._save_to_cache.call_args[0][0]
        assert saved_state.last_response_id == "resp_789"


class TestCaseLinking:
    """Test case linking functionality"""
    
    @pytest.mark.asyncio
    async def test_link_to_case(self, conversation_manager, mock_db_manager):
        """Test linking conversation to case"""
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        # Mock case query
        mock_case = Mock(spec=Case)
        mock_case.id = "case_789"
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_case)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        mock_db_manager.get_session.return_value = mock_session
        
        # Mock cache operations
        conversation_manager._get_from_cache = AsyncMock(return_value=None)
        conversation_manager._save_to_cache = AsyncMock()
        
        await conversation_manager.link_to_case("conv_123", "case_789")
        
        # Verify case was queried
        execute_calls = mock_session.execute.call_args_list
        assert len(execute_calls) >= 1
        
        # Verify state was updated
        conversation_manager._save_to_cache.assert_called()
        saved_state = conversation_manager._save_to_cache.call_args[0][0]
        assert saved_state.case_id == "case_789"


class TestHealthCheck:
    """Test health check functionality"""
    
    @pytest.mark.asyncio
    async def test_healthy_state(self, conversation_manager, mock_db_manager):
        """Test health check with Redis and database healthy"""
        # Mock Redis
        conversation_manager._redis_client = AsyncMock()
        conversation_manager._redis_client.ping = AsyncMock(return_value=True)
        
        # Mock database
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock()
        mock_db_manager.get_session.return_value = mock_session
        
        result = await conversation_manager.health_check()
        
        assert result.status == ServiceStatus.HEALTHY
        assert result.details["redis"] == "connected"
        assert result.details["database"] == "connected"
    
    @pytest.mark.asyncio
    async def test_redis_disconnected(self, conversation_manager, mock_db_manager):
        """Test health check with Redis disconnected"""
        # Mock Redis failure
        conversation_manager._redis_client = AsyncMock()
        conversation_manager._redis_client.ping = AsyncMock(side_effect=Exception("Connection failed"))
        
        # Mock healthy database
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock()
        mock_db_manager.get_session.return_value = mock_session
        
        result = await conversation_manager.health_check()
        
        assert result.status == ServiceStatus.HEALTHY  # Still healthy without Redis
        assert result.details["redis"] == "disconnected"
        assert result.details["database"] == "connected"
    
    @pytest.mark.asyncio
    async def test_database_unhealthy(self, conversation_manager, mock_db_manager):
        """Test health check with database failure"""
        conversation_manager._redis_client = None
        
        # Mock database failure
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock(side_effect=Exception("Database error"))
        mock_db_manager.get_session.return_value = mock_session
        
        result = await conversation_manager.health_check()
        
        assert result.status == ServiceStatus.UNHEALTHY
        assert result.details["database"] == "error"


class TestConcurrentAccess:
    """Test concurrent conversation access"""
    
    @pytest.mark.asyncio
    async def test_concurrent_cache_updates(self, conversation_manager):
        """Test concurrent updates to same conversation"""
        conversation_manager._redis_client = AsyncMock()
        conversation_manager._redis_client.get = AsyncMock(return_value=None)
        conversation_manager._redis_client.setex = AsyncMock()
        
        # Simulate concurrent updates
        async def update_conversation(index):
            async with conversation_manager.conversation_context(f"conv_123") as state:
                state.metadata[f"update_{index}"] = True
                await asyncio.sleep(0.01)  # Simulate work
            return index
        
        # Run updates concurrently
        results = await asyncio.gather(*[update_conversation(i) for i in range(5)])
        
        assert results == [0, 1, 2, 3, 4]
        
        # Should have multiple cache saves
        assert conversation_manager._redis_client.setex.call_count >= 5
    
    @pytest.mark.asyncio
    async def test_memory_cache_thread_safety(self, conversation_manager):
        """Test memory cache with concurrent access"""
        conversation_manager._redis_client = None
        conversation_manager._memory_cache = {}
        
        # Simulate concurrent access to memory cache
        async def access_cache(index):
            state = ConversationState(f"conv_{index}")
            await conversation_manager._save_to_cache(state)
            retrieved = await conversation_manager._get_from_cache(f"conv_{index}")
            return retrieved is not None
        
        # Run concurrent operations
        results = await asyncio.gather(*[access_cache(i) for i in range(10)])
        
        assert all(results)
        assert len(conversation_manager._memory_cache) == 10


class TestEdgeCases:
    """Test edge cases and error scenarios"""
    
    @pytest.mark.asyncio
    async def test_cache_ttl_expiration(self, conversation_manager):
        """Test cache TTL expiration behavior"""
        conversation_manager._cache_ttl = timedelta(seconds=1)
        conversation_manager._redis_client = AsyncMock()
        
        state = ConversationState("conv_123")
        await conversation_manager._save_to_cache(state)
        
        # Verify TTL was set to 1 second
        call_args = conversation_manager._redis_client.setex.call_args
        assert call_args[0][1] == 1  # TTL in seconds
    
    @pytest.mark.asyncio
    async def test_invalid_json_in_cache(self, conversation_manager):
        """Test handling invalid JSON in cache"""
        conversation_manager._redis_client = AsyncMock()
        conversation_manager._redis_client.get = AsyncMock(return_value="invalid json{")
        
        state = await conversation_manager._get_from_cache("conv_123")
        
        assert state is None  # Should handle gracefully
    
    @pytest.mark.asyncio
    async def test_get_or_create_with_metadata(self, conversation_manager):
        """Test get_or_create preserves metadata"""
        conversation_manager._get_from_cache = AsyncMock(return_value=None)
        conversation_manager._get_from_db = AsyncMock(return_value=None)
        conversation_manager._save_to_cache = AsyncMock()
        
        state = await conversation_manager.get_or_create_conversation(
            "conv_123",
            user_id="user_abc",
            case_id="case_789"
        )
        
        assert state.conversation_id == "conv_123"
        assert state.user_id == "user_abc"
        assert state.case_id == "case_789"