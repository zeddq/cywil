"""
FastAPI dependencies for database sessions and other common dependencies.
"""

from typing import AsyncGenerator
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .core.database_manager import DatabaseManager, get_database_manager


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency to provide an async database session.
    Uses the DatabaseManager from the service container.
    """
    db_manager: DatabaseManager = get_database_manager(request)
    async with db_manager.get_session() as session:
        yield session