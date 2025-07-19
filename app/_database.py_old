from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import create_engine
from sqlmodel import Session as SQLModelSession
from .models import SQLModel
from .config import settings
import logging
# import alembic
from pathlib import Path
from alembic import command
from alembic.config import Config

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

# Sync session factory for auth
SessionLocal = sessionmaker(
    sync_engine,
    class_=Session,
    expire_on_commit=False
)

async def get_db():
    """Dependency for FastAPI routes"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            logger.error(f"Error in get_db: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db():
    """Initialize database tables"""
    logger.info("Connecting to PostgreSQL database to initialize tables")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

def init_db_sync():
    """Initialize database tables synchronously (for scripts)"""
    #run_migrations()
    SQLModel.metadata.create_all(bind=sync_engine)

def get_session():
    """Dependency for synchronous database sessions (used by auth)"""
    with SQLModelSession(sync_engine) as session:
        yield session

# def run_migrations() -> None:
#     """
#     Apply all Alembic migrations up to 'head'.
#     This is intended for local development only.
#     """
#     if not settings.debug:        # or any flag that means "production"
#         return                    # skip in prod / CI

#     # Path to alembic.ini (adjust if it lives elsewhere)
#     alembic_ini = Path(__file__).parent / "alembic.ini"

#     cfg = Config(str(alembic_ini))

#     # Override URL so it always matches your settings
#     cfg.set_main_option("sqlalchemy.url", settings.sync_database_url)

#     # Optionally silence output in tests
#     # cfg.print_stdout = lambda *args, **kw: None

#     command.upgrade(cfg, "head")  # equivalent to `alembic upgrade head`
