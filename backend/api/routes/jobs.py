"""Jobs endpoints — list, filter, dismiss, clear, research."""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete
from core.database import get_db
from models.job import Job
from models.profile import UserProfile
from core.runs import enqueue_run, run_response

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/search", status_code=202)
async def trigger_search(
    query: str,
    location: str = "remote",
    portal: str = "linkedin",
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger the Search Agent to find new jobs.
    Runs in background — watch WebSocket /ws for live events.
    """
    from api.routes.search_config import SUPPORTED_PORTALS
    if portal not in SUPPORTED_PORTALS or not query.strip():
        raise HTTPException(422, "Provide a keyword and supported job portal.")
    run, created = await enqueue_run(db, "search", {"keywords": [query], "locations": [location], "portals": [portal]})
    return run_response(run, created)


@router.post("/rank", status_code=202)
async def trigger_rank(
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger the Rank Agent to score all unranked jobs.
    Runs in background — watch WebSocket /ws for live events.
    """
    if not (await db.execute(select(UserProfile.id).limit(1))).first():
        raise HTTPException(400, "Create a profile before ranking jobs.")
    run, created = await enqueue_run(db, "rank")
    return run_response(run, created)


@router.get("")
async def list_jobs(
    status: str | None = None,
    min_score: float = Query(default=0, ge=0, le=100),
    portal: str | None = None,
    limit: int = Query(default=20, le=100),
    offset: int = 0,
    application_status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List jobs with optional filters, sorted by fit_score descending."""
    q = select(Job)
    if application_status:
        from models.application import Application
        q = q.where(Job.id.in_(select(Application.job_id).where(
            Application.status == application_status
        )))
    if status:
        q = q.where(Job.status == status)
    if portal:
        q = q.where(Job.portal == portal)
    if min_score > 0:
        q = q.where(Job.fit_score >= min_score)

    q = q.order_by(desc(Job.fit_score).nulls_last(), Job.found_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    jobs = result.scalars().all()
    return {"jobs": jobs, "count": len(jobs)}


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Aggregated stats for the dashboard — total, researched, fit buckets, top jobs."""
    from sqlalchemy import func
    from models.application import Application
    from models.search_config import SearchConfig

    # Counts
    total_r = await db.execute(
        select(func.count(Job.id)).where(Job.status != "dismissed")
    )
    total = total_r.scalar() or 0

    researched_r = await db.execute(
        select(func.count(Job.id)).where(
            Job.researched_at != None,  # noqa: E711
            Job.status != "dismissed",
        )
    )
    researched = researched_r.scalar() or 0

    high_fit_r = await db.execute(
        select(func.count(Job.id)).where(
            Job.fit_score >= 70, Job.status != "dismissed"
        )
    )
    high_fit = high_fit_r.scalar() or 0

    avg_r = await db.execute(
        select(func.avg(Job.fit_score)).where(
            Job.fit_score != None,  # noqa: E711
            Job.status != "dismissed",
        )
    )
    avg_score = avg_r.scalar()

    docs_r = await db.execute(
        select(func.count(Application.id)).where(Application.one_pager_path != None)  # noqa: E711
    )
    docs = docs_r.scalar() or 0

    # Portal breakdown
    portal_r = await db.execute(
        select(Job.portal, func.count(Job.id))
        .where(Job.status != "dismissed")
        .group_by(Job.portal)
    )
    by_portal = {row[0]: row[1] for row in portal_r.all()}

    # Score buckets
    scores_r = await db.execute(
        select(Job.fit_score).where(
            Job.fit_score != None,  # noqa: E711
            Job.status != "dismissed",
        )
    )
    buckets: dict[str, int] = {"85-100": 0, "70-84": 0, "50-69": 0, "30-49": 0, "0-29": 0}
    for (s,) in scores_r.all():
        if s >= 85:   buckets["85-100"] += 1
        elif s >= 70: buckets["70-84"] += 1
        elif s >= 50: buckets["50-69"] += 1
        elif s >= 30: buckets["30-49"] += 1
        else:         buckets["0-29"] += 1

    # Top 5 jobs
    top_r = await db.execute(
        select(Job)
        .where(Job.fit_score != None, Job.status != "dismissed")  # noqa: E711
        .order_by(desc(Job.fit_score))
        .limit(5)
    )
    top_jobs = [
        {
            "id": j.id,
            "title": j.title,
            "company": j.company,
            "fit_score": j.fit_score,
            "portal": j.portal,
            "location": j.location,
            "remote": j.remote,
            "researched_at": j.researched_at.isoformat() if j.researched_at else None,
            "url": j.url,
        }
        for j in top_r.scalars().all()
    ]

    # Last pipeline run
    config_r = await db.execute(
        select(SearchConfig).where(SearchConfig.active == True).limit(1)  # noqa: E712
    )
    config = config_r.scalar_one_or_none()
    last_pipeline = None
    if config and config.last_run_at:
        last_pipeline = {
            "run_at": config.last_run_at.isoformat(),
            "found": config.last_run_found or 0,
        }

    return {
        "total_jobs": total,
        "researched": researched,
        "high_fit": high_fit,
        "docs_generated": docs,
        "avg_fit_score": round(float(avg_score), 1) if avg_score else None,
        "by_portal": by_portal,
        "score_buckets": buckets,
        "top_jobs": top_jobs,
        "last_pipeline": last_pipeline,
    }


@router.get("/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.patch("/{job_id}/dismiss")
async def dismiss_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Mark a job as dismissed — hides it from the default list."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = "dismissed"
    await db.commit()
    return {"message": "Job dismissed."}


@router.post("/{job_id}/research", status_code=202)
async def research_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Run the Research Agent on a single job.
    Fetches the full description, scores fit against the user's profile,
    and persists the analysis (fit_score, strengths, gaps, talking_points …)
    back to the Job record.

    Queues a durable worker run and returns its ID immediately.
    Follow /api/runs/{run_id} for progress and results.
    """
    # Load job
    job_result = await db.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Load user profile (required for analysis)
    profile_result = await db.execute(select(UserProfile).limit(1))
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=400,
            detail="No profile found. Please fill in your profile before running research.",
        )

    run, created = await enqueue_run(db, "research", job_id=job_id)
    return run_response(run, created)


@router.delete("/clear")
async def clear_jobs(
    portal: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete untracked jobs, optionally restricted to one portal.
    Jobs with application records are always preserved.
    """
    from models.application import Application
    from models.run import TaskRun
    from core.runs import ACTIVE_STATUSES
    if (await db.execute(select(TaskRun.id).where(TaskRun.active_key == "discovery"))).first():
        raise HTTPException(409, "Wait for the active search/ranking pipeline to finish before clearing jobs.")
    q = delete(Job).where(Job.id.notin_(select(Application.job_id)))
    q = q.where(Job.id.notin_(select(TaskRun.job_id).where(
        TaskRun.job_id != None, TaskRun.status.in_(ACTIVE_STATUSES)
    )))
    if portal:
        q = q.where(Job.portal == portal)
    result = await db.execute(q)
    await db.commit()
    return {"message": f"Deleted {result.rowcount} job(s).", "deleted": result.rowcount}
