from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from .models import Base
from .config import settings
import logging

logger = logging.getLogger(__name__)

# Async engine for application use
logger.info(f"Creating async PostgreSQL connection to {settings.postgres_host}:{settings.postgres_port}")
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True
)

# Sync engine for migrations
sync_engine = create_engine(
    settings.sync_database_url,
    echo=settings.debug
)

# Async session factory
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db():
    """Dependency for FastAPI routes"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db():
    """Initialize database tables"""
    logger.info("Connecting to PostgreSQL database to initialize tables")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

def init_db_sync():
    """Initialize database tables synchronously (for scripts)"""
    Base.metadata.create_all(bind=sync_engine)
