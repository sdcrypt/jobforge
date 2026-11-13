from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from pydantic import BaseModel, Field

from core.database import get_db
from core.runs import ACTIVE_STATUSES, cancel_run, enqueue_run, serialize_run
from models.application import AgentEvent, Application
from models.job import Job
from models.run import TaskRun

router = APIRouter(prefix="/api/runs", tags=["runs"])


class RetryOptions(BaseModel):
    max_attempts: int = Field(default=3, ge=1, le=5)


def serialize_event(event: AgentEvent) -> dict:
    return {"id": event.id, "run_id": event.run_id, "agent": event.agent,
            "status": event.status, "message": event.message, "extra": event.extra or {},
            "created_at": event.created_at.isoformat() + "Z"}


@router.get("/events")
async def events(run_id: int | None = None, limit: int = Query(50, ge=1, le=200), db=Depends(get_db)):
    query = select(AgentEvent)
    if run_id:
        query = query.where(AgentEvent.run_id == run_id)
    records = (await db.execute(query.order_by(AgentEvent.created_at.desc()).limit(limit))).scalars().all()
    return {"events": [serialize_event(event) for event in records]}


@router.get("")
async def list_runs(kind: str | None = None, status: str | None = None,
                    limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0), db=Depends(get_db)):
    filters = []
    if kind:
        filters.append(TaskRun.kind.in_(("pipeline", "search", "rank")) if kind == "discovery" else TaskRun.kind == kind)
    if status:
        filters.append(TaskRun.status.in_(ACTIVE_STATUSES) if status == "active" else TaskRun.status == status)
    records = (await db.execute(select(TaskRun).where(*filters).order_by(TaskRun.created_at.desc()).limit(limit).offset(offset))).scalars().all()
    total = (await db.execute(select(func.count(TaskRun.id)).where(*filters))).scalar_one()
    return {"runs": [serialize_run(run) for run in records], "count": total}


@router.get("/{run_id}")
async def get_run(run_id: int, db=Depends(get_db)):
    run = await db.get(TaskRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    children = (await db.execute(select(TaskRun).where(TaskRun.parent_id == run.id).order_by(TaskRun.created_at))).scalars().all()
    return {**serialize_run(run, detail=True), "children": [serialize_run(child) for child in children]}


@router.post("/{run_id}/stop")
async def stop_run(run_id: int, db=Depends(get_db)):
    """Permanently stop queued, running, or retrying work without deleting results."""
    return serialize_run(await cancel_run(db, run_id))


@router.post("/{run_id}/retry", status_code=202)
async def retry_run(run_id: int, options: RetryOptions = RetryOptions(), db=Depends(get_db)):
    previous = await db.get(TaskRun, run_id)
    if not previous:
        raise HTTPException(404, "Run not found")
    if previous.status not in ("failed", "partial"):
        raise HTTPException(409, "Only failed or partially completed runs can be retried.")
    if previous.job_id:
        job = (await db.execute(select(Job.id).where(Job.id == previous.job_id).with_for_update())).first()
        if not job:
            raise HTTPException(404, "The job associated with this run has been deleted.")
    if previous.kind == "docgen":
        application = (await db.execute(select(Application).where(Application.job_id == previous.job_id).with_for_update())).scalar_one_or_none()
        if not application:
            raise HTTPException(404, "Application not found")
        application.document_status = "generating"
        application.document_error = None
    run, created = await enqueue_run(db, previous.kind, previous.payload, previous.job_id,
                                    previous.config_id, retry_of=previous.id,
                                    max_attempts=1 if previous.kind == "apply" else options.max_attempts)
    await db.commit()
    return {"run_id": run.id, "run": serialize_run(run), "duplicate": not created,
            "message": "Retry queued." if created else "Equivalent work is already queued or running."}
