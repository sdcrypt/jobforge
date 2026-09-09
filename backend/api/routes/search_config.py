"""
SearchConfig CRUD + pipeline trigger endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from core.database import get_db
from models.search_config import SearchConfig

router = APIRouter(prefix="/api/search-config", tags=["search-config"])


class SearchConfigCreate(BaseModel):
    keywords: list[str]
    locations: list[str] = ["remote"]
    portals: list[str] = ["linkedin", "indeed"]
    remote_only: bool = False
    posted_within_days: int = 7
    active: bool = True
    run_every_hours: int = 12


@router.post("", status_code=201)
async def create_search_config(
    data: SearchConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a search configuration. Replaces any existing one."""
    # Deactivate old configs
    old_r = await db.execute(select(SearchConfig))
    for old in old_r.scalars().all():
        old.active = False

    config = SearchConfig(**data.model_dump())
    db.add(config)
    await db.flush()
    return {"id": config.id, "message": "Search config saved."}


@router.get("")
async def get_search_config(db: AsyncSession = Depends(get_db)):
    """Get the active search configuration."""
    result = await db.execute(
        select(SearchConfig).where(SearchConfig.active == True).limit(1)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(404, "No active search config. Create one first.")
    return config


# ── Pipeline trigger ──────────────────────────────────────────────────────────

pipeline_router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@pipeline_router.post("/run")
async def run_pipeline(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually trigger the full Search → Store → Rank pipeline.
    Watch /ws WebSocket for live progress.
    """
    background_tasks.add_task(_run_pipeline_bg)
    return {
        "message": "Pipeline started. Connect to ws://localhost:8000/ws for live updates.",
        "watch": "/ws",
    }


async def _run_pipeline_bg():
    from core.database import AsyncSessionLocal
    from agents.pipeline import run_pipeline as _pipeline
    async with AsyncSessionLocal() as db:
        await _pipeline(db)
