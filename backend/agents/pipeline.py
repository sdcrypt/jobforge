"""
JobForge — Pipeline
Chains Search → Store → Rank → (optional) Auto-Research in one background run.
Used by the API route and the Celery scheduled task.
"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, delete, desc, func, or_, select
import structlog

from models.application import Application
from models.job import Job
from models.profile import UserProfile
from models.search_config import SearchConfig
from agents.search import SearchAgent
from core.websocket import ws_manager
from core.runs import commit_owned, stage
from models.run import TaskRun
from core.runs import ACTIVE_STATUSES

log = structlog.get_logger()


async def run_pipeline(db: AsyncSession, config_data: dict | None = None, config_id: str | None = None) -> dict:
    """
    Full pipeline:
      1. Load SearchConfig + UserProfile from DB
      2. Search all portals
      3. Store new jobs (skip duplicates)
      4. Rank all unranked jobs
      5. Return summary

    Called by:
      - POST /api/pipeline/run  (manual trigger)
      - Celery task             (scheduled)
    """

    # ── Load config ───────────────────────────────────────────────────────
    config_r = await db.execute(
        select(SearchConfig).where(SearchConfig.active == True).limit(1)
    )
    config = config_r.scalar_one_or_none()
    if config_data is not None:
        config = SimpleNamespace(**config_data)

    if not config:
        await ws_manager.emit_agent_event(
            "pipeline", "error",
            "No active SearchConfig found. Create one at POST /api/search-config"
        )
        raise ValueError("No active search configuration found.")

    profile_r = await db.execute(select(UserProfile).limit(1))
    profile = profile_r.scalar_one_or_none()

    if not profile:
        await ws_manager.emit_agent_event(
            "pipeline", "error",
            "No profile found. Create one at POST /api/profile"
        )
        raise ValueError("No profile found.")

    # Remove stale local rows before adding fresh results. Search agents already
    # request recent postings, but old rows can remain from earlier runs.
    await stage("cleanup", "Removing stale untracked jobs")
    cleaned_count = await _cleanup_stale_jobs(db, config.posted_within_days)
    await commit_owned(db)
    await stage("cleanup", f"Removed {cleaned_count} stale jobs", cleaned_count, cleaned_count, done=True,
                result={"old_jobs_removed": cleaned_count})

    # ── Step 1: Search ────────────────────────────────────────────────────
    search_agent = SearchAgent(db=db)
    await stage("search", "Searching configured portals")
    raw_jobs = await search_agent.run(
        keywords=config.keywords,
        locations=config.locations,
        portals=config.portals,
        remote_only=config.remote_only,
        posted_within_days=config.posted_within_days,
        max_results=getattr(config, "max_results_per_search", 15),
        linkedin_pages=getattr(config, "linkedin_pages", 1),
    )

    await stage("search", f"Found {len(raw_jobs)} results", len(raw_jobs), len(raw_jobs), done=True)
    await stage("store", "Saving new jobs and skipping duplicates")
    new_count = await store_jobs(db, raw_jobs)
    await commit_owned(db)
    await stage("store", f"Saved {new_count} new jobs", new_count, new_count, done=True,
                result={"new_jobs_found": new_count})

    from workers.handlers import rank_pending
    ranked_count = await rank_pending(db, profile)
    stored_config = await db.get(SearchConfig, config_id) if config_id else None
    if stored_config:
        stored_config.last_run_at = datetime.utcnow()
        stored_config.last_run_found = new_count
    elif isinstance(config, SearchConfig):
        config.last_run_at = datetime.utcnow()
        config.last_run_found = new_count
    await commit_owned(db)
    summary = {"new_jobs_found": new_count, "jobs_ranked": ranked_count,
               "old_jobs_removed": cleaned_count, "portals_searched": config.portals,
               "keywords": config.keywords}
    auto_n = getattr(config, "auto_research_top_n", 5)
    await stage("research", f"Researching up to {auto_n} top matches")
    summary["jobs_researched"] = await _auto_research(profile, auto_n) if auto_n > 0 else 0
    await stage("research", f"Research complete: {summary['jobs_researched']} jobs",
                summary["jobs_researched"], summary["jobs_researched"], done=True, result=summary)
    return summary


async def store_jobs(db: AsyncSession, raw_jobs: list[dict]) -> int:
    # Primary dedup: exact URL match (DB unique constraint)
    # Secondary dedup: same company + same title (catches URL variants / LinkedIn
    #   returning the same job for different keyword/location combos)
    new_count = 0
    for j in raw_jobs:
        url = j.get("url", "")
        if not url:
            continue

        # Primary: URL
        existing_url = await db.execute(select(Job).where(Job.url == url))
        if existing_url.scalar_one_or_none():
            continue

        # Secondary: same company + title (case-insensitive)
        company = (j.get("company") or "").strip()
        title = (j.get("title") or "").strip()
        if company and title:
            existing_pair = await db.execute(
                select(Job).where(
                    func.lower(Job.company) == company.lower(),
                    func.lower(Job.title) == title.lower(),
                )
            )
            if existing_pair.scalar_one_or_none():
                continue

        db.add(Job(**{k: v for k, v in j.items() if hasattr(Job, k)}))
        new_count += 1

    await db.flush()

    return new_count


async def _cleanup_stale_jobs(db: AsyncSession, posted_within_days: int) -> int:
    """
    Delete jobs that are older than the active search window.

    Uses posted_at when a portal provides it. For feeds/APIs that do not expose a
    reliable posting date, found_at is used as a fallback so stale local rows do
    not stay forever.
    """
    days = max(1, posted_within_days or 7)
    cutoff = datetime.utcnow() - timedelta(days=days)

    protected_job_statuses = {
        "saved",
        "applying",
        "applied",
        "interviewing",
        "offered",
        "rejected",
    }
    protected_application_job_ids = select(Application.job_id)
    protected_run_job_ids = select(TaskRun.job_id).where(
        TaskRun.job_id != None, TaskRun.status.in_(ACTIVE_STATUSES)
    )

    stale_job_ids = select(Job.id).where(
        or_(
            Job.posted_at < cutoff,
            and_(Job.posted_at == None, Job.found_at < cutoff),  # noqa: E711
        ),
        Job.status.notin_(protected_job_statuses),
        Job.id.notin_(protected_application_job_ids),
        Job.id.notin_(protected_run_job_ids),
    )

    stale_ids = [row[0] for row in (await db.execute(stale_job_ids)).all()]
    if not stale_ids:
        return 0

    result = await db.execute(delete(Job).where(Job.id.in_(stale_ids)))
    await db.flush()

    removed = result.rowcount or 0
    return removed


async def _auto_research(profile, top_n: int) -> int:
    """
    Background step: research the top N unresearched jobs by fit_score.
    Runs 2 jobs concurrently to keep Ollama load manageable.
    Uses fresh DB sessions per job to avoid long-held transactions.
    """
    from core.database import AsyncSessionLocal
    from core.runs import current_run, enqueue_run, execute_run

    # Find top N jobs that haven't been researched yet, ordered by fit_score
    async with AsyncSessionLocal() as db:
        context = current_run.get()
        parent = await db.get(TaskRun, context[0]) if context else None
        targets = (parent.result or {}).get("research_job_ids") if parent else None
        query = select(Job).where(Job.status != "dismissed", Job.fit_score != None).order_by(desc(Job.fit_score))
        if targets is None:
            query = query.where(Job.researched_at == None).limit(top_n)
        else:
            query = query.where(Job.id.in_(targets))
        result = await db.execute(query)
        jobs_to_research = result.scalars().all()
        target_ids = targets if targets is not None else [job.id for job in jobs_to_research]
        job_ids = [job.id for job in jobs_to_research if job.researched_at is None]
        already_completed = len(jobs_to_research) - len(job_ids)
        total = len(jobs_to_research)

    await stage("research", f"Researching {total} selected matches", already_completed, total,
                result={"research_job_ids": target_ids, "jobs_researched": already_completed})

    if not job_ids:
        return already_completed

    await ws_manager.emit_agent_event(
        "research", "started",
        f"Auto-researching top {len(job_ids)} jobs in the background…",
        {"total": len(job_ids)},
    )

    sem = asyncio.Semaphore(2)   # 2 concurrent — keeps Ollama comfortable
    completed = already_completed
    failed = []

    async def research_one(job_id: str) -> None:
        nonlocal completed
        async with sem:
            try:
                async with AsyncSessionLocal() as research_db:
                    context = current_run.get()
                    child, _created = await enqueue_run(
                        research_db, "research", job_id=job_id, dispatch=False,
                        parent_id=context[0] if context else None, trigger="pipeline", max_attempts=1,
                    )
                outcome = await execute_run(child.id)
                if outcome not in ("succeeded", "partial"):
                    raise RuntimeError(f"Research run {child.id} {outcome}")
                completed += 1
                await stage("research", f"Researched {completed}/{total} jobs", completed, total,
                            result={"jobs_researched": completed})
                await ws_manager.emit_agent_event(
                    "research", "thinking",
                    f"Researched {completed}/{total} jobs…",
                    {"completed": completed, "total": total},
                )
            except Exception as e:
                log.warning("pipeline.auto_research_failed", job_id=job_id, error=str(e))
                failed.append(str(e))

    await asyncio.gather(*[research_one(jid) for jid in job_ids], return_exceptions=True)

    await ws_manager.emit_agent_event(
        "research", "done",
        f"Auto-research complete — {completed}/{total} jobs analysed.",
        {"completed": completed, "total": total},
    )
    if failed:
        raise RuntimeError(f"{len(failed)} job research tasks failed: {failed[0]}")
    return completed
