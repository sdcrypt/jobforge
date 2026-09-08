"""Health check endpoints."""

from fastapi import APIRouter
from core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "llm_provider": settings.llm_base_url,
        "llm_model_smart": settings.llm_model_smart,
        "llm_model_fast": settings.llm_model_fast,
    }


@router.get("/health/llm")
async def health_llm():
    """Check that the LLM backend (Ollama / OpenAI) is reachable."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
    )
    try:
        resp = await client.chat.completions.create(
            model=settings.llm_model_fast,
            messages=[{"role": "user", "content": "Reply with: OK"}],
            max_tokens=5,
        )
        return {
            "status": "connected",
            "model": settings.llm_model_fast,
            "response": resp.choices[0].message.content,
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}
