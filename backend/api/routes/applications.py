"""
Application pipeline endpoints — generate docs, preview, download, apply, track.
"""

from pathlib import Path
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.database import get_db
from models.job import Job
from models.profile import UserProfile
from models.application import Application

router = APIRouter(prefix="/api/applications", tags=["applications"])


# ── Generate docs ─────────────────────────────────────────────────────────────

@router.post("/{job_id}/generate-docs", status_code=202)
async def generate_docs(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger DocGen Agent to produce one-pager + cover letter.
    Watch /ws WebSocket for live progress.
    """
    await _get_job(job_id, db)
    await _get_profile(db)
    app = await _get_or_create_application(job_id, db)

    background_tasks.add_task(_run_docgen, job_id)
    return {
        "message": "DocGen started. Watch ws://localhost:8000/ws for progress.",
        "application_id": app.id,
        "preview_url": f"/api/applications/{job_id}/preview/one-pager",
    }


async def _run_docgen(job_id: str):
    from core.database import AsyncSessionLocal
    from agents.docgen import DocGenAgent
    async with AsyncSessionLocal() as db:
        job = await _get_job(job_id, db)
        profile = await _get_profile(db)
        app = await _get_or_create_application(job_id, db)

        agent = DocGenAgent(db=db, job_id=job_id)
        result = await agent.run(job=job, profile=profile)

        app.one_pager_path = result["one_pager_path"]
        app.one_pager_html = result["one_pager_html"]
        app.cover_letter_path = result["cover_letter_path"]
        app.cover_letter_text = result["cover_letter_text"]
        app.status = "ready"
        await db.commit()


# ── Preview (HTML in browser) ─────────────────────────────────────────────────

@router.get("/{job_id}/preview/one-pager", response_class=HTMLResponse)
async def preview_one_pager(job_id: str, db: AsyncSession = Depends(get_db)):
    """Preview the generated one-pager HTML directly in the browser."""
    app = await _get_application(job_id, db)
    if not app.one_pager_html:
        raise HTTPException(404, "One-pager not generated yet. Call /generate-docs first.")
    return HTMLResponse(content=app.one_pager_html)


@router.get("/{job_id}/preview/cover-letter", response_class=HTMLResponse)
async def preview_cover_letter(job_id: str, db: AsyncSession = Depends(get_db)):
    """Preview the generated cover letter HTML in the browser."""
    app = await _get_application(job_id, db)
    if not app.cover_letter_path:
        raise HTTPException(404, "Cover letter not generated yet. Call /generate-docs first.")
    # Read the HTML file
    html_path = Path(app.cover_letter_path).with_suffix(".html")
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    raise HTTPException(404, "Cover letter HTML file not found.")


# ── Download (PDF) ────────────────────────────────────────────────────────────

@router.get("/{job_id}/download/one-pager")
async def download_one_pager(job_id: str, db: AsyncSession = Depends(get_db)):
    """Download the one-pager as PDF (or HTML if WeasyPrint not installed)."""
    app = await _get_application(job_id, db)
    if not app.one_pager_path:
        raise HTTPException(404, "One-pager not generated yet.")
    path = Path(app.one_pager_path)
    if not path.exists():
        raise HTTPException(404, f"File not found: {path}")
    media_type = "application/pdf" if path.suffix == ".pdf" else "text/html"
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=f"one_pager_{job_id[:8]}{path.suffix}",
    )


@router.get("/{job_id}/download/cover-letter")
async def download_cover_letter(job_id: str, db: AsyncSession = Depends(get_db)):
    """Download the cover letter as PDF (or HTML if WeasyPrint not installed)."""
    app = await _get_application(job_id, db)
    if not app.cover_letter_path:
        raise HTTPException(404, "Cover letter not generated yet.")
    path = Path(app.cover_letter_path)
    if not path.exists():
        raise HTTPException(404, f"File not found: {path}")
    media_type = "application/pdf" if path.suffix == ".pdf" else "text/html"
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=f"cover_letter_{job_id[:8]}{path.suffix}",
    )


# ── Apply ─────────────────────────────────────────────────────────────────────

@router.post("/{job_id}/apply", status_code=202)
async def start_apply(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Start the Apply Agent. Always pauses for user review before submitting."""
    app = await _get_or_create_application(job_id, db)
    if app.status not in ("ready", "draft"):
        raise HTTPException(400, "Generate documents first (POST /generate-docs).")
    background_tasks.add_task(_run_apply, job_id)
    return {"message": "Apply Agent started. A browser window will open for your review."}


async def _run_apply(job_id: str):
    from core.database import AsyncSessionLocal
    from agents.apply import ApplyAgent
    async with AsyncSessionLocal() as db:
        job = await _get_job(job_id, db)
        profile = await _get_profile(db)
        app = await _get_or_create_application(job_id, db)
        agent = ApplyAgent(db=db, job_id=job_id)
        result = await agent.run(job=job, profile=profile, application=app)
        if result["status"] == "filled":
            app.status = "applying"
        await db.commit()


# ── Status + listing ──────────────────────────────────────────────────────────

@router.get("")
async def list_applications(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Application))
    apps = result.scalars().all()
    return {"applications": apps, "count": len(apps)}


@router.get("/{job_id}")
async def get_application(job_id: str, db: AsyncSession = Depends(get_db)):
    app = await _get_application(job_id, db)
    return app


@router.patch("/{job_id}/status")
async def update_status(
    job_id: str,
    status: str,
    db: AsyncSession = Depends(get_db),
):
    """Manually update status (e.g. after an interview)."""
    app = await _get_or_create_application(job_id, db)
    app.status = status
    await db.flush()
    return {"message": f"Status updated to '{status}'"}


# ── Helpers ───────────────────────────────────────────────────────────────────

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


async def _get_application(job_id: str, db: AsyncSession) -> Application:
    r = await db.execute(select(Application).where(Application.job_id == job_id))
    app = r.scalar_one_or_none()
    if not app:
        raise HTTPException(404, "No application found for this job.")
    return app


async def _get_or_create_application(job_id: str, db: AsyncSession) -> Application:
    r = await db.execute(select(Application).where(Application.job_id == job_id))
    app = r.scalar_one_or_none()
    if not app:
        app = Application(job_id=job_id)
        db.add(app)
        await db.flush()
    return app
