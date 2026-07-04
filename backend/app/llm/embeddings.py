"""Text embeddings for agent memory (pgvector).

This is the **one** place in the codebase that is allowed to call a provider
SDK directly (embeddings have no place in the chat router). Primary backend is
OpenAI ``text-embedding-3-small`` (1536-d). If no OpenAI key is present it falls
back to Gemini ``text-embedding-004`` (768-d) padded/truncated to 1536 so the
vector column dimension is stable either way. Every call is logged to the
``llm_calls`` ledger with ``purpose="embedding"`` (fire-and-forget), mirroring
the router so cost/traffic accounting stays complete.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.llm.base import LLMError
from app.models.enums import LlmTier
from app.models.memory import EMBEDDING_DIM

logger = get_logger(__name__)

OPENAI_EMBED_MODEL = "text-embedding-3-small"
GEMINI_EMBED_MODEL = "text-embedding-004"


def _fit_dim(vec: list[float], dim: int = EMBEDDING_DIM) -> list[float]:
    """Pad with zeros / truncate ``vec`` to exactly ``dim`` components."""
    if len(vec) == dim:
        return vec
    if len(vec) > dim:
        return vec[:dim]
    return vec + [0.0] * (dim - len(vec))


class Embedder:
    """Async embedding client with provider fallback and usage logging."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._openai_key = self._settings.openai_api_key
        self._gemini_key = self._settings.gemini_api_key
        self._openai_client: object | None = None
        self._gemini_client: object | None = None
        self._bg: set[asyncio.Task[None]] = set()

    def available(self) -> bool:
        return bool(self._openai_key or self._gemini_key)

    async def embed(self, text: str) -> list[float]:
        """Embed a single string into a 1536-d vector."""
        return (await self.embed_many([text]))[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of strings. Returns one 1536-d vector per input."""
        if not texts:
            return []
        if self._openai_key:
            return await self._embed_openai(texts)
        if self._gemini_key:
            return await self._embed_gemini(texts)
        raise LLMError(
            "no embedding provider configured; set OPENAI_API_KEY or GEMINI_API_KEY"
        )

    # -- providers ------------------------------------------------------------
    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        from openai import AsyncOpenAI

        if self._openai_client is None:
            self._openai_client = AsyncOpenAI(api_key=self._openai_key)
        client: AsyncOpenAI = self._openai_client  # type: ignore[assignment]
        try:
            resp = await client.embeddings.create(model=OPENAI_EMBED_MODEL, input=texts)
        except Exception as exc:
            raise LLMError(f"openai embedding failed: {exc}") from exc
        vectors = [_fit_dim(list(d.embedding)) for d in resp.data]
        tokens = resp.usage.total_tokens if resp.usage else 0
        self._log("openai", OPENAI_EMBED_MODEL, tokens)
        return vectors

    async def _embed_gemini(self, texts: list[str]) -> list[list[float]]:
        from google import genai
        from google.genai import types

        if self._gemini_client is None:
            self._gemini_client = genai.Client(api_key=self._gemini_key)
        client: genai.Client = self._gemini_client  # type: ignore[assignment]
        try:
            resp = await client.aio.models.embed_content(
                model=GEMINI_EMBED_MODEL,
                contents=texts,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
            )
        except Exception as exc:
            raise LLMError(f"gemini embedding failed: {exc}") from exc
        vectors = [_fit_dim(list(e.values or [])) for e in (resp.embeddings or [])]
        approx_tokens = sum(len(t.split()) for t in texts)
        self._log("gemini", GEMINI_EMBED_MODEL, approx_tokens)
        return vectors

    # -- usage ledger (fire-and-forget) --------------------------------------
    def _log(self, provider: str, model: str, tokens_in: int) -> None:
        try:
            task = asyncio.create_task(self._persist(provider, model, tokens_in))
        except RuntimeError:
            return
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _persist(self, provider: str, model: str, tokens_in: int) -> None:
        from app.llm.cost import compute_cost
        from app.models.tracing import LlmCall

        try:
            async with get_sessionmaker()() as session:
                session.add(
                    LlmCall(
                        provider=provider,
                        model=model,
                        tier=LlmTier.FAST,
                        tokens_in=tokens_in,
                        tokens_out=0,
                        cost_usd=compute_cost(model, tokens_in, 0),
                        latency_ms=None,
                        ok=True,
                        error=None,
                        purpose="embedding",
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.warning("embedding_persist_failed", error=str(exc))


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    """Process-wide cached embedder wired to settings."""
    return Embedder(get_settings())
