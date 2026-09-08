"""
JobForge — UserProfile model
The candidate's profile — used by all agents to personalise output.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Personal
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Professional summary (used by DocGen agent)
    headline: Mapped[str | None] = mapped_column(String(512), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Skills, experience, education (stored as JSON for flexibility)
    skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # [{"name": "Python", "level": "expert"}, {"name": "FastAPI", "level": "intermediate"}]

    experience: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # [{"company": "...", "role": "...", "start": "2022-01", "end": "present",
    #   "highlights": ["Built X", "Led Y"]}]

    education: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # [{"institution": "...", "degree": "...", "year": 2020}]

    # Job preferences (used by Search + Rank agents)
    target_roles: Mapped[list | None] = mapped_column(JSON, nullable=True)    # ["Senior Backend Engineer"]
    target_companies: Mapped[list | None] = mapped_column(JSON, nullable=True) # ["Stripe", "Notion"]
    avoid_companies: Mapped[list | None] = mapped_column(JSON, nullable=True)
    preferred_locations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    remote_preference: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # "remote" | "hybrid" | "onsite" | "any"
    salary_min: Mapped[int | None] = mapped_column(nullable=True)
    salary_max: Mapped[int | None] = mapped_column(nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Writing style hints (used by DocGen agent)
    tone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # "professional" | "conversational" | "technical"

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<UserProfile {self.full_name} ({self.email})>"
