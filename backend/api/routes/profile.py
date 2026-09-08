"""Profile CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Any
from core.database import get_db
from models.profile import UserProfile

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileCreate(BaseModel):
    full_name: str
    email: str
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    headline: str | None = None
    summary: str | None = None
    skills: list[dict] | None = None
    experience: list[dict] | None = None
    education: list[dict] | None = None
    target_roles: list[str] | None = None
    preferred_locations: list[str] | None = None
    remote_preference: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = "USD"
    tone: str | None = "professional"


@router.post("", status_code=201)
async def create_profile(data: ProfileCreate, db: AsyncSession = Depends(get_db)):
    """Create or update the user profile (upsert by email)."""
    result = await db.execute(
        select(UserProfile).where(UserProfile.email == data.email)
    )
    profile = result.scalar_one_or_none()

    if profile:
        # Update existing
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(profile, field, value)
    else:
        profile = UserProfile(**data.model_dump())
        db.add(profile)

    await db.flush()
    return {"id": profile.id, "message": "Profile saved."}


@router.get("")
async def get_profile(db: AsyncSession = Depends(get_db)):
    """Get the first (and only) user profile."""
    result = await db.execute(select(UserProfile).limit(1))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="No profile found. Create one first.")
    return profile
