import asyncio
import traceback
import uuid
from hashlib import sha256
from contextvars import ContextVar
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from core import database
from models.application import Application
from models.run import TaskRun

ACTIVE_STATUSES = ("queued", "running", "retrying")
TERMINAL_STATUSES = ("succeeded", "partial", "failed")
LEASE_SECONDS = 180
current_run: ContextVar[tuple[str, str] | None] = ContextVar("current_run", default=None)


class RunLost(RuntimeError):
    pass


def active_key(kind: str, job_id: str | None = None) -> str:
    if kind in ("pipeline", "search", "rank"):
        return "discovery"
    return f"{kind}:{job_id or 'profile'}"


def serialize_run(run: TaskRun, detail: bool = False) -> dict:
    excluded = {"payload", "execution_token", "active_key", "traceback"}
    result = {column.name: getattr(run, column.name) for column in TaskRun.__table__.columns if column.name not in excluded}
    if detail:
        result["traceback"] = run.traceback
    result["label"] = (run.payload or {}).get("_label") or run.kind.replace("_", " ")
    return result


def run_response(run: TaskRun, created: bool) -> dict:
    return {"run_id": run.id, "run": serialize_run(run), "duplicate": not created,
            "message": f"{run.kind.capitalize()} queued. Follow progress in Runs." if created
            else "Equivalent work is already queued or running. Follow its progress in Runs."}


async def enqueue_run(db, kind: str, payload: dict | None = None, job_id: str | None = None,
                      config_id: str | None = None, trigger: str = "manual",
                      retry_of: str | None = None, parent_id: str | None = None,
                      dispatch: bool = True, max_attempts: int = 3) -> tuple[TaskRun, bool]:
    key = active_key(kind, job_id)
    payload = dict(payload or {})
    if kind == "resume_parse":
        key = f"resume_parse:{sha256((payload or {}).get('content', '').encode()).hexdigest()}"
    if job_id:
        from models.job import Job
        job = (await db.execute(select(Job).where(Job.id == job_id).with_for_update())).scalar_one_or_none()
        if not job:
            raise HTTPException(404, "The job associated with this work no longer exists.")
        payload["_label"] = f"{job.title} at {job.company}"
    existing = (await db.execute(select(TaskRun).where(TaskRun.active_key == key))).scalar_one_or_none()
    if existing:
        return existing, False
    try:
        async with db.begin_nested():
            run = TaskRun(kind=kind, payload=payload or {}, job_id=job_id, config_id=config_id,
                          active_key=key, trigger=trigger, retry_of=retry_of,
                          parent_id=parent_id, max_attempts=max_attempts)
            db.add(run)
            await db.flush()
    except IntegrityError:
        existing = (await db.execute(select(TaskRun).where(TaskRun.active_key == key))).scalar_one()
        return existing, False
    await db.commit()
    if dispatch:
        await dispatch_run(run.id)
        await db.refresh(run)
    return run, True


async def dispatch_run(run_id: str) -> None:
    from workers.celery_app import celery_app
    try:
        await asyncio.to_thread(celery_app.send_task, "workers.tasks.execute_run", args=[run_id], task_id=run_id)
        values = {"dispatched_at": datetime.utcnow(), "dispatch_error": None}
    except Exception as exc:
        values = {"dispatch_error": f"Queue unavailable; dispatch will be retried: {str(exc)[:1000]}"}
    async with database.AsyncSessionLocal() as db:
        await db.execute(update(TaskRun).where(
            TaskRun.id == run_id, TaskRun.status.in_(("queued", "retrying"))
        ).values(**values))
        await db.commit()


async def commit_owned(db) -> None:
    context = current_run.get()
    if context:
        run = (await db.execute(select(TaskRun).where(TaskRun.id == context[0]).with_for_update())).scalar_one()
        if run.status != "running" or run.execution_token != context[1]:
            await db.rollback()
            raise RunLost("This worker no longer owns the run.")
    await db.commit()


async def stage(name: str, message: str, completed: int = 0, total: int = 0, done: bool = False,
                result: dict | None = None) -> None:
    context = current_run.get()
    if not context:
        return
    async with database.AsyncSessionLocal() as db:
        run = (await db.execute(select(TaskRun).where(TaskRun.id == context[0]).with_for_update())).scalar_one()
        if run.status != "running" or run.execution_token != context[1]:
            raise RunLost("This worker no longer owns the run.")
        entries = list(run.stages or [])
        if not entries or entries[-1]["name"] != name or entries[-1]["attempt"] != run.attempts:
            entries.append({"name": name, "attempt": run.attempts, "started_at": datetime.utcnow().isoformat(), "status": "running"})
        completed = max(completed, entries[-1].get("completed", 0))
        total = max(total, completed)
        entries[-1] = {**entries[-1], "message": message, "completed": completed, "total": total,
                       "status": "succeeded" if done else "running"}
        if done:
            entries[-1]["finished_at"] = datetime.utcnow().isoformat()
        run.stage = name
        run.stages = entries
        if result:
            run.result = {**(run.result or {}), **result}
        await db.commit()
    from core.websocket import ws_manager
    await ws_manager.emit_agent_event("pipeline", "done" if done else "thinking", message, {"stage": name, "completed": completed, "total": total})


