"""Application pipeline endpoints — generate docs, apply, track outcomes."""

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.database import get_db
from models.job import Job
from models.profile import UserProfile
from models.application import Application

router = APIRouter(prefix="/api/applications", tags=["applications"])


@router.post("/{job_id}/generate-docs", status_code=202)
async def generate_docs(
    job_id: str,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    """Generate tailored one-pager + cover letter for a job."""
    job = await _get_job(job_id, db)
    profile = await _get_profile(db)
    app = await _get_or_create_application(job_id, db)

    background_tasks.add_task(_run_docgen, job_id)
    return {"message": "DocGen started. Watch /ws for progress.", "application_id": app.id}


async def _run_docgen(job_id: str):
    from core.database import AsyncSessionLocal
    from agents.docgen import DocGenAgent
    async with AsyncSessionLocal() as db:
        job_r = await db.execute(select(Job).where(Job.id == job_id))
        job = job_r.scalar_one_or_none()
        profile_r = await db.execute(select(UserProfile).limit(1))
        profile = profile_r.scalar_one_or_none()
        app_r = await db.execute(select(Application).where(Application.job_id == job_id))
        app = app_r.scalar_one_or_none()

        if not all([job, profile, app]):
            return

        agent = DocGenAgent(db=db, job_id=job_id)
        result = await agent.run(job=job, profile=profile)

        app.one_pager_path = result["one_pager_path"]
        app.one_pager_html = result["one_pager_html"]
        app.cover_letter_text = result["cover_letter_text"]
        app.cover_letter_path = result["cover_letter_path"]
        app.status = "ready"
        await db.commit()


@router.post("/{job_id}/apply", status_code=202)
async def start_apply(
    job_id: str,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    """Start the Apply Agent for a job. Always pauses for user review."""
    job = await _get_job(job_id, db)
    app = await _get_or_create_application(job_id, db)

    if app.status not in ("ready", "draft"):
        raise HTTPException(400, "Generate documents first before applying.")

    background_tasks.add_task(_run_apply, job_id)
    return {"message": "Apply Agent started. A browser window will open for your review."}


async def _run_apply(job_id: str):
    from core.database import AsyncSessionLocal
    from agents.apply import ApplyAgent
    async with AsyncSessionLocal() as db:
        job_r = await db.execute(select(Job).where(Job.id == job_id))
        job = job_r.scalar_one_or_none()
        profile_r = await db.execute(select(UserProfile).limit(1))
        profile = profile_r.scalar_one_or_none()
        app_r = await db.execute(select(Application).where(Application.job_id == job_id))
        app = app_r.scalar_one_or_none()

        if not all([job, profile, app]):
            return

        agent = ApplyAgent(db=db, job_id=job_id)
        result = await agent.run(job=job, profile=profile, application=app)

        if result["status"] == "filled":
            app.status = "applying"
        await db.commit()


@router.get("")
async def list_applications(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Application))
    apps = result.scalars().all()
    return {"applications": apps}


@router.patch("/{job_id}/status")
async def update_status(
    job_id: str,
    status: str,
    db: AsyncSession = Depends(get_db),
):
    """Manually update application status (e.g. after interview)."""
    app_r = await db.execute(select(Application).where(Application.job_id == job_id))
    app = app_r.scalar_one_or_none()
    if not app:
        raise HTTPException(404, "Application not found")
    app.status = status
    await db.flush()
    return {"message": f"Status updated to '{status}'"}


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _get_job(job_id: str, db: AsyncSession) -> Job:
    r = await db.execute(select(Job).where(Job.id == job_id))
    job = r.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    return job


async def _get_profile(db: AsyncSession) -> UserProfile:
    r = await db.execute(select(UserProfile).limit(1))
    profile = r.scalar_one_or_none()
    if not profile:
        raise HTTPException(400, "No profile found. Create one at POST /api/profile")
    return profile


async def _get_or_create_application(job_id: str, db: AsyncSession) -> Application:
    r = await db.execute(select(Application).where(Application.job_id == job_id))
    app = r.scalar_one_or_none()
    if not app:
        app = Application(job_id=job_id)
        db.add(app)
        await db.flush()
    return app
