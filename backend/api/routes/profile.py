"""Profile CRUD + resume upload/parse endpoints."""

from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from core.database import get_db
from core.resume_parser import ResumeParser
from models.profile import UserProfile

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


@router.post("/parse-resume")
async def parse_resume(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a PDF or DOCX resume.
    Returns parsed profile fields — does NOT save automatically.
    The frontend shows the result for user review, then calls POST /api/profile to save.
    """
    # Validate extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Please upload a PDF or DOCX file.",
        )

    # Read and size-check
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="File is too large. Maximum size is 5 MB.",
        )

    # Parse
    parser = ResumeParser(db=db)
    try:
        if ext == ".pdf":
            parsed = await parser.parse_pdf(content)
        else:
            parsed = await parser.parse_docx(content)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error parsing resume: {str(e)}",
        )

    return {
        "parsed": parsed,
        "message": "Resume parsed successfully. Review the fields below and click Save Profile.",
    }
