"""
Application pipeline endpoints — generate docs, preview, download, apply, track.
"""

from pathlib import Path
import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from core.database import get_db
from core.config import settings
from core.runs import ACTIVE_STATUSES, RunLost, commit_owned, enqueue_run, run_response
from core.application_lifecycle import (
    ApplicationUpdate, StatusChange, TRANSITIONS, history_entry, transition,
)
from models.job import Job
from models.profile import UserProfile
from models.application import AgentEvent, Application
from models.run import TaskRun

router = APIRouter(prefix="/api/applications", tags=["applications"])
log = structlog.get_logger()


# ── Generate docs ─────────────────────────────────────────────────────────────

@router.post("/{job_id}/generate-docs", status_code=202)
async def generate_docs(
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger DocGen Agent to produce one-pager + cover letter.
    Watch /ws WebSocket for live progress.
    """
    await _get_job(job_id, db)
    await _get_profile(db)
    app = await _get_or_create_application(job_id, db)
    if app.status == "saved":
        transition(app, "preparing", "Started preparing application documents")
    app.document_status = "generating"
    app.document_error = None
    run, created = await enqueue_run(db, "docgen", job_id=job_id)
    await db.commit()
    return {
        **run_response(run, created),
        "application_id": app.id,
        "preview_url": f"/api/applications/{job_id}/preview/one-pager",
    }


async def _run_docgen(job_id: int):
    from core.database import AsyncSessionLocal
    from agents.docgen import DocGenAgent
    async with AsyncSessionLocal() as db:
        app = None
        try:
            job = await _get_job(job_id, db)
            profile = await _get_profile(db)
            app = await _get_application(job_id, db)

            agent = DocGenAgent(db=db, job_id=job_id)
            result = await agent.run(job=job, profile=profile)

            app.one_pager_path = result["one_pager_path"]
            app.one_pager_html = result["one_pager_html"]
            app.cover_letter_path = result["cover_letter_path"]
            app.cover_letter_text = result["cover_letter_text"]
            app.document_status = "ready"
            app.document_error = None
        except RunLost:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            app = await _get_application(job_id, db)
            app.document_status = "failed"
            app.document_error = str(exc)[:2000]
            await commit_owned(db)
            raise
        await commit_owned(db)


# ── Preview (HTML in browser) ─────────────────────────────────────────────────

@router.get("/{job_id}/preview/one-pager", response_class=HTMLResponse)
async def preview_one_pager(job_id: int, db: AsyncSession = Depends(get_db)):
    """Preview the generated one-pager HTML directly in the browser."""
    app = await _get_application(job_id, db)
    if not app.one_pager_html:
        raise HTTPException(404, "One-pager not generated yet. Call /generate-docs first.")
    return HTMLResponse(content=app.one_pager_html)


@router.get("/{job_id}/preview/cover-letter", response_class=HTMLResponse)
async def preview_cover_letter(job_id: int, db: AsyncSession = Depends(get_db)):
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
async def download_one_pager(job_id: int, db: AsyncSession = Depends(get_db)):
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
        filename=f"one_pager_{job_id}{path.suffix}",
    )


@router.get("/{job_id}/download/cover-letter")
async def download_cover_letter(job_id: int, db: AsyncSession = Depends(get_db)):
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
        filename=f"cover_letter_{job_id}{path.suffix}",
    )


# ── Apply ─────────────────────────────────────────────────────────────────────

@router.post("/{job_id}/apply", status_code=202)
async def start_apply(
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Start the Apply Agent. Always pauses for user review before submitting."""
    app = await _get_or_create_application(job_id, db)
    if app.document_status != "ready":
        raise HTTPException(400, "Generate documents first (POST /generate-docs).")
    if app.status not in ("saved", "preparing"):
        raise HTTPException(409, "This application has already progressed beyond preparation.")
    run, created = await enqueue_run(db, "apply", job_id=job_id, max_attempts=1)
    return run_response(run, created)


async def _run_apply(job_id: int):
    from core.database import AsyncSessionLocal
    from agents.apply import ApplyAgent
    async with AsyncSessionLocal() as db:
        job = await _get_job(job_id, db)
        profile = await _get_profile(db)
        app = await _get_application(job_id, db)
        agent = ApplyAgent(db=db, job_id=job_id)
        result = await agent.run(job=job, profile=profile, application=app)
        if result["status"] == "filled":
            app.apply_notes = "Form filled; awaiting manual review and submission."
        await commit_owned(db)
        if result.get("status") == "error":
            raise RuntimeError(result.get("message", "Application assistance failed"))
        return result


# ── Status + listing ──────────────────────────────────────────────────────────

@router.get("")
async def list_applications(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Application, Job).join(Job, Application.job_id == Job.id)
        .order_by(Application.updated_at.desc())
    )
    apps = [_serialize(app, job) for app, job in result.all()]
    return {"applications": apps, "count": len(apps)}


@router.get("/{job_id}")
async def get_application(job_id: int, db: AsyncSession = Depends(get_db)):
    app = await _get_application(job_id, db)
    return _serialize(app, await _get_job(job_id, db))


@router.put("/{job_id}")
async def save_application(job_id: int, db: AsyncSession = Depends(get_db)):
    app = await _get_or_create_application(job_id, db)
    return _serialize(app, await _get_job(job_id, db))


