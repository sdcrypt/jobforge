"""Jobs endpoints — list, filter, dismiss, clear, research."""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete, func, or_
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit
import uuid
from core.database import get_db
from models.job import Job
from models.profile import UserProfile
from core.runs import enqueue_run, run_response

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class ManualJob(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    company: str = Field(min_length=1, max_length=255)
    url: str | None = Field(default=None, max_length=1024)
    description: str | None = Field(default=None, max_length=50000)
    location: str | None = Field(default=None, max_length=255)
    remote: bool = False
    salary_range: str | None = Field(default=None, max_length=255)
    salary_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    salary_max: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    salary_currency: str | None = None
    salary_period: Literal["year", "month", "hour"] | None = None
    posted_at: datetime | None = None

    @field_validator("title", "company", "url", "description", "location", "salary_range", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        if not value:
            return None
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            raise ValueError("Use an http(s) listing URL without credentials.")
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))

    @field_validator("salary_currency")
    @classmethod
    def validate_currency(cls, value):
        if value is None:
            return None
        value = value.strip().upper()
        if len(value) != 3 or not value.isascii() or not value.isalpha():
            raise ValueError("Use a three-letter currency code such as USD or INR.")
        return value

    @field_validator("posted_at")
    @classmethod
    def normalize_date(cls, value):
        if value is not None and value.tzinfo:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @model_validator(mode="after")
    def validate_details(self):
        if not self.url and not (self.description or "").strip():
            raise ValueError("Provide a listing URL or pasted job description.")
        if self.salary_min is not None and self.salary_max is not None and self.salary_min > self.salary_max:
            raise ValueError("Minimum salary cannot exceed maximum salary.")
        if (self.salary_min is not None or self.salary_max is not None) and not (self.salary_currency and self.salary_period):
            raise ValueError("Salary amounts require a currency and pay period.")
        return self


@router.post("/import", status_code=201)
async def import_job(data: ManualJob, db: AsyncSession = Depends(get_db)):
    """Save a manually entered job and assess sponsorship in the pasted text.

    Keep the URL as a reference without fetching it. Reject duplicate URLs,
    and leave application tracking to the separate Save job / Mark applied actions.
    """
    if data.url:
        existing = (await db.execute(select(Job).where(Job.url == data.url))).scalar_one_or_none()
        if existing:
            raise HTTPException(409, {"message": "This listing already exists.", "job_id": existing.id})
    values = data.model_dump()
    values["url"] = data.url or f"manual:{uuid.uuid4()}"
    if not data.salary_range and (data.salary_min is not None or data.salary_max is not None):
        values["salary_range"] = f"{data.salary_currency} {data.salary_min if data.salary_min is not None else '?'}–{data.salary_max if data.salary_max is not None else '?'} / {data.salary_period}"
    job = Job(**values, portal="manual", status="new", description_source="manual")
    from core.sponsorship import update_sponsorship
    update_sponsorship(job)
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "This listing already exists.")
    return job


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
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    keyword: str | None = None,
    company: str | None = None,
    location: str | None = None,
    remote: bool | None = None,
    salary_min: float | None = Query(default=None, ge=0, allow_inf_nan=False),
    salary_max: float | None = Query(default=None, ge=0, allow_inf_nan=False),
    salary_currency: str | None = Query(default=None, pattern="^[A-Z]{3}$"),
    salary_period: Literal["year", "month", "hour"] = "year",
    has_salary: bool = False,
    posted_within_days: int | None = Query(default=None, ge=1, le=365),
    sort: Literal["fit", "newest", "posted", "salary", "company"] = "fit",
    application_status: str | None = None,
    sponsorship_status: Literal["mentioned", "conditional", "not_available", "not_specified", "not_assessed"] | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List jobs with optional filters, sorted by fit_score descending."""
    q = select(Job)
    if sponsorship_status == "not_assessed":
        q = q.where(Job.sponsorship_checked_at == None)
    elif sponsorship_status:
        # A default category without a check date is still an unassessed job.
        q = q.where(Job.sponsorship_checked_at != None, Job.sponsorship_status == sponsorship_status)
    if status != "dismissed":
        q = q.where(Job.status != "dismissed")
    if keyword and keyword.strip():
        term = keyword.strip()
        q = q.where(or_(Job.title.icontains(term, autoescape=True), Job.company.icontains(term, autoescape=True), Job.description.icontains(term, autoescape=True)))
    if company and company.strip():
        q = q.where(Job.company.icontains(company.strip(), autoescape=True))
    if location and location.strip():
        q = q.where(Job.location.icontains(location.strip(), autoescape=True))
    if remote is not None:
        q = q.where(Job.remote == remote)
    if posted_within_days:
        q = q.where(Job.posted_at >= datetime.utcnow() - timedelta(days=posted_within_days))
    if has_salary:
        q = q.where(or_(Job.salary_range != None, Job.salary_min != None, Job.salary_max != None))
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        raise HTTPException(422, "Minimum salary cannot exceed maximum salary.")
    if salary_min is not None or salary_max is not None or sort == "salary":
        if not salary_currency:
            raise HTTPException(422, "Choose a currency for salary filtering or sorting.")
        q = q.where(Job.salary_currency == salary_currency, Job.salary_period == salary_period)
        q = q.where(or_(Job.salary_min != None, Job.salary_max != None))
        if salary_min is not None:
            q = q.where(or_(Job.salary_max == None, Job.salary_max >= salary_min))
        if salary_max is not None:
            q = q.where(or_(Job.salary_min == None, Job.salary_min <= salary_max))
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

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    order = {"fit": Job.fit_score.desc().nulls_last(), "newest": Job.found_at.desc(),
             "posted": Job.posted_at.desc().nulls_last(), "salary": func.coalesce(Job.salary_max, Job.salary_min).desc().nulls_last(),
             "company": func.lower(Job.company).asc()}[sort]
    q = q.order_by(order, Job.found_at.desc(), Job.id).limit(limit).offset(offset)
    result = await db.execute(q)
    jobs = result.scalars().all()
    return {"jobs": jobs, "count": len(jobs), "total": total, "limit": limit, "offset": offset,
            "has_more": offset + len(jobs) < total}


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
        select(SearchConfig).where(SearchConfig.active == True).order_by(SearchConfig.last_run_at.desc().nulls_last()).limit(1)
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
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.patch("/{job_id}/dismiss")
async def dismiss_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Mark a job as dismissed — hides it from the default list."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = "dismissed"
    await db.commit()
    return {"message": "Job dismissed."}


@router.post("/{job_id}/research", status_code=202)
async def research_job(job_id: int, db: AsyncSession = Depends(get_db)):
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
