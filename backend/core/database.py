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
    """Create all tables on startup. Also runs lightweight column migrations for SQLite."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # ── Lightweight migrations: add new columns to existing tables ────────
        # SQLAlchemy create_all won't add columns to tables that already exist.
        # These ALTER TABLE statements are idempotent — they silently fail if the
        # column is already there, which is the desired behaviour in dev/prod.
        _new_columns = [
            ("jobs", "fit_summary",    "TEXT"),
            ("jobs", "talking_points", "JSON"),
            ("jobs", "researched_at",  "DATETIME"),
        ]
        for table, col, col_type in _new_columns:
            try:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                )
            except Exception:
                pass  # column already exists — safe to ignore


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
