"""Profile CRUD + resume upload/parse endpoints."""

from pathlib import Path
import base64
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from core.database import get_db
from models.profile import UserProfile
from core.runs import enqueue_run, run_response

router = APIRouter(prefix="/api/profile", tags=["profile"])

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


# ── Schemas ───────────────────────────────────────────────────────────────────

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


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def get_profile(db: AsyncSession = Depends(get_db)):
    """Return the single user profile."""
    result = await db.execute(select(UserProfile).limit(1))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="No profile found. Create one first.")
    return profile


@router.post("", status_code=201)
async def save_profile(data: ProfileCreate, db: AsyncSession = Depends(get_db)):
    """Create or update the user profile (upsert by email)."""
    result = await db.execute(
        select(UserProfile).where(UserProfile.email == data.email)
    )
    profile = result.scalar_one_or_none()

    if profile:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(profile, field, value)
    else:
        profile = UserProfile(**data.model_dump())
        db.add(profile)

    await db.flush()
    return {"id": profile.id, "message": "Profile saved."}


@router.post("/parse-resume", status_code=202)
async def parse_resume(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a PDF or DOCX resume.
    Queues parsing and returns a run ID. Parsed fields are available in the run's
    result for user review and are never saved to the profile automatically.
    """
    # Validate extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Please upload a PDF or DOCX file.",
        )

    # Read and size-check
    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="File is too large. Maximum size is 5 MB.",
        )

    # Parse
    run, created = await enqueue_run(db, "resume_parse", {"extension": ext, "content": base64.b64encode(content).decode("ascii")})
    return run_response(run, created)
