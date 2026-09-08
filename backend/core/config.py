"""
JobForge — Application settings
Reads from .env file. Change LLM_BASE_URL to switch providers.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "JobForge"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "change-me"

    # LLM — Ollama by default, swap to OpenAI/Groq via .env
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model_smart: str = "qwen2.5:7b"   # complex reasoning
    llm_model_fast: str = "llama3.2:3b"   # fast parallel calls

    # Database
    database_url: str = "sqlite+aiosqlite:///./jobforge.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Documents
    documents_dir: str = "./documents"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

    @property
    def is_local_llm(self) -> bool:
        """True when running against Ollama or similar local server."""
        return "localhost" in self.llm_base_url or "127.0.0.1" in self.llm_base_url


settings = Settings()
