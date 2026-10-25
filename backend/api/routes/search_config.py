"""
SearchConfig CRUD + pipeline trigger endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field, field_validator
from core.database import get_db
from models.search_config import SearchConfig

router = APIRouter(prefix="/api/search-config", tags=["search-config"])

SUPPORTED_PORTALS = {
    "linkedin",
    "remoteok",
    "weworkremotely",
    "hackernews",
    "jobleads",
}


class SearchConfigCreate(BaseModel):
    keywords: list[str]
    locations: list[str] = ["remote"]
    portals: list[str] = ["linkedin", "remoteok", "weworkremotely", "hackernews"]
    remote_only: bool = False
    posted_within_days: int = Field(default=7, ge=1, le=365)
    active: bool = True
    run_every_hours: int = Field(default=12, ge=0, le=8760)
    # Search depth — configurable instead of hardcoded
    max_results_per_search: int = 15   # results per keyword+location+portal combo
    linkedin_pages: int = 1            # LinkedIn pagination pages (each page = 25 jobs)
    # Auto-research: 0 = disabled, N = research top N jobs by score after each run
    auto_research_top_n: int = 5

    @field_validator("keywords", "locations")
    @classmethod
    def validate_search_terms(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if not cleaned:
            raise ValueError("Provide at least one keyword and location.")
        return cleaned

    @field_validator("portals")
    @classmethod
    def validate_portals(cls, portals: list[str]) -> list[str]:
        unknown = sorted(set(portals) - SUPPORTED_PORTALS)
        if unknown:
            supported = ", ".join(sorted(SUPPORTED_PORTALS))
            raise ValueError(
                f"Unsupported portal(s): {', '.join(unknown)}. "
                f"Supported portals: {supported}"
            )
        if not portals:
            raise ValueError("Select at least one portal.")
        return portals

    @field_validator("max_results_per_search")
    @classmethod
    def validate_max_results(cls, v: int) -> int:
        if v < 5:
            raise ValueError("max_results_per_search must be at least 5")
        if v > 100:
            raise ValueError("max_results_per_search cannot exceed 100")
        return v

    @field_validator("linkedin_pages")
    @classmethod
    def validate_linkedin_pages(cls, v: int) -> int:
        if v < 1:
            raise ValueError("linkedin_pages must be at least 1")
        if v > 4:
            raise ValueError("linkedin_pages cannot exceed 4 (LinkedIn blocks aggressive pagination)")
        return v

    @field_validator("auto_research_top_n")
    @classmethod
    def validate_auto_research(cls, v: int) -> int:
        if v < 0:
            raise ValueError("auto_research_top_n cannot be negative (use 0 to disable)")
        if v > 50:
            raise ValueError("auto_research_top_n cannot exceed 50")
        return v


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


@pipeline_router.post("/run", status_code=202)
async def run_pipeline(
    db: AsyncSession = Depends(get_db),
):
    """
    Manually trigger the full Search → Store → Rank pipeline.
    Watch /ws WebSocket for live progress.
    """
    from core.runs import enqueue_run, run_response
    from models.profile import UserProfile
    from workers.scheduler import snapshot
    config = (await db.execute(select(SearchConfig).where(SearchConfig.active == True).limit(1))).scalar_one_or_none()
    if not config:
        raise HTTPException(400, "Save a search configuration before starting the pipeline.")
    if not (await db.execute(select(UserProfile.id).limit(1))).first():
        raise HTTPException(400, "Create a profile before starting the pipeline.")
    run, created = await enqueue_run(db, "pipeline", snapshot(config), config_id=config.id)
    return run_response(run, created)
