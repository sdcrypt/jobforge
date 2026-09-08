"""
JobForge — Application model
Tracks every job application from draft → offer/rejected.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), index=True)

    # Pipeline status
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    # draft → ready → applied → screening → interviewing → offer → accepted → rejected

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

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    agent: Mapped[str] = mapped_column(String(50))         # "search", "rank", "docgen"...
    status: Mapped[str] = mapped_column(String(20))        # "started" | "thinking" | "done" | "error"
    message: Mapped[str] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
