"""
JobForge — Pipeline
Chains Search → Store → Rank in one call.
Used by the API route and the Celery scheduled task.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from models.job import Job
from models.profile import UserProfile
from models.search_config import SearchConfig
from agents.search import SearchAgent
from agents.rank import RankAgent
from core.websocket import ws_manager

log = structlog.get_logger()


async def run_pipeline(db: AsyncSession) -> dict:
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

    if not config:
        await ws_manager.emit_agent_event(
            "pipeline", "error",
            "No active SearchConfig found. Create one at POST /api/search-config"
        )
        return {"error": "No search config found"}

    profile_r = await db.execute(select(UserProfile).limit(1))
    profile = profile_r.scalar_one_or_none()

    if not profile:
        await ws_manager.emit_agent_event(
            "pipeline", "error",
            "No profile found. Create one at POST /api/profile"
        )
        return {"error": "No profile found"}

    # ── Step 1: Search ────────────────────────────────────────────────────
    search_agent = SearchAgent(db=db)
    raw_jobs = await search_agent.run(
        keywords=config.keywords,
        locations=config.locations,
        portals=config.portals,
        remote_only=config.remote_only,
        posted_within_days=config.posted_within_days,
    )

    # ── Step 2: Store (deduplicate) ───────────────────────────────────────
    new_count = 0
    for j in raw_jobs:
        existing = await db.execute(select(Job).where(Job.url == j["url"]))
        if existing.scalar_one_or_none():
            continue
        db.add(Job(**{k: v for k, v in j.items() if hasattr(Job, k)}))
        new_count += 1

    await db.flush()

    await ws_manager.emit_agent_event(
        "pipeline", "thinking",
        f"Stored {new_count} new jobs. Starting ranking...",
        {"new_jobs": new_count},
    )

    # ── Step 3: Rank all unranked jobs ────────────────────────────────────
    unranked_r = await db.execute(
        select(Job).where(Job.fit_score == None).limit(50)
    )
    unranked = unranked_r.scalars().all()

    ranked_count = 0
    if unranked:
        rank_agent = RankAgent(db=db)
        scores = await rank_agent.run(jobs=unranked, profile=profile)

        for score in scores:
            job_r = await db.execute(select(Job).where(Job.id == score["job_id"]))
            job = job_r.scalar_one_or_none()
            if job:
                job.fit_score     = score.get("overall")
                job.tech_score    = score.get("tech_score")
                job.exp_score     = score.get("exp_score")
                job.location_score = score.get("location_score")
                job.growth_score  = score.get("growth_score")
                job.strengths     = score.get("strengths", [])
                job.gaps          = score.get("gaps", [])
                job.status        = "ranked"
                ranked_count += 1

    # ── Update config last_run ────────────────────────────────────────────
    config.last_run_at = __import__("datetime").datetime.utcnow()
    config.last_run_found = new_count

    await db.commit()

    summary = {
        "new_jobs_found": new_count,
        "jobs_ranked": ranked_count,
        "portals_searched": config.portals,
        "keywords": config.keywords,
    }

    await ws_manager.emit_agent_event(
        "pipeline", "done",
        f"Pipeline complete — {new_count} new jobs, {ranked_count} ranked.",
        summary,
    )

    return summary
