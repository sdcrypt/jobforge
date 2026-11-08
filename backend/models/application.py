"""
JobForge — Application model
Tracks the application lifecycle independently of document generation.
"""

from datetime import datetime
from sqlalchemy import Integer, String, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id"), index=True, unique=True)

    status: Mapped[str] = mapped_column(String(30), default="saved", index=True)

    # Generated documents
    one_pager_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cover_letter_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    one_pager_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_letter_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Apply agent results
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    apply_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # "automated" | "manual" | "email"
    apply_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Interview tracking
    interview_rounds: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # [{"round": 1, "type": "technical", "date": "...", "notes": "..."}]

    # Outcome
    offer_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    document_status: Mapped[str] = mapped_column(String(30), default="not_started")
    document_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    recruiter_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recruiter_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    recruiter_phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    preparation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    follow_up_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_history: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<Application job={self.job_id} status={self.status}>"


class AgentEvent(Base):
    """Persisted log of every agent action — shown in the UI activity feed."""

    __tablename__ = "agent_events"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    agent: Mapped[str] = mapped_column(String(50))         # "search", "rank", "docgen"...
    status: Mapped[str] = mapped_column(String(20))        # "started" | "thinking" | "done" | "error"
    message: Mapped[str] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
