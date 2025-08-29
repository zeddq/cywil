"""
Compatibility shim for legacy tests expecting app.database.
Exports AsyncSessionLocal and init_db by delegating to the current database manager.
"""

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from app.core.database_manager import DatabaseManager
from app.core.config_service import get_config, ConfigService
from app.models import init_db

# Create a database manager instance for legacy compatibility
_config_service = ConfigService()
_db_manager = DatabaseManager(_config_service)

# Create async session factory that matches the legacy AsyncSessionLocal interface
AsyncSessionLocal = async_sessionmaker[AsyncSession](
    bind=None,  # Will be set when the database manager is initialized
    class_=AsyncSession,
    expire_on_commit=False,
)

# Export init_db for compatibility
__all__ = ["AsyncSessionLocal", "init_db"]