@router.delete("/{job_id}")
async def delete_application(job_id: int, db: AsyncSession = Depends(get_db)):
    job_result = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    job = job_result.scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "Job not found")
    app = await _get_application(job_id, db, lock=True)
    active = (await db.execute(select(TaskRun.id).where(
        TaskRun.job_id == job_id, TaskRun.status.in_(ACTIVE_STATUSES)
    ).limit(1))).first()
    if active:
        raise HTTPException(409, "This job has queued or running work. Wait for it to finish before deleting.")
    if app.document_status == "generating":
        raise HTTPException(409, "Documents are being generated. Wait for generation to finish before deleting this application.")

    files = _document_files((app.one_pager_path, app.cover_letter_path))
    other_documents = (await db.execute(
        select(Application.one_pager_path, Application.cover_letter_path)
        .where(Application.id != app.id)
    )).all()
    shared_files = _document_files(path for pair in other_documents for path in pair)
    related_run_ids = select(TaskRun.id).where(TaskRun.job_id == job_id)
    await db.execute(delete(AgentEvent).where(or_(
        AgentEvent.job_id == job_id, AgentEvent.run_id.in_(related_run_ids)
    )))
    await db.execute(delete(TaskRun).where(TaskRun.job_id == job_id))
    await db.delete(app)
    await db.flush()
    await db.delete(job)
    await db.commit()

    cleanup_failed = False
    for path in files - shared_files:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            cleanup_failed = True
            log.warning("application.document_cleanup_failed", job_id=job_id, error=str(exc))
    return {
        "message": "Application and job listing permanently deleted.",
        "cleanup_warning": "Some document files could not be removed from disk." if cleanup_failed else None,
    }


@router.patch("/{job_id}")
async def update_application(
    job_id: int, data: ApplicationUpdate, db: AsyncSession = Depends(get_db),
):
    app = await _get_application(job_id, db, lock=True)
    values = data.model_dump(exclude_unset=True)
    if "interview_rounds" in values:
        identifiers = [entry.id for entry in data.interview_rounds]
        if len(set(identifiers)) != len(identifiers):
            raise HTTPException(422, "Interview round IDs must be unique.")
        values["interview_rounds"] = [
            entry.model_dump(mode="json") for entry in data.interview_rounds
        ]
    if "applied_at" in values and values["applied_at"] is None and app.applied_at is not None:
        raise HTTPException(422, "An existing application date cannot be cleared.")
    if "follow_up_at" in values and values["follow_up_at"] != app.follow_up_at:
        values["follow_up_completed_at"] = None
    follow_up = values.get("follow_up_at", app.follow_up_at)
    if values.get("follow_up_completed_at") and not follow_up:
        raise HTTPException(422, "Set a follow-up reminder before marking it complete.")
    for field, value in values.items():
        setattr(app, field, value)
    await db.flush()
    return _serialize(app, await _get_job(job_id, db))


@router.patch("/{job_id}/status")
async def update_status(
    job_id: int,
    data: StatusChange,
    db: AsyncSession = Depends(get_db),
):
    """Manually update status (e.g. after an interview)."""
    app = await _get_or_create_application(job_id, db)
    if app.status != data.expected_status.value:
        raise HTTPException(409, "Application status changed. Refresh and try again.")
    try:
        transition(app, data.status.value, data.note)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await db.flush()
    return _serialize(app, await _get_job(job_id, db))


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_job(job_id: int, db: AsyncSession) -> Job:
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


async def _get_application(job_id: int, db: AsyncSession, lock: bool = False) -> Application:
    query = select(Application).where(Application.job_id == job_id)
    if lock:
        query = query.with_for_update()
    r = await db.execute(query)
    app = r.scalar_one_or_none()
    if not app:
        raise HTTPException(404, "No application found for this job.")
    return app


async def _get_or_create_application(job_id: int, db: AsyncSession) -> Application:
    job = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    if job.scalar_one_or_none() is None:
        raise HTTPException(404, "Job not found")
    r = await db.execute(
        select(Application).where(Application.job_id == job_id).with_for_update()
    )
    app = r.scalar_one_or_none()
    if not app:
        try:
            async with db.begin_nested():
                app = Application(
                    job_id=job_id, status="saved",
                    status_history=[history_entry(None, "saved", "Saved job")],
                )
                db.add(app)
                await db.flush()
        except IntegrityError:
            app = await _get_application(job_id, db, lock=True)
    return app


def _serialize(app: Application, job: Job) -> dict:
    values = {column.name: getattr(app, column.name) for column in Application.__table__.columns}
    values["job"] = {
        field: getattr(job, field)
        for field in ("id", "title", "company", "url", "location", "portal", "fit_score")
    }
    values["allowed_transitions"] = list(TRANSITIONS.get(app.status, ()))
    return values


def _document_files(paths) -> set[Path]:
    documents_dir = Path(settings.documents_dir).resolve()
    files = set()
    for stored_path in paths:
        if not stored_path:
            continue
        path = Path(stored_path).resolve()
        if path.is_relative_to(documents_dir) and path.suffix in (".pdf", ".html"):
            files.add(path.with_suffix(".pdf"))
            files.add(path.with_suffix(".html"))
    return files
