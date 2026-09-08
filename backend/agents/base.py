"""
JobForge — BaseAgent
All agents inherit from this. Handles:
  - OpenAI-compatible client (works with Ollama, Groq, OpenAI — same code)
  - WebSocket event broadcasting
  - DB event persistence
  - Retry logic for LLM calls
  - Streaming support
"""

import json
from abc import ABC, abstractmethod
from typing import Any
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog

from core.config import settings
from core.websocket import ws_manager

log = structlog.get_logger()


# Shared LLM client — one instance, used by all agents
_llm_client = AsyncOpenAI(
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
)


class BaseAgent(ABC):
    """
    Base class for all JobForge agents.

    Usage:
        class SearchAgent(BaseAgent):
            name = "search"
            model = settings.llm_model_fast

            async def run(self, **kwargs):
                await self.emit("started", "Searching LinkedIn...")
                result = await self.chat([{"role": "user", "content": "..."}])
                await self.emit("done", f"Found {len(result)} jobs")
                return result
    """

    name: str = "agent"
    model: str = settings.llm_model_smart

    def __init__(self, db=None, job_id: str | None = None):
        self.db = db
        self.job_id = job_id
        self.client = _llm_client

    # ─── Event broadcasting ───────────────────────────────────────────────

    async def emit(self, status: str, message: str, data: dict | None = None):
        """Broadcast agent status to UI via WebSocket and persist to DB."""
        log.info("agent.event", agent=self.name, status=status, message=message)

        # Broadcast to all connected WebSocket clients (real-time UI feed)
        await ws_manager.emit_agent_event(
            agent=self.name,
            status=status,
            message=message,
            data=data,
        )

        # Persist to DB for history
        if self.db:
            from models.application import AgentEvent
            event = AgentEvent(
                agent=self.name,
                status=status,
                message=message,
                extra=data,
                job_id=self.job_id,
            )
            self.db.add(event)
            await self.db.flush()

    # ─── LLM calls ───────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        """
        Single LLM call. Returns the assistant's response text.
        Works with Ollama, Groq, OpenAI — identical API.
        """
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    async def chat_json(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.1,
    ) -> dict:
        """
        LLM call that guarantees a JSON response.
        Falls back to parsing if json_mode isn't supported (some Ollama models).
        """
        try:
            text = await self.chat(
                messages, model=model, temperature=temperature, json_mode=True
            )
        except Exception:
            # Some local models don't support json_mode — call without it
            text = await self.chat(messages, model=model, temperature=temperature)

        # Extract JSON from response (handles markdown code blocks too)
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])  # strip ```json ... ```

        return json.loads(text)

    async def stream_chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.5,
    ):
        """
        Streaming LLM call — yields text chunks.
        Use for DocGen where long output benefits from streaming.
        """
        stream = await self.client.chat.completions.create(
            model=model or self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=8192,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    # ─── Abstract interface ───────────────────────────────────────────────

    @abstractmethod
    async def run(self, **kwargs) -> Any:
        """Override in each agent subclass."""
        ...

    # ─── Helpers ─────────────────────────────────────────────────────────

    def system(self, content: str) -> dict:
        return {"role": "system", "content": content}

    def user(self, content: str) -> dict:
        return {"role": "user", "content": content}

    def assistant(self, content: str) -> dict:
        return {"role": "assistant", "content": content}
