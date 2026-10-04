"""Jobs endpoints — list, filter, dismiss, clear, research."""

from fastapi import APIRouter, Depends, BackgroundTasks, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete
from core.database import get_db
from models.job import Job
from models.profile import UserProfile
from agents.search import SearchAgent
from agents.rank import RankAgent

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/search")
async def trigger_search(
    query: str,
    location: str = "remote",
    portal: str = "linkedin",
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger the Search Agent to find new jobs.
    Runs in background — watch WebSocket /ws for live events.
    """
    background_tasks.add_task(_run_search, query, location, portal)
    return {"message": f"Search started for '{query}' on {portal}. Watch /ws for updates."}


async def _run_search(query: str, location: str, portal: str):
    """Background task: search + deduplicate + store jobs."""
    from core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        agent = SearchAgent(db=db)
        raw_jobs = await agent.run(query=query, location=location, portal=portal)

        new_count = 0
        for j in raw_jobs:
            # Deduplicate by URL
            existing = await db.execute(select(Job).where(Job.url == j["url"]))
            if existing.scalar_one_or_none():
                continue
            db.add(Job(**j))
            new_count += 1

        await db.commit()


@router.post("/rank")
async def trigger_rank(
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger the Rank Agent to score all unranked jobs.
    Runs in background — watch WebSocket /ws for live events.
    """
    background_tasks.add_task(_run_rank)
    return {"message": "Ranking started. Watch /ws for updates."}


async def _run_rank():
    """Background task: rank all unranked jobs."""
    from core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        # Get unranked jobs
        jobs_result = await db.execute(
            select(Job).where(Job.fit_score == None).limit(50)
        )
        jobs = jobs_result.scalars().all()
        if not jobs:
            return

        # Get profile
        profile_result = await db.execute(select(UserProfile).limit(1))
        profile = profile_result.scalar_one_or_none()
        if not profile:
            return

        agent = RankAgent(db=db)
        scores = await agent.run(jobs=jobs, profile=profile)

        # Write scores back to DB
        for score in scores:
            job_result = await db.execute(
                select(Job).where(Job.id == score["job_id"])
            )
            job = job_result.scalar_one_or_none()
            if job:
                job.fit_score = score.get("overall")
                job.tech_score = score.get("tech_score")
                job.exp_score = score.get("exp_score")
                job.location_score = score.get("location_score")
                job.growth_score = score.get("growth_score")
                job.strengths = score.get("strengths")
                job.gaps = score.get("gaps")
                job.status = "ranked"

        await db.commit()


@router.get("")
async def list_jobs(
    status: str | None = None,
    min_score: float = Query(default=0, ge=0, le=100),
    portal: str | None = None,
    limit: int = Query(default=20, le=100),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List jobs with optional filters, sorted by fit_score descending."""
    q = select(Job)
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


@router.post("/{job_id}/research")
async def research_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Run the Research Agent on a single job.
    Fetches the full description, scores fit against the user's profile,
    and persists the analysis (fit_score, strengths, gaps, talking_points …)
    back to the Job record.

    This call is synchronous — it waits for the LLM and returns the result.
    Watch ws://localhost:8000/ws for live progress events.
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

    profile_dict = {
        "full_name":         profile.full_name,
        "headline":          profile.headline,
        "summary":           profile.summary,
        "skills":            profile.skills or [],
        "experience":        profile.experience or [],
        "education":         profile.education or [],
        "target_roles":      profile.target_roles or [],
        "remote_preference": profile.remote_preference,
    }

    from agents.research import ResearchAgent
    agent = ResearchAgent(db=db, job_id=job_id)
    analysis = await agent.run(job_id=job_id, profile=profile_dict)

    return {"message": "Research complete", "job_id": job_id, **analysis}


@router.delete("/clear")
async def clear_jobs(
    portal: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete jobs from DB.
    - portal=None  → delete ALL jobs (full reset)
    - portal=linkedin → delete only LinkedIn jobs
    Dismissed / applied jobs are also removed — use with care.
    """
    q = delete(Job)
    if portal:
        q = q.where(Job.portal == portal)
    result = await db.execute(q)
    await db.commit()
    return {"message": f"Deleted {result.rowcount} job(s).", "deleted": result.rowcount}
