"""
JobForge — Celery Tasks
"""

import asyncio
from workers.celery_app import celery_app
import structlog

log = structlog.get_logger()


@celery_app.task(name="workers.tasks.run_search_pipeline", bind=True, max_retries=2)
def run_search_pipeline(self):
    """
    Scheduled task: runs full Search → Store → Rank pipeline.
    Triggered every 12 hours by Celery Beat.
    Can also be triggered manually: run_search_pipeline.delay()
    """
    try:
        asyncio.run(_async_pipeline())
    except Exception as exc:
        log.error("task.pipeline_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60)


async def _async_pipeline():
    from core.database import AsyncSessionLocal
    from agents.pipeline import run_pipeline
    async with AsyncSessionLocal() as db:
        result = await run_pipeline(db)
        log.info("task.pipeline_complete", **result)
