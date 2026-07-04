"""Router-level streaming tests: fallback, mid-stream propagation, ledger, cost.

A scripted :class:`FakeStreamProvider` (no network) drives every path so the
router's streaming contract is verified deterministically.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from decimal import Decimal
from itertools import pairwise
from time import perf_counter

import pytest

from app.core.config import Settings
from app.llm.base import (
    ChatMessage,
    LLMError,
    LLMResponse,
    StreamDone,
    StreamEvent,
    TextDelta,
)
from app.llm.cost import compute_cost
from app.llm.router import LLMRouter, LLMRouterError

MESSAGES = [ChatMessage(role="user", content="hi")]


class FakeStreamProvider:
    """Scriptable streaming provider double (implements the streaming surface)."""

    def __init__(
        self,
        provider: str,
        *,
        deltas: Sequence[str] | None = None,
        usage: tuple[int, int] = (10, 20),
        credentials: bool = True,
        fail_before: bool = False,
        fail_after: int | None = None,
        delay: float = 0.0,
    ) -> None:
        self.provider = provider
        self._deltas = list(deltas if deltas is not None else ["Hello", " there", "!"])
        self._usage = usage
        self._credentials = credentials
        self._fail_before = fail_before
        self._fail_after = fail_after
        self._delay = delay
        self.stream_calls = 0

    def has_credentials(self) -> bool:
        return self._credentials

    async def chat(self, *_args: object, **_kwargs: object) -> LLMResponse:  # pragma: no cover
        raise NotImplementedError("streaming tests never call chat()")

    async def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        timeout: float = 60.0,
    ) -> AsyncIterator[StreamEvent]:
        self.stream_calls += 1
        if self._fail_before:
            raise LLMError(f"{self.provider} failed before first delta")
        for emitted, delta in enumerate(self._deltas, start=1):
            if self._delay:
                await asyncio.sleep(self._delay)
            yield TextDelta(delta)
            if self._fail_after is not None and emitted >= self._fail_after:
                raise LLMError(f"{self.provider} failed mid-stream")
        yield StreamDone(
            LLMResponse(
                text="".join(self._deltas),
                tokens_in=self._usage[0],
                tokens_out=self._usage[1],
                model=model,
                provider=self.provider,
            )
        )


def _settings() -> Settings:
    return Settings(openai_api_key=None, gemini_api_key=None, anthropic_api_key=None)


async def _drain(router: LLMRouter, **kwargs: object) -> tuple[list[str], LLMResponse | None]:
    deltas: list[str] = []
    done: LLMResponse | None = None
    async for event in router.stream_chat(messages=MESSAGES, **kwargs):  # type: ignore[arg-type]
        if isinstance(event, TextDelta):
            deltas.append(event.text)
        else:
            done = event.response
    return deltas, done


async def test_stream_happy_path_yields_deltas_then_done_with_usage() -> None:
    provider = FakeStreamProvider("openai", deltas=["Hel", "lo ", "world"], usage=(11, 7))
    router = LLMRouter(settings=_settings(), providers={"openai": provider})

    deltas, done = await _drain(router, tier="smart")

    assert deltas == ["Hel", "lo ", "world"]
    assert done is not None
    assert done.text == "Hello world"
    assert done.tokens_in == 11
    assert done.tokens_out == 7
    assert done.provider == "openai"


async def test_stream_deltas_arrive_incrementally_over_generation_window() -> None:
    # A per-delta delay proves the deltas are surfaced as they are produced
    # (not buffered into one burst at the end).
    provider = FakeStreamProvider("openai", deltas=["a", "b", "c", "d"], delay=0.02)
    router = LLMRouter(settings=_settings(), providers={"openai": provider})

    arrivals: list[float] = []
    start = perf_counter()
    async for event in router.stream_chat(tier="smart", messages=MESSAGES):
        if isinstance(event, TextDelta):
            arrivals.append(perf_counter() - start)

    assert len(arrivals) == 4
    # Each delta lands measurably after the previous one - real streaming spread.
    assert arrivals[-1] - arrivals[0] >= 0.04
    assert all(b > a for a, b in pairwise(arrivals))


async def test_pre_first_delta_failure_falls_through_to_next_provider() -> None:
    openai = FakeStreamProvider("openai", fail_before=True)
    gemini = FakeStreamProvider("gemini", deltas=["from ", "gemini"], usage=(3, 5))
    router = LLMRouter(
        settings=_settings(), providers={"openai": openai, "gemini": gemini}
    )

    deltas, done = await _drain(router, tier="smart")

    assert deltas == ["from ", "gemini"]
    assert done is not None and done.provider == "gemini"
    assert openai.stream_calls == 1  # tried
    assert gemini.stream_calls == 1  # fell through and succeeded


async def test_mid_stream_failure_propagates_and_does_not_switch() -> None:
    # openai yields one delta then dies; the router must NOT fall through
    # (that would duplicate the already-sent text) - it re-raises instead.
    openai = FakeStreamProvider("openai", deltas=["partial", "more"], fail_after=1)
    gemini = FakeStreamProvider("gemini", deltas=["should not run"])
    router = LLMRouter(
        settings=_settings(), providers={"openai": openai, "gemini": gemini}
    )

    seen: list[str] = []
    with pytest.raises(LLMError):
        async for event in router.stream_chat(tier="smart", messages=MESSAGES):
            if isinstance(event, TextDelta):
                seen.append(event.text)

    assert seen == ["partial"]  # the delta already delivered before the error
    assert gemini.stream_calls == 0  # never switched


async def test_stream_empty_completion_yields_no_deltas_then_done() -> None:
    # Provider produces zero deltas but a well-formed StreamDone (empty text).
    provider = FakeStreamProvider("openai", deltas=[], usage=(4, 0))
    router = LLMRouter(settings=_settings(), providers={"openai": provider})

    deltas, done = await _drain(router, tier="smart")

    assert deltas == []
    assert done is not None
    assert done.text == ""
    assert done.provider == "openai"
    assert done.tokens_out == 0


async def test_stream_provider_without_streamdone_gets_synthesised_done() -> None:
    # A provider that yields deltas but forgets the terminal StreamDone: the
    # router must still emit one (synthesised) so callers always finalise.
    class _NoDoneProvider:
        def has_credentials(self) -> bool:
            return True

        async def chat(self, *_a: object, **_k: object) -> LLMResponse:  # pragma: no cover
            raise NotImplementedError

        async def stream_chat(
            self, _messages: Sequence[ChatMessage], *, model: str, **_kwargs: object
        ) -> AsyncIterator[StreamEvent]:
            yield TextDelta("orphan")

    router = LLMRouter(settings=_settings(), providers={"openai": _NoDoneProvider()})

    deltas, done = await _drain(router, tier="smart")

    assert deltas == ["orphan"]
    assert done is not None
    assert done.provider == "openai"  # synthesised terminal response


async def test_stream_long_completion_passes_every_delta_through() -> None:
    # A large stream: the router forwards each delta without accumulating an
    # internal buffer (final text/usage come from the provider's StreamDone).
    chunks = [f"tok{i} " for i in range(2000)]
    provider = FakeStreamProvider("openai", deltas=chunks, usage=(3, 2000))
    router = LLMRouter(settings=_settings(), providers={"openai": provider})

    deltas, done = await _drain(router, tier="smart")

    assert len(deltas) == 2000
    assert deltas == chunks
    assert done is not None
    assert done.tokens_out == 2000


async def test_stream_cancellation_propagates_and_does_not_fall_through() -> None:
    # asyncio.CancelledError is a BaseException, not Exception: the router must
    # NOT swallow it into a fallback. It propagates so the caller's tracer can
    # finish cleanly, and no second provider is tried.
    class _CancelMidStreamProvider:
        def __init__(self, name: str) -> None:
            self.provider = name
            self.stream_calls = 0

        def has_credentials(self) -> bool:
            return True

        async def chat(self, *_a: object, **_k: object) -> LLMResponse:  # pragma: no cover
            raise NotImplementedError

        async def stream_chat(
            self, _messages: Sequence[ChatMessage], *, model: str, **_kwargs: object
        ) -> AsyncIterator[StreamEvent]:
            self.stream_calls += 1
            yield TextDelta("partial")
            raise asyncio.CancelledError

    openai = _CancelMidStreamProvider("openai")
    gemini = FakeStreamProvider("gemini", deltas=["should not run"])
    router = LLMRouter(
        settings=_settings(), providers={"openai": openai, "gemini": gemini}
    )

    seen: list[str] = []
    with pytest.raises(asyncio.CancelledError):
        async for event in router.stream_chat(tier="smart", messages=MESSAGES):
            if isinstance(event, TextDelta):
                seen.append(event.text)

    assert seen == ["partial"]
    assert openai.stream_calls == 1
    assert gemini.stream_calls == 0  # cancellation never triggers fallback


async def test_all_providers_fail_before_delta_raises_router_error() -> None:
    router = LLMRouter(
        settings=_settings(),
        providers={
            "openai": FakeStreamProvider("openai", fail_before=True),
            "gemini": FakeStreamProvider("gemini", fail_before=True),
        },
    )
    with pytest.raises(LLMRouterError):
        await _drain(router, tier="fast")


async def test_no_providers_raises() -> None:
    router = LLMRouter(settings=_settings())
    with pytest.raises(LLMRouterError):
        await _drain(router, tier="smart")


async def test_stream_done_carries_computed_cost() -> None:
    provider = FakeStreamProvider("openai", deltas=["x"], usage=(1000, 2000))
    router = LLMRouter(settings=_settings(), providers={"openai": provider})

    _deltas, done = await _drain(router, tier="smart")

    assert done is not None
    # Model comes from settings' smart tier (gpt-4.1); cost must match the table.
    assert done.cost_usd == compute_cost(done.model, 1000, 2000)
    assert done.cost_usd > Decimal("0")


# ---------------------------------------------------------------------------
# Ledger: a completed stream records one llm_calls row with the real usage/cost.
# ---------------------------------------------------------------------------


class _CaptureSession:
    def __init__(self, sink: list[object]) -> None:
        self._sink = sink

    async def __aenter__(self) -> _CaptureSession:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    def add(self, row: object) -> None:
        self._sink.append(row)

    async def commit(self) -> None:
        return None


class _CaptureSessionmaker:
    def __init__(self) -> None:
        self.rows: list[object] = []

    def __call__(self) -> _CaptureSession:
        return _CaptureSession(self.rows)


async def test_ledger_row_written_with_streamed_usage_and_cost() -> None:
    sm = _CaptureSessionmaker()
    provider = FakeStreamProvider("openai", deltas=["ok"], usage=(1000, 2000))
    router = LLMRouter(
        settings=_settings(),
        providers={"openai": provider},
        sessionmaker=sm,  # type: ignore[arg-type]
    )

    _deltas, done = await _drain(router, tier="smart", purpose="unit:stream")

    # The ledger write is fire-and-forget; wait for the background task to land.
    for _ in range(50):
        if sm.rows:
            break
        await asyncio.sleep(0.01)

    assert done is not None
    assert len(sm.rows) == 1
    row = sm.rows[0]
    assert row.provider == "openai"  # type: ignore[attr-defined]
    assert row.tokens_in == 1000  # type: ignore[attr-defined]
    assert row.tokens_out == 2000  # type: ignore[attr-defined]
    assert row.ok is True  # type: ignore[attr-defined]
    assert row.purpose == "unit:stream"  # type: ignore[attr-defined]
    assert row.cost_usd == compute_cost(done.model, 1000, 2000)  # type: ignore[attr-defined]


async def test_ledger_records_failed_provider_then_success_row() -> None:
    sm = _CaptureSessionmaker()
    openai = FakeStreamProvider("openai", fail_before=True)
    gemini = FakeStreamProvider("gemini", deltas=["ok"], usage=(5, 9))
    router = LLMRouter(
        settings=_settings(),
        providers={"openai": openai, "gemini": gemini},
        sessionmaker=sm,  # type: ignore[arg-type]
    )

    await _drain(router, tier="smart", purpose="unit:fallback")

    for _ in range(50):
        if len(sm.rows) >= 2:
            break
        await asyncio.sleep(0.01)

    by_provider = {r.provider: r for r in sm.rows}  # type: ignore[attr-defined]
    assert by_provider["openai"].ok is False
    assert by_provider["gemini"].ok is True
    assert by_provider["gemini"].tokens_out == 9