async def heartbeat(run_id: str, token: str) -> None:
    while True:
        await asyncio.sleep(15)
        async with database.AsyncSessionLocal() as db:
            result = await db.execute(update(TaskRun).where(
                TaskRun.id == run_id, TaskRun.execution_token == token, TaskRun.status == "running"
            ).values(lease_expires_at=datetime.utcnow() + timedelta(seconds=LEASE_SECONDS)))
            await db.commit()
            if not result.rowcount:
                return


async def _finish(run_id: str, token: str, result: dict | None = None, error: Exception | None = None) -> None:
    from models.application import AgentEvent
    async with database.AsyncSessionLocal() as db:
        run = (await db.execute(select(TaskRun).where(TaskRun.id == run_id).with_for_update())).scalar_one()
        if run.status != "running" or run.execution_token != token:
            return
        if error:
            run.error = str(error)[:10000]
            run.error_type = type(error).__name__
            run.traceback = "".join(traceback.format_exception(error))[-30000:]
            retryable = not isinstance(error, (ValueError, KeyError, HTTPException))
            run.status = "retrying" if retryable and run.attempts < run.max_attempts else "failed"
            run.next_retry_at = datetime.utcnow() + timedelta(seconds=30 * 2 ** (run.attempts - 1)) if run.status == "retrying" else None
            if run.stages and run.stages[-1]["status"] == "running":
                run.stages = [*run.stages[:-1], {**run.stages[-1], "status": "failed", "error": run.error, "finished_at": datetime.utcnow().isoformat()}]
        else:
            errors = (await db.execute(select(AgentEvent.id).where(
                AgentEvent.run_id == run_id, AgentEvent.status == "error", AgentEvent.created_at >= run.started_at
            ))).first()
            run.status = "partial" if errors else "succeeded"
            run.result = {**(run.result or {}), **(result or {})}
            run.error = None
            run.error_type = None
            run.traceback = None
            run.next_retry_at = None
            if run.kind == "resume_parse":
                run.payload = {}
        if run.status in TERMINAL_STATUSES:
            run.active_key = None
            run.finished_at = datetime.utcnow()
        run.execution_token = None
        run.lease_expires_at = None
        run.dispatched_at = None
        await db.commit()
    from core.websocket import ws_manager
    await ws_manager.emit_agent_event(run.kind, "error" if error else "done",
                                      f"Run {run.status}: {run.error or 'work completed'}", {"run_status": run.status})


async def execute_run(run_id: str) -> str:
    token = str(uuid.uuid4())
    now = datetime.utcnow()
    async with database.AsyncSessionLocal() as db:
        claimed = await db.execute(update(TaskRun).where(
            TaskRun.id == run_id, TaskRun.status.in_(("queued", "retrying")),
            or_(TaskRun.next_retry_at == None, TaskRun.next_retry_at <= now),
        ).values(status="running", execution_token=token,
                 lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
                 started_at=now, finished_at=None, attempts=TaskRun.attempts + 1, dispatch_error=None))
        await db.commit()
        if not claimed.rowcount:
            return "not_claimed"
        run = await db.get(TaskRun, run_id)
    context_token = current_run.set((run_id, token))
    pulse = asyncio.create_task(heartbeat(run_id, token))
    try:
        from workers.handlers import perform_run
        await stage("starting", f"Starting {run.kind}, attempt {run.attempts}/{run.max_attempts}")
        await stage("starting", "Worker ready", done=True)
        result = await perform_run(run)
        await _finish(run_id, token, result=result)
    except RunLost:
        return "ownership_lost"
    except Exception as exc:
        await _finish(run_id, token, error=exc)
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
        current_run.reset(context_token)
    async with database.AsyncSessionLocal() as db:
        return (await db.get(TaskRun, run_id)).status


async def recover_and_dispatch() -> None:
    now = datetime.utcnow()
    async with database.AsyncSessionLocal() as db:
        expired = (await db.execute(select(TaskRun).where(
            TaskRun.status == "running", TaskRun.lease_expires_at < now
        ).with_for_update(skip_locked=True))).scalars().all()
        for run in expired:
            run.error = "Worker heartbeat expired; the worker may have stopped."
            run.error_type = "WorkerInterrupted"
            run.status = "retrying" if run.attempts < run.max_attempts else "failed"
            run.next_retry_at = now if run.status == "retrying" else None
            run.execution_token = None
            run.lease_expires_at = None
            run.dispatched_at = None
            if run.stages and run.stages[-1]["status"] == "running":
                run.stages = [*run.stages[:-1], {**run.stages[-1], "status": "failed", "error": run.error, "finished_at": now.isoformat()}]
            if run.status == "failed":
                run.active_key = None
                run.finished_at = now
                if run.kind == "docgen":
                    await db.execute(update(Application).where(Application.job_id == run.job_id).values(document_status="failed", document_error=run.error))
        await db.commit()
        waiting = (await db.execute(select(TaskRun.id).where(
            TaskRun.status.in_(("queued", "retrying")),
            or_(TaskRun.next_retry_at == None, TaskRun.next_retry_at <= now),
            or_(TaskRun.dispatched_at == None, TaskRun.dispatched_at < now - timedelta(seconds=60)),
            TaskRun.created_at < now - timedelta(seconds=60),
        ))).scalars().all()
    for run_id in waiting:
        await dispatch_run(run_id)
