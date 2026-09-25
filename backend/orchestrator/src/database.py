from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text
from src.config import settings
from loguru import logger

# Convert to asyncpg URL
DATABASE_URL = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

# Create engine
engine = create_async_engine(
    DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# Create session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def init_db():
    """Initialize database connection and create tables if needed."""
    try:
        async with engine.begin() as conn:
            logger.info("✅ Database connected successfully")
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS alert_history (
                    id SERIAL PRIMARY KEY,
                    engineer_name VARCHAR(255),
                    service_name VARCHAR(255),
                    message TEXT,
                    status VARCHAR(50) DEFAULT 'sent',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.commit()
    except Exception as e:
        logger.warning(f"⚠️ Database connection failed (continuing without DB): {e}")


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an open database session; close it when the caller exits.

    Usage:
        async with get_db_session() as session:
            await session.execute(...)
            await session.commit()

    This is the correct session lifecycle. The old get_db() returned a
    session that was already closed by its own context manager — callers
    got a closed session, and every statement triggered an implicit
    reconnect. See #74.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            # Roll back any in-flight transaction before the context
            # manager closes the session. Without this, a failed
            # statement leaves a half-open transaction on the connection
            # until the connection is returned to the pool.
            await session.rollback()
            raise


async def get_db():
    """
    DEPRECATED — returns a closed session. Use get_db_session() instead.

    This shim exists so that un-migrated callers fail loudly during the
    #74 migration instead of silently leaking connections. Once all 32
    call sites are migrated (see PR for #74), this function is deleted.

    Raises:
        RuntimeError: always.
    """
    raise RuntimeError(
        "get_db() is deprecated and unsafe (see #74). "
        "Use `async with get_db_session() as session:` instead. "
        "If you are seeing this in a test, update the mock target to "
        "`src.<module>.get_db_session`."
    )
