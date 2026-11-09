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
    from sqlalchemy import Integer, inspect, select, text
    from models.application import Application
    from models.job import Job
    from core.application_lifecycle import TRANSITIONS, history_entry

    async with engine.begin() as conn:
        legacy_ids = await conn.run_sync(lambda sync: inspect(sync).has_table("jobs") and not isinstance(
            next(column["type"] for column in inspect(sync).get_columns("jobs") if column["name"] == "id"), Integer
        ))
        if legacy_ids:
            raise RuntimeError("This database schema requires integer record IDs.")
        await conn.run_sync(Base.metadata.create_all)

        # SQLAlchemy create_all won't add columns to tables that already exist.
        json_type = "JSONB" if conn.dialect.name == "postgresql" else "JSON"
        datetime_type = (
            "TIMESTAMP WITHOUT TIME ZONE"
            if conn.dialect.name == "postgresql"
            else "DATETIME"
        )
        _new_columns = [
            ("jobs", "sponsorship_status", "VARCHAR(30) DEFAULT 'not_specified'"),
            ("jobs", "sponsorship_evidence", json_type),
            ("jobs", "sponsorship_needs_review", "BOOLEAN DEFAULT FALSE"),
            ("jobs", "sponsorship_method", "VARCHAR(20)"),
            ("jobs", "sponsorship_notes", "TEXT"),
            ("jobs", "sponsorship_checked_at", datetime_type),
            ("jobs", "sponsorship_description_hash", "VARCHAR(64)"),
            ("jobs", "description_source", "VARCHAR(20)"),
            ("jobs", "description_checked_at", datetime_type),
            ("jobs", "description_error", "TEXT"),
            ("jobs", "salary_min", "FLOAT"),
            ("jobs", "salary_max", "FLOAT"),
            ("jobs", "salary_currency", "VARCHAR(3)"),
            ("jobs", "salary_period", "VARCHAR(10)"),
            ("search_configs", "name", "VARCHAR(100) DEFAULT 'Default search'"),
            # jobs — Phase 5 Research Agent fields
            ("jobs",           "fit_summary",           "TEXT"),
            ("jobs",           "talking_points",        json_type),
            ("jobs",           "researched_at",         datetime_type),
            # search_configs — configurable search depth + auto-research
            ("search_configs", "max_results_per_search", "INTEGER DEFAULT 15"),
            ("search_configs", "linkedin_pages",          "INTEGER DEFAULT 1"),
            ("search_configs", "auto_research_top_n",     "INTEGER DEFAULT 5"),
            ("applications", "document_status", "VARCHAR(30) DEFAULT 'not_started'"),
            ("applications", "document_error", "TEXT"),
            ("applications", "recruiter_name", "VARCHAR(200)"),
            ("applications", "recruiter_email", "VARCHAR(320)"),
            ("applications", "recruiter_phone", "VARCHAR(100)"),
            ("applications", "notes", "TEXT"),
            ("applications", "preparation_notes", "TEXT"),
            ("applications", "outcome", "TEXT"),
            ("applications", "deadline_at", datetime_type),
            ("applications", "follow_up_at", datetime_type),
            ("applications", "follow_up_completed_at", datetime_type),
            ("applications", "status_history", json_type),
            ("agent_events", "run_id", "INTEGER"),
        ]
        columns = await conn.run_sync(
            lambda sync_conn: {
                table: {column["name"] for column in inspect(sync_conn).get_columns(table)}
                for table in {entry[0] for entry in _new_columns}
            }
        )
        for table, col, col_type in _new_columns:
            if col not in columns[table]:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))

        application_table = Application.__table__
        job_table = Job.__table__
        from core.sponsorship import assessment_values, classify, description_hash
        # Give existing jobs a rules-only assessment without making AI requests at startup.
        unclassified = (await conn.execute(select(job_table.c.id, job_table.c.description, job_table.c.updated_at,
                                                job_table.c.sponsorship_description_hash))).mappings().all()
        for job in unclassified:
            # Keep a saved assessment, including its AI review, when nothing has changed.
            if job["sponsorship_description_hash"] == description_hash(job["description"]):
                continue
            # Preserve the job's update date while filling these assessment fields.
            await conn.execute(job_table.update().where(job_table.c.id == job["id"]).values(
                **assessment_values(job["description"], classify(job["description"])), updated_at=job["updated_at"]
            ))
        rows = (await conn.execute(select(application_table))).mappings().all()
        for row in rows:
            values = {}
            legacy_status = row["status"]
            if "notes" not in columns["applications"] and row["apply_notes"]:
                values["notes"] = row["apply_notes"]
            if "outcome" not in columns["applications"] and row["rejection_reason"]:
                values["outcome"] = row["rejection_reason"]
            if "document_status" not in columns["applications"] and row["one_pager_path"]:
                values["document_status"] = "ready"
            if legacy_status not in TRANSITIONS:
                values["status"] = {"draft": "saved", "offered": "offer"}.get(legacy_status, "preparing")
                values["document_status"] = (
                    "failed" if legacy_status == "failed"
                    else "ready" if row["one_pager_path"]
                    else "not_started"
                )
                if legacy_status == "generating":
                    values["document_status"] = "failed"
                    values["document_error"] = "Generation was interrupted. Please regenerate documents."
            if not row["status_history"]:
                values["status_history"] = [history_entry(
                    None, values.get("status", legacy_status), "Imported existing application"
                )]
            if values:
                await conn.execute(application_table.update().where(
                    application_table.c.id == row["id"]
                ).values(**values))

        legacy_jobs = (await conn.execute(select(job_table).where(
            job_table.c.status.in_([*TRANSITIONS, "applying", "offered"])
        ))).mappings().all()
        for job in legacy_jobs:
            status = {"applying": "preparing", "offered": "offer"}.get(job["status"], job["status"])
            existing = (await conn.execute(select(application_table).where(
                application_table.c.job_id == job["id"]
            ))).mappings().first()
            if existing is None:
                await conn.execute(application_table.insert().values(
                    job_id=job["id"], status=status,
                    status_history=[history_entry(None, status, "Imported job tracking status")],
                ))
            elif existing["status"] in ("saved", "preparing") and status not in ("saved", "preparing"):
                await conn.execute(application_table.update().where(
                    application_table.c.id == existing["id"]
                ).values(status=status, status_history=[
                    *(existing["status_history"] or []),
                    history_entry(existing["status"], status, "Imported job tracking status"),
                ]))
            await conn.execute(job_table.update().where(job_table.c.id == job["id"]).values(
                status="ranked" if job["fit_score"] is not None else "new"
            ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_applications_job_id ON applications (job_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_agent_events_run_id ON agent_events (run_id)"
        ))


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
