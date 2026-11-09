"""
JobForge — Job model
Stores every job found across all portals.
"""

from datetime import datetime
from sqlalchemy import Integer, String, Float, DateTime, Text, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    # Core job info
    title: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    description_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sponsorship_status: Mapped[str] = mapped_column(String(30), default="not_specified", index=True)
    sponsorship_evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    sponsorship_needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    sponsorship_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sponsorship_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sponsorship_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sponsorship_description_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    salary_range: Mapped[str | None] = mapped_column(String(255), nullable=True)
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    salary_period: Mapped[str | None] = mapped_column(String(10), nullable=True)
    job_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # full-time, contract...
    remote: Mapped[bool] = mapped_column(Boolean, default=False)

    # Source
    portal: Mapped[str] = mapped_column(String(50))  # linkedin, indeed, etc.
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Rank / Research Agent scores (filled after research)
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)      # 0–100 overall
    tech_score: Mapped[float | None] = mapped_column(Float, nullable=True)     # technical fit
    exp_score: Mapped[float | None] = mapped_column(Float, nullable=True)      # experience fit
    location_score: Mapped[float | None] = mapped_column(Float, nullable=True) # location/remote fit
    growth_score: Mapped[float | None] = mapped_column(Float, nullable=True)   # career growth
    strengths: Mapped[list | None] = mapped_column(JSON, nullable=True)        # ["Python match", ...]
    gaps: Mapped[list | None] = mapped_column(JSON, nullable=True)             # ["Needs Kubernetes"]
    fit_summary: Mapped[str | None] = mapped_column(Text, nullable=True)       # 2-3 sentence honest assessment
    talking_points: Mapped[list | None] = mapped_column(JSON, nullable=True)   # interview / cover-letter tips
    researched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(
        String(30), default="new", index=True
    )

    # Timestamps
    found_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<Job {self.title} @ {self.company} [{self.fit_score}]>"
