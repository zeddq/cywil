"""
Comprehensive tests for DatabaseManager with connection pooling and transactions.
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

from app.core.database_manager import DatabaseManager, UnitOfWork, DatabaseTransaction
from app.core.service_interface import ServiceStatus


@pytest.fixture
def mock_config():
    """Mock configuration for testing"""
    config = Mock()
    config.postgres.async_url = "postgresql+asyncpg://test:test@localhost/test"
    config.postgres.sync_url = "postgresql://test:test@localhost/test"
    config.postgres.pool_size = 5
    config.postgres.max_overflow = 10
    config.debug = False
    return config


@pytest.fixture
async def db_manager(mock_config):
    """Create DatabaseManager instance with mocked config"""
    with patch('app.core.database_manager.get_config', return_value=mock_config):
        manager = DatabaseManager()
        yield manager
        # Cleanup
        if manager._initialized:
            await manager.shutdown()


class TestDatabaseManagerInitialization:
    """Test DatabaseManager initialization and lifecycle"""
    
    @pytest.mark.asyncio
    async def test_successful_initialization(self, db_manager, mock_config):
        """Test successful database initialization"""
        # Mock engine creation
        mock_async_engine = Mock(spec=AsyncEngine)
        mock_sync_engine = Mock()
        
        with patch('app.core.database_manager.create_async_engine', return_value=mock_async_engine), \
             patch('app.core.database_manager.create_engine', return_value=mock_sync_engine):
            
            # Mock connection test
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(return_value=None)
            mock_async_engine.begin = AsyncMock(return_value=mock_conn)
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=None)
            
            await db_manager.initialize()
            
            assert db_manager._initialized
            assert db_manager._async_engine is not None
            assert db_manager._sync_engine is not None
            from sqlalchemy import text
            mock_conn.execute.assert_called_once_with(text("SELECT 1"))
    
    @pytest.mark.asyncio
    async def test_initialization_failure(self, db_manager):
        """Test initialization failure handling"""
        with patch('app.core.database_manager.create_async_engine', side_effect=Exception("Connection failed")):
            with pytest.raises(Exception, match="Connection failed"):
                await db_manager.initialize()
            
            assert not db_manager._initialized
            assert db_manager._status == ServiceStatus.UNHEALTHY
    
    @pytest.mark.asyncio
    async def test_double_initialization(self, db_manager):
        """Test that double initialization is handled gracefully"""
        mock_engine = Mock(spec=AsyncEngine)
        
        with patch('app.core.database_manager.create_async_engine', return_value=mock_engine), \
             patch('app.core.database_manager.create_engine'):
            
            # Mock successful connection
            mock_conn = AsyncMock()
            mock_engine.begin = AsyncMock(return_value=mock_conn)
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=None)
            
            await db_manager.initialize()
            await db_manager.initialize()  # Second call
            
            # Should only create engine once
            assert mock_engine.begin.call_count == 1


class TestConnectionPooling:
    """Test connection pooling behavior"""
    
    @pytest.mark.asyncio
    async def test_pool_configuration(self, mock_config):
        """Test that pool is configured correctly"""
        with patch('app.core.database_manager.create_async_engine') as mock_create:
            with patch('app.core.database_manager.get_config', return_value=mock_config):
                manager = DatabaseManager()
                
                # Initialize to trigger engine creation
                mock_engine = Mock()
                mock_create.return_value = mock_engine
                mock_conn = AsyncMock()
                mock_engine.begin = AsyncMock(return_value=mock_conn)
                mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_conn.__aexit__ = AsyncMock(return_value=None)
                
                await manager.initialize()
                
                # Verify pool configuration
                mock_create.assert_called_once_with(
                    mock_config.postgres.async_url,
                    echo=False,
                    pool_size=5,
                    max_overflow=10,
                    pool_pre_ping=True,
                    pool_recycle=3600
                )
    
    @pytest.mark.asyncio
    async def test_pool_exhaustion(self, db_manager):
        """Test behavior when connection pool is exhausted"""
        # This would require a more complex setup with actual pool testing
        # For now, we'll test the concept
        mock_session_factory = AsyncMock()
        db_manager._async_session_factory = mock_session_factory
        db_manager._initialized = True
        
        # Simulate pool exhaustion
        mock_session_factory.side_effect = OperationalError("QueuePool limit exceeded", None, None)
        
        with pytest.raises(OperationalError, match="QueuePool limit exceeded"):
            async with db_manager.get_session() as session:
                pass


class TestTransactionManagement:
    """Test transaction management and session handling"""
    
    @pytest.mark.asyncio
    async def test_successful_transaction(self, db_manager):
        """Test successful transaction with auto-commit"""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session_factory = Mock(return_value=mock_session)
        
        db_manager._async_session_factory = mock_session_factory
        db_manager._initialized = True
        
        # Configure async context manager
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        async with db_manager.get_session() as session:
            assert session == mock_session
            # Simulate some work
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))
        
        # Verify commit was called
        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()
        mock_session.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_transaction_rollback_on_exception(self, db_manager):
        """Test automatic rollback on exception"""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session_factory = Mock(return_value=mock_session)
        
        db_manager._async_session_factory = mock_session_factory
        db_manager._initialized = True
        
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        with pytest.raises(ValueError):
            async with db_manager.get_session() as session:
                raise ValueError("Test error")
        
        # Verify rollback was called
        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()
        mock_session.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_explicit_transaction_context(self, db_manager):
        """Test explicit transaction context manager"""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session_factory = Mock(return_value=mock_session)
        
        db_manager._async_session_factory = mock_session_factory
        db_manager._initialized = True
        
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.begin = AsyncMock()
        mock_session.begin.return_value.__aenter__ = AsyncMock()
        mock_session.begin.return_value.__aexit__ = AsyncMock()
        
        async with db_manager.transaction() as session:
            assert session == mock_session
        
        mock_session.begin.assert_called_once()


class TestUnitOfWork:
    """Test Unit of Work pattern implementation"""
    
    @pytest.mark.asyncio
    async def test_unit_of_work_commit(self, db_manager):
        """Test UoW with successful commit"""
        mock_session = AsyncMock(spec=AsyncSession)
        db_manager.get_session = AsyncMock()
        
        # Configure the context manager
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock()
        db_manager.get_session.return_value = cm
        
        uow = UnitOfWork(db_manager)
        
        async with uow:
            assert uow.session == mock_session
            # Simulate work
            from sqlalchemy import text
            await uow.session.execute(text("SELECT 1"))
        
        assert uow._committed
        assert not uow._rolled_back
        mock_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_unit_of_work_rollback(self, db_manager):
        """Test UoW with rollback on exception"""
        mock_session = AsyncMock(spec=AsyncSession)
        db_manager.get_session = AsyncMock()
        
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock()
        db_manager.get_session.return_value = cm
        
        uow = UnitOfWork(db_manager)
        
        with pytest.raises(ValueError):
            async with uow:
                raise ValueError("Test error")
        
        assert not uow._committed
        assert uow._rolled_back
        mock_session.rollback.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_unit_of_work_manual_commit(self, db_manager):
        """Test manual commit in UoW"""
        mock_session = AsyncMock(spec=AsyncSession)
        db_manager.get_session = AsyncMock()
        
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock()
        db_manager.get_session.return_value = cm
        
        uow = UnitOfWork(db_manager)
        
        async with uow:
            await uow.commit()
            assert uow._committed
        
        # Should not commit again on exit
        assert mock_session.commit.call_count == 1
    
    @pytest.mark.asyncio
    async def test_unit_of_work_double_commit_error(self, db_manager):
        """Test error on double commit"""
        mock_session = AsyncMock(spec=AsyncSession)
        db_manager.get_session = AsyncMock()
        
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock()
        db_manager.get_session.return_value = cm
        
        uow = UnitOfWork(db_manager)
        
        async with uow:
            await uow.commit()
            with pytest.raises(RuntimeError, match="Transaction already completed"):
                await uow.commit()


class TestHealthCheck:
    """Test health check functionality"""
    
    @pytest.mark.asyncio
    async def test_healthy_database(self, db_manager):
        """Test health check with healthy database"""
        mock_engine = Mock(spec=AsyncEngine)
        mock_engine.pool = Mock()
        mock_engine.pool.status.return_value = "Pool size: 5, Connections: 2"
        
        db_manager._async_engine = mock_engine
        db_manager._initialized = True
        
        # Mock successful query
        mock_conn = AsyncMock()
        mock_result = Mock()
        mock_result.scalar = Mock(return_value=1)
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_engine.begin = AsyncMock(return_value=mock_conn)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        
        result = await db_manager.health_check()
        
        assert result.status == ServiceStatus.HEALTHY
        assert "pool_status" in result.details
        assert result.message == "Database connection healthy"
    
    @pytest.mark.asyncio
    async def test_unhealthy_database(self, db_manager):
        """Test health check with database connection failure"""
        mock_engine = Mock(spec=AsyncEngine)
        db_manager._async_engine = mock_engine
        db_manager._initialized = True
        
        # Mock connection failure
        mock_engine.begin = AsyncMock(side_effect=OperationalError("Connection refused", None, None))
        
        result = await db_manager.health_check()
        
        assert result.status == ServiceStatus.UNHEALTHY
        assert "Connection refused" in result.message


class TestConcurrentAccess:
    """Test concurrent session access"""
    
    @pytest.mark.asyncio
    async def test_concurrent_sessions(self, db_manager):
        """Test multiple concurrent sessions"""
        mock_sessions = [AsyncMock(spec=AsyncSession) for _ in range(5)]
        call_count = 0
        
        def create_session():
            nonlocal call_count
            session = mock_sessions[call_count]
            call_count += 1
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            return session
        
        mock_session_factory = Mock(side_effect=create_session)
        db_manager._async_session_factory = mock_session_factory
        db_manager._initialized = True
        
        # Create concurrent tasks
        async def use_session(index):
            async with db_manager.get_session() as session:
                from sqlalchemy import text
                await session.execute(text(f"SELECT {index}"))
                await asyncio.sleep(0.01)  # Simulate work
            return index
        
        # Run sessions concurrently
        results = await asyncio.gather(*[use_session(i) for i in range(5)])
        
        assert results == [0, 1, 2, 3, 4]
        assert call_count == 5
        
        # Verify all sessions were properly closed
        for session in mock_sessions:
            session.commit.assert_called_once()
            session.close.assert_called_once()


class TestShutdown:
    """Test graceful shutdown"""
    
    @pytest.mark.asyncio
    async def test_engine_disposal(self, db_manager):
        """Test that engines are properly disposed on shutdown"""
        mock_async_engine = Mock(spec=AsyncEngine)
        mock_sync_engine = Mock()
        
        db_manager._async_engine = mock_async_engine
        db_manager._sync_engine = mock_sync_engine
        db_manager._initialized = True
        
        await db_manager.shutdown()
        
        mock_async_engine.dispose.assert_called_once()
        mock_sync_engine.dispose.assert_called_once()
        assert not db_manager._initialized
