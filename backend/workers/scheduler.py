from datetime import datetime, timedelta

from sqlalchemy import select

from core import database
from core.runs import enqueue_run, recover_and_dispatch
from models.profile import UserProfile
from models.run import TaskRun
from models.search_config import SearchConfig

SEARCH_FIELDS = ("name", "keywords", "locations", "portals", "remote_only", "posted_within_days",
                 "max_results_per_search", "linkedin_pages", "auto_research_top_n")


def snapshot(config: SearchConfig) -> dict:
    return {**{field: getattr(config, field) for field in SEARCH_FIELDS}, "_label": config.name}


async def tick():
    await recover_and_dispatch()
    async with database.AsyncSessionLocal() as db:
        profile = (await db.execute(select(UserProfile.id).limit(1))).first()
        if not profile:
            return
        configs = (await db.execute(select(SearchConfig).where(
            SearchConfig.active == True, SearchConfig.run_every_hours > 0
        ))).scalars().all()
        due = []
        for config in configs:
            latest = (await db.execute(select(TaskRun.created_at).where(
                TaskRun.kind == "pipeline", TaskRun.config_id == config.id
            ).order_by(TaskRun.created_at.desc()).limit(1))).scalar_one_or_none()
            baseline = latest or config.last_run_at or config.created_at
            if baseline + timedelta(hours=config.run_every_hours) <= datetime.utcnow():
                due.append((baseline + timedelta(hours=config.run_every_hours), config))
        for due_at, config in sorted(due, key=lambda entry: entry[0]):
            run, created = await enqueue_run(db, "pipeline", snapshot(config), config_id=config.id, trigger="scheduled")
            if created:
                break
