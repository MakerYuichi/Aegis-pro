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
    pool_recycle=3600
)

# Create session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()

async def init_db():
    """Initialize database connection and create tables if needed"""
    try:
        async with engine.begin() as conn:
            logger.info("✅ Database connected successfully")
            # Create alert_history table if it doesn't exist
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

# Simple function to get session - no async generator
async def get_db():
    """Get database session"""
    async with AsyncSessionLocal() as session:
        return session