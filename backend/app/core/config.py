"""Application settings, loaded from the repo-root ``.env`` via pydantic-settings."""

from __future__ import annotations

import contextlib
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
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

    # Purpose-based provider routing. Comma-separated "<key>=<provider>[:<model>]"
    # entries; a key matches when it equals any ':'-separated segment of a call's
    # ``purpose`` (so "classify" matches "supervisor:classify"). The matched provider
    # is tried FIRST when its API key is configured, then the normal tier fallback
    # chain. This keeps Gemini genuinely in rotation (intent classification) while
    # OpenAI stays the default, so cost traces show both providers in a real session.
    # "embedding" documents the embeddings backend (see app/llm/embeddings.py).
    llm_purpose_routing: str = "classify=gemini:gemini-2.5-flash-lite,embedding=openai"

    # --- database / cache ---
    database_url: str = "postgresql+asyncpg://sarathi:sarathi@localhost:5432/sarathi"
    redis_url: str = "redis://localhost:6379/0"

    # --- auth ---
    google_client_id: str | None = None
    google_client_secret: str | None = None
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_seconds: int = 60 * 15
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 7
    # Cookie `Domain` attribute; None = exact host only (fine for single-host dev/demo).
    # Set to e.g. ".sarathi.example" in prod if the frontend/backend live on sibling subdomains.
    cookie_domain: str | None = None
    webauthn_rp_id: str = "localhost"
    webauthn_origin: str = "http://localhost:3000"
    webauthn_challenge_ttl_seconds: int = 60 * 5
    otp_ttl_seconds: int = 60 * 10
    otp_rate_limit_per_hour: int = 3

    # --- request hardening (rate limits, body cap, proxy trust) ---
    # Trust the first hop of ``X-Forwarded-For`` for client-IP rate limiting.
    # nginx fronts us in prod, so the real client IP is the first XFF entry there;
    # in dev the app is hit directly and a client could spoof the header, so we
    # only trust it outside dev OR when this flag is explicitly set (tests).
    trust_forwarded_for: bool = False
    # Hard cap on request body size (Content-Length). Bodies above this are
    # rejected with a 413 envelope before the route runs. 256 KiB comfortably
    # fits every real request (chat text is capped at 8000 chars) while stopping
    # an accidental or malicious multi-megabyte upload from reaching the app.
    max_request_bytes: int = 256 * 1024

    # --- email (AWS SES ap-south-1) ---
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "ap-south-1"
    ses_from_address: str = "no-reply@niheshr.com"

    # --- CORS ---
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- console / staff gate ---
    # Plain string field (never JSON-decoded at the settings-source layer, so it
    # can never crash on a bare `.env` value) accepting either a comma-separated
    # list ("a@x.com,b@x.com") or a JSON array ("[\"a@x.com\"]") - see
    # `staff_email_list`. Empty in dev = any authenticated user passes
    # `get_current_staff` (with a warning).
    staff_emails: str = ""

    # --- event consumer ---
    event_cooldown_seconds: int = 300
    """Per-(customer, rule) cooldown before another agent run may be triggered."""

    @property
    def staff_email_list(self) -> list[str]:
        raw = self.staff_emails.strip()
        if raw.startswith("["):
            import json

            with contextlib.suppress(json.JSONDecodeError, TypeError):
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(e).strip() for e in parsed if str(e).strip()]
        return [e.strip() for e in raw.split(",") if e.strip()]

    @property
    def is_dev(self) -> bool:
        return self.app_env.lower() in {"dev", "development", "local"}

    @property
    def trust_client_forwarded_for(self) -> bool:
        """Whether to believe ``X-Forwarded-For`` for client-IP resolution.

        True in any non-dev deployment (nginx sets a trustworthy first hop) or
        when ``trust_forwarded_for`` is explicitly enabled."""
        return (not self.is_dev) or self.trust_forwarded_for

    @property
    def has_any_llm_key(self) -> bool:
        return any((self.openai_api_key, self.gemini_api_key, self.anthropic_api_key))

    @property
    def llm_purpose_routing_map(self) -> dict[str, tuple[str, str | None]]:
        """Parse ``llm_purpose_routing`` into ``{key: (provider, model|None)}``."""
        out: dict[str, tuple[str, str | None]] = {}
        for raw_entry in self.llm_purpose_routing.split(","):
            entry = raw_entry.strip()
            if not entry or "=" not in entry:
                continue
            key, target = (part.strip() for part in entry.split("=", 1))
            if not key or not target:
                continue
            if ":" in target:
                provider, model = (part.strip() for part in target.split(":", 1))
                out[key] = (provider, model or None)
            else:
                out[key] = (target, None)
        return out

    @model_validator(mode="after")
    def _require_real_jwt_secret_outside_dev(self) -> Settings:
        """Refuse to boot with the placeholder JWT secret anywhere but dev - sessions are
        only as secure as this key."""
        if not self.is_dev and self.jwt_secret == "change-me":
            raise ValueError("JWT_SECRET must be set to a real secret when APP_ENV != dev")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance."""
    return Settings()


def is_staff_email(email: str) -> bool:
    """Shared staff-gate predicate: ``app.api.v1.console.get_current_staff`` and
    ``GET /me``'s ``is_staff`` flag both derive from this single rule so they can
    never disagree. Empty allowlist + ``APP_ENV=dev`` -> everyone is staff."""
    settings = get_settings()
    allowlist = {e.lower() for e in settings.staff_email_list}
    if not allowlist:
        return settings.is_dev
    return email.lower() in allowlist
