import logging
from typing import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database_manager import DatabaseManager
from app.services.embedding_service import EmbeddingService
from app.services.statute_ingestion_service import StatuteIngestionService
from app.services.supreme_court_ingest_service import SupremeCourtIngestService

logger = logging.getLogger(__name__)

def get_embedding_service(request: Request) -> EmbeddingService:
    return request.app.state.manager.inject_service(EmbeddingService)

def get_statute_ingestion_service(request: Request) -> StatuteIngestionService:
    return request.app.state.manager.inject_service(StatuteIngestionService)

def get_supreme_court_ingest_service(request: Request) -> SupremeCourtIngestService:
    return request.app.state.manager.inject_service(SupremeCourtIngestService)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with request.app.state.manager.inject_service(DatabaseManager).get_session() as session:
        try:
            yield session
        finally:
            await session.close()


