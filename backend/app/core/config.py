"""Application settings, loaded from the repo-root ``.env`` via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# repo root = backend/app/core/config.py -> parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Typed application configuration.

    Values are read (case-insensitively) from the repo-root ``.env`` file and the
    process environment. Nested settings use a ``__`` delimiter.
    """

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # --- app ---
    app_env: str = "dev"
    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    # --- LLM providers (at least one key required for live calls) ---
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None

    # --- LLM model table (config-driven so ids are trivially bumpable) ---
    openai_model_fast: str = "gpt-4.1-mini"
    openai_model_smart: str = "gpt-4.1"
    gemini_model_fast: str = "gemini-2.5-flash"
    gemini_model_smart: str = "gemini-2.5-pro"
    anthropic_model_fast: str = "claude-haiku-4-5"
    anthropic_model_smart: str = "claude-sonnet-4-6"

    # --- LLM router behaviour ---
    llm_timeout_seconds: float = 60.0
    llm_default_max_tokens: int = 1024

    # --- database / cache ---
    database_url: str = "postgresql+asyncpg://sarathi:sarathi@localhost:5432/sarathi"
    redis_url: str = "redis://localhost:6379/0"

    # --- auth ---
    google_client_id: str | None = None
    google_client_secret: str | None = None
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_seconds: int = 60 * 30
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 14
    webauthn_rp_id: str = "localhost"
    webauthn_origin: str = "http://localhost:3000"

    # --- email (AWS SES ap-south-1) ---
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "ap-south-1"
    ses_from_address: str = "no-reply@niheshr.com"

    # --- CORS ---
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @property
    def is_dev(self) -> bool:
        return self.app_env.lower() in {"dev", "development", "local"}

    @property
    def has_any_llm_key(self) -> bool:
        return any((self.openai_api_key, self.gemini_api_key, self.anthropic_api_key))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance."""
    return Settings()
