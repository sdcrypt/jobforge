"""
JobForge — SearchConfig model
Stores what to search for across which portals.
Users configure this once; the Search Agent reads it every run.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class SearchConfig(Base):
    __tablename__ = "search_configs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # What to search
    keywords: Mapped[list] = mapped_column(JSON)
    # ["Senior Python Developer", "Backend Engineer", "FastAPI Developer"]

    locations: Mapped[list] = mapped_column(JSON)
    # ["remote", "London", "Berlin"]

    portals: Mapped[list] = mapped_column(JSON, default=lambda: ["linkedin", "indeed"])
    # ["linkedin", "indeed"] — more added in later phases

    # Filters
    remote_only: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_within_days: Mapped[int] = mapped_column(Integer, default=7)
    # Only fetch jobs posted in last N days

    # Schedule
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    run_every_hours: Mapped[int] = mapped_column(Integer, default=12)
    # 0 = manual only

    # State
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_found: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<SearchConfig keywords={self.keywords} portals={self.portals}>"
