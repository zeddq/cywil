"""
Compatibility shim for legacy tests expecting app.database.
Exports AsyncSessionLocal and init_db by delegating to the current database manager.
"""
from app.core.database_manager import (
    get_async_session_factory as AsyncSessionLocal,  # type: ignore
    init_database as init_db,
)


