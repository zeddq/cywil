"""
Enhanced database management with connection pooling and unit of work pattern.
"""
from typing import Optional, AsyncGenerator, Any, Dict
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    create_async_engine, 
    AsyncSession, 
    AsyncEngine,
    async_sessionmaker
)
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, Engine, pool, event
from sqlalchemy.pool import NullPool, QueuePool
import logging
import asyncio
from datetime import datetime
from fastapi import Request, Depends
from typing import Annotated
from .config_service import get_config, ConfigService
from .service_interface import ServiceInterface, HealthCheckResult, ServiceStatus
from ..models import init_db

logger = logging.getLogger(__name__)


class DatabaseManager(ServiceInterface):
    """
    Manages database connections with proper pooling and lifecycle management.
    """
    
    def __init__(self, config_service: ConfigService):
        super().__init__("DatabaseManager")
        self._async_engine: Optional[AsyncEngine] = None
        self._sync_engine: Optional[Engine] = None
        self._async_session_factory: Optional[async_sessionmaker] = None
        self._sync_session_factory: Optional[Engine] = None
        self._config = config_service.config
        self._initialized = False
    
    async def _initialize_impl(self) -> None:
        """Initialize database engines and session factories"""
        # Create async engine with connection pooling
        self._async_engine = create_async_engine(
            self._config.postgres.async_url,
            echo=self._config.debug,
            pool_size=self._config.postgres.pool_size,
            max_overflow=self._config.postgres.max_overflow,
            pool_pre_ping=True,  # Verify connections before using
            pool_recycle=3600)
        
        # Create sync engine for migrations and scripts
        self._sync_engine = create_engine(
            self._config.postgres.sync_url,
            echo=self._config.debug,
            pool_size=self._config.postgres.pool_size,
            max_overflow=self._config.postgres.max_overflow,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        
        # Create session factories
        self._async_session_factory = async_sessionmaker(
            self._async_engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        from sqlalchemy.orm import sessionmaker
        self._sync_session_factory = sessionmaker(
            self._sync_engine,
            expire_on_commit=False
        )
        
        # Test connection
        try:
            with self._sync_engine.begin() as engine:
                init_db(engine)
            async with self._async_engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(text("""SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;"""))
            logger.info("Database connection established")
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    async def _shutdown_impl(self) -> None:
        """Shutdown database connections"""
        if self._async_engine:
            await self._async_engine.dispose()
        if self._sync_engine:
            self._sync_engine.dispose()
    
    async def _health_check_impl(self) -> HealthCheckResult:
        """Check database health"""
        try:
            async with self._async_engine.begin() as conn:
                from sqlalchemy import text
                result = await conn.execute(text("SELECT 1"))
                _ = result.scalar()
            
            # Get pool statistics
            pool_status = self._async_engine.pool.status()
            
            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message="Database connection healthy",
                details={
                    "pool_status": pool_status,
                    "url": self._config.postgres.host
                }
            )
        except Exception as e:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message=f"Database health check failed: {str(e)}"
            )
    
    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get an async database session with automatic transaction management.
        """
        if not self._async_session_factory:
            raise RuntimeError("Database not initialized")
        
        async with self._async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    
    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Explicit transaction context manager.
        """
        async with self.get_session() as session:
            async with session.begin():
                yield session
    
    def get_sync_session(self) -> Session:
        """Get a synchronous session (for scripts and migrations)"""
        if not self._sync_session_factory:
            raise RuntimeError("Database not initialized")
        return self._sync_session_factory()
    
    @property
    def async_engine(self) -> AsyncEngine:
        """Get the async engine"""
        return self._async_engine
    
    @property
    def sync_engine(self) -> Engine:
        """Get the sync engine"""
        return self._sync_engine


class UnitOfWork:
    """
    Implements the Unit of Work pattern for managing database transactions.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        self._db_manager = db_manager
        self._session: Optional[AsyncSession] = None
        self._committed = False
        self._rolled_back = False
    
    async def __aenter__(self):
        """Enter the unit of work context"""
        self._session = await self._db_manager.get_session().__aenter__()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the unit of work context"""
        if exc_type:
            await self.rollback()
        elif not self._committed and not self._rolled_back:
            await self.commit()
        
        await self._session.close()
    
    async def commit(self):
        """Commit the transaction"""
        if self._committed or self._rolled_back:
            raise RuntimeError("Transaction already completed")
        
        await self._session.commit()
        self._committed = True
    
    async def rollback(self):
        """Rollback the transaction"""
        if self._committed or self._rolled_back:
            raise RuntimeError("Transaction already completed")
        
        await self._session.rollback()
        self._rolled_back = True
    
    @property
    def session(self) -> AsyncSession:
        """Get the current session"""
        if not self._session:
            raise RuntimeError("Unit of work not started")
        return self._session


class DatabaseTransaction:
    """
    Decorator for transactional methods.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        self._db_manager = db_manager
    
    def __call__(self, func):
        """Wrap function in a transaction"""
        async def wrapper(*args, **kwargs):
            async with self._db_manager.transaction() as session:
                # Inject session as first argument if not present
                if 'session' not in kwargs:
                    return await func(session, *args, **kwargs)
                else:
                    return await func(*args, **kwargs)
        return wrapper


# Connection event listeners for monitoring
def _log_connection_info(dbapi_conn, connection_record):
    """Log connection pool events"""
    logger.debug(f"Database connection checked out from pool")


def _log_connection_close(dbapi_conn, connection_record):
    """Log connection close events"""
    logger.debug(f"Database connection returned to pool")


def get_database_manager(request: Request) -> DatabaseManager:
    return request.app.state.manager.inject_service(DatabaseManager)

DatabaseManagerDep = Annotated[DatabaseManager, Depends(get_database_manager)]
