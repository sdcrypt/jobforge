"""
JobForge — Async database setup (SQLAlchemy 2.0)
Default: SQLite (zero setup). Swap DATABASE_URL in .env for PostgreSQL.
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from core.config import settings


# Engine — works with both SQLite and PostgreSQL
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    # SQLite-specific: allow usage across threads
    connect_args={"check_same_thread": False}
    if "sqlite" in settings.database_url
    else {},
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


async def init_db():
    """Create all tables on startup and run lightweight column migrations."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # SQLAlchemy create_all won't add columns to tables that already exist.
        json_type = "JSONB" if "postgresql" in settings.database_url else "JSON"
        datetime_type = (
            "TIMESTAMP WITHOUT TIME ZONE"
            if "postgresql" in settings.database_url
            else "DATETIME"
        )
        _new_columns = [
            # jobs — Phase 5 Research Agent fields
            ("jobs",           "fit_summary",           "TEXT"),
            ("jobs",           "talking_points",        json_type),
            ("jobs",           "researched_at",         datetime_type),
            # search_configs — configurable search depth + auto-research
            ("search_configs", "max_results_per_search", "INTEGER DEFAULT 15"),
            ("search_configs", "linkedin_pages",          "INTEGER DEFAULT 1"),
            ("search_configs", "auto_research_top_n",     "INTEGER DEFAULT 5"),
        ]
        for table, col, col_type in _new_columns:
            await conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}")
            )


async def get_db():
    """FastAPI dependency — yields a DB session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
