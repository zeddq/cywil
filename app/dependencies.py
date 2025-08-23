
from typing import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database_manager import DatabaseManager


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with request.app.state.manager.inject_service(DatabaseManager).get_session() as session:
        yield session
