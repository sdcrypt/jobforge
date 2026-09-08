"""
JobForge — Job model
Stores every job found across all portals.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, Float, DateTime, Text, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Core job info
    title: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    salary_range: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # full-time, contract...
    remote: Mapped[bool] = mapped_column(Boolean, default=False)

    # Source
    portal: Mapped[str] = mapped_column(String(50))  # linkedin, indeed, etc.
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Rank Agent scores (filled after ranking)
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)      # 0–100 overall
    tech_score: Mapped[float | None] = mapped_column(Float, nullable=True)     # technical fit
    exp_score: Mapped[float | None] = mapped_column(Float, nullable=True)      # experience fit
    location_score: Mapped[float | None] = mapped_column(Float, nullable=True) # location/remote fit
    growth_score: Mapped[float | None] = mapped_column(Float, nullable=True)   # career growth
    strengths: Mapped[list | None] = mapped_column(JSON, nullable=True)        # ["Python match", ...]
    gaps: Mapped[list | None] = mapped_column(JSON, nullable=True)             # ["Needs Kubernetes"]

    # Status
    status: Mapped[str] = mapped_column(
        String(30), default="new", index=True
    )
    # new → ranked → saved → applying → applied → interviewing → offered → rejected

    # Timestamps
    found_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<Job {self.title} @ {self.company} [{self.fit_score}]>"
