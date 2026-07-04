"""Redis Streams consumer: `txn.events` -> deterministic prefilter -> agent mesh.

Run with ``python -m app.workers.event_consumer`` (Makefile target ``worker``).

Pipeline, per Stream entry:

1. Resolve the customer (``Customer.id == envelope["customer_id"]`` - see the
   seeding ID contract in ``app.seed``: ``Customer.id`` *is* the sim persona id).
   Unknown customer -> ack and skip (debug log), not a failure.
2. Persist a ``Transaction`` row + update the account balance atomically and
   idempotently, keyed on the envelope's ``event_id``
   (:func:`app.services.ledger.post_transaction_idempotent`). A duplicate delivery
   of an already-applied ``event_id`` is a no-op (ack, skip further processing).
3. Run every deterministic prefilter rule (:mod:`app.workers.prefilter`) over the
   customer's trailing transaction window.
4. For each matched rule, gate on a Redis cooldown
   (``agent.cooldown:{customer_id}:{rule}``, ``SETNX``+TTL) so at most one agent
   run fires per customer per rule per cooldown window.
5. Call :func:`app.agents.entrypoints.run_event_trigger` with a crisp
   ``event_summary`` + the raw evidence, and publish the outcome onto the
   `agent.actions` console-feed stream (:mod:`app.workers.activity`).
6. Ack the entry. On an unhandled exception, the entry is left pending (not
   acked); :func:`_reclaim_stale` periodically reclaims entries idle longer than
   ``CLAIM_MIN_IDLE_MS`` via ``XAUTOCLAIM`` and retries them, up to
   ``MAX_DELIVERIES`` (tracked via ``XPENDING``'s delivery count) before the raw
   entry is moved to ``txn.events.dlq`` and acked off the main stream. One bad
   event never blocks the loop - every entry is handled in its own try/except.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import uuid
from datetime import UTC, datetime
from typing import Any
from weakref import WeakKeyDictionary

import orjson

from app.agents.entrypoints import run_event_trigger
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import get_logger, setup_logging
from app.core.redis import GROUP_AGENTS, TXN_EVENTS, TXN_EVENTS_DLQ, get_redis
from app.models.customer import Customer
from app.services import ledger
from app.workers.activity import publish_run_result
from app.workers.prefilter import TxnLike, evaluate_rules

logger = get_logger(__name__)

CONSUMER_NAME = f"consumer-{uuid.uuid4().hex[:8]}"
BLOCK_MS = 5_000
BATCH_COUNT = 10
CLAIM_MIN_IDLE_MS = 30_000
MAX_DELIVERIES = 3
HISTORY_WINDOW_DAYS = 200
"""Lookback window for trailing-median / recurring-category rule context."""

AGENT_RUN_TIMEOUT_SECONDS = 120.0
"""Hard ceiling on a single agent trigger. A run that wedges (a hung LLM call, a
runaway graph) must not pin the consumer forever; on timeout we DLQ the envelope
and move on rather than blocking the whole stream."""

AGENT_RUN_CONCURRENCY = 2
"""Max concurrent agent runs across the worker. An event burst (e.g. a big sim
inject) could otherwise fan out dozens of simultaneous LLM-spending runs; this
semaphore paces them so spend and provider load stay bounded."""

# Semaphore keyed by the running loop object so a fresh loop (each pytest-asyncio
# test gets one) never awaits a semaphore bound to a dead loop. A WeakKeyDictionary
# drops the entry when the loop is GC'd and keys on the loop identity itself (not a
# reusable id()). In the long-lived worker process there is exactly one loop, hence
# exactly one semaphore.
_agent_semaphores: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    WeakKeyDictionary()
)


def _agent_run_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _agent_semaphores.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(AGENT_RUN_CONCURRENCY)
        _agent_semaphores[loop] = sem
    return sem


async def ensure_group() -> None:
    """Create the ``sarathi-agents`` consumer group on ``txn.events`` (idempotent)."""
    redis = get_redis()
    try:
        await redis.xgroup_create(TXN_EVENTS, GROUP_AGENTS, id="0", mkstream=True)
        logger.info("consumer_group_created", group=GROUP_AGENTS, stream=TXN_EVENTS)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _cooldown_key(customer_id: str, rule: str) -> str:
    return f"agent.cooldown:{customer_id}:{rule}"


async def _acquire_cooldown(customer_id: str, rule: str) -> bool:
    """``SETNX``-style acquire: True if this call won the cooldown window."""
    redis = get_redis()
    settings = get_settings()
    acquired = await redis.set(
        _cooldown_key(customer_id, rule), "1", ex=settings.event_cooldown_seconds, nx=True
    )
    return bool(acquired)


def _parse_event_ts(raw_ts: Any) -> datetime:
    """Parse an envelope ``ts`` into a timezone-*aware* datetime.

    Sim/generator (and console-injected) timestamps serialize without an offset,
    so ``datetime.fromisoformat`` returns a naive value. Transactions loaded back
    from Postgres, however, come back aware (the column is ``timestamptz``). The
    deterministic prefilter mixes the just-created transaction with DB-loaded
    history in the same window/sort, so a naive new-event ts against aware history
    raises ``can't compare offset-naive and offset-aware datetimes`` and drops the
    event (no rule ever fires). Normalizing the incoming ts to aware UTC keeps
    every comparison on the same footing.
    """
    if not raw_ts:
        return datetime.now(UTC)
    ts = datetime.fromisoformat(str(raw_ts))
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _txn_to_txnlike(txn: Any) -> TxnLike:
    return TxnLike(
        ts=txn.ts,
        amount_paise=txn.amount_paise,
        direction=txn.direction.value,
        channel=txn.channel.value,
        category=txn.category,
        merchant=txn.merchant,
        balance_after_paise=txn.balance_after_paise,
    )


async def _run_agent_guarded(
    customer_id: str, match: Any, new_txn: TxnLike, envelope: dict[str, Any]
) -> Any | None:
    """Run one agent trigger under the concurrency semaphore + runtime timeout.

    Returns the :class:`AgentRunResult` on success, or ``None`` if the run timed
    out (in which case the raw envelope is dead-lettered and processing continues -
    a single wedged run must never stall the whole stream).
    """
    sem = _agent_run_semaphore()
    async with sem:
        try:
            async with asyncio.timeout(AGENT_RUN_TIMEOUT_SECONDS):
                return await run_event_trigger(
                    customer_id,
                    match.event_summary,
                    event={
                        "rule": match.rule,
                        "evidence": match.evidence,
                        "transaction": dict(new_txn),
                    },
                )
        except TimeoutError:
            logger.error(
                "event_agent_run_timeout",
                customer_id=customer_id,
                rule=match.rule,
                timeout_s=AGENT_RUN_TIMEOUT_SECONDS,
            )
            await get_redis().xadd(
                TXN_EVENTS_DLQ,
                {
                    "data": orjson.dumps(envelope).decode(),
                    "error": f"agent_run_timeout after {AGENT_RUN_TIMEOUT_SECONDS}s",
                    "rule": match.rule,
                },
            )
            return None


async def process_envelope(envelope: dict[str, Any]) -> None:
    """Handle one decoded `txn.events` envelope end to end."""
    customer_id_raw = str(envelope.get("customer_id") or "")
    payload = envelope.get("payload") or {}
    event_id = str(envelope.get("event_id") or payload.get("event_id") or "")
    if not customer_id_raw or not event_id:
        logger.warning("event_missing_ids", envelope=envelope)
        return

    try:
        customer_uuid = uuid.UUID(customer_id_raw)
    except ValueError:
        logger.debug("event_unknown_customer_id_format", customer_id=customer_id_raw)
        return

    sm = get_sessionmaker()
    new_txn: TxnLike | None = None
    history: list[TxnLike] = []
    upi_active = False

    async with sm() as session:
        customer = await session.get(Customer, customer_uuid)
        if customer is None:
            logger.debug("event_unknown_customer", customer_id=customer_id_raw)
            return
        upi_active = bool((customer.persona or {}).get("upi_active"))

        accounts = await ledger.list_accounts(session, customer.id)
        if not accounts:
            logger.warning("event_customer_has_no_account", customer_id=customer_id_raw)
            return
        account = accounts[0]

        ts = _parse_event_ts(payload.get("ts"))
        txn = await ledger.post_transaction_idempotent(
            session,
            account_id=account.id,
            event_id=event_id,
            amount_paise=int(payload["amount_paise"]),
            direction=str(payload["direction"]),
            channel=str(payload["channel"]),
            merchant=payload.get("merchant"),
            mcc=payload.get("mcc"),
            category=payload.get("category"),
            description=payload.get("description"),
            ts=ts,
        )
        if txn is None:
            await session.commit()
            logger.debug("event_already_applied", event_id=event_id)
            return

        history_rows = await ledger.get_recent_transactions(
            session, customer.id, days=HISTORY_WINDOW_DAYS
        )
        history = [_txn_to_txnlike(t) for t in history_rows if t.id != txn.id]
        new_txn = _txn_to_txnlike(txn)
        await session.commit()

    assert new_txn is not None
    matches = evaluate_rules(history, new_txn, upi_active=upi_active)
    if not matches:
        return

    redis = get_redis()
    for match in matches:
        if not await _acquire_cooldown(customer_id_raw, match.rule):
            logger.debug(
                "event_rule_cooldown_active", customer_id=customer_id_raw, rule=match.rule
            )
            continue
        logger.info("event_rule_matched", customer_id=customer_id_raw, rule=match.rule)
        result = await _run_agent_guarded(customer_id_raw, match, new_txn, envelope)
        if result is None:
            continue  # timed out and dead-lettered; keep draining the other matches
        await publish_run_result(
            redis,
            customer_id=customer_id_raw,
            run_id=result.run_id,
            run_summary=f"[{match.rule}] {result.final_text[:200] or match.event_summary}",
            proposals=result.proposals,
            life_events=result.life_events,
            nudges=result.nudges,
        )


async def _delivery_count(redis: Any, entry_id: str) -> int:
    info = await redis.xpending_range(TXN_EVENTS, GROUP_AGENTS, min=entry_id, max=entry_id, count=1)
    if not info:
        return 1
    return int(info[0]["times_delivered"])


async def _handle_delivery(redis: Any, entry_id: str, fields: dict[str, str]) -> None:
    """Process one Stream entry with per-entry error isolation and DLQ escalation."""
    raw = fields.get("data")
    if raw is None:
        logger.warning("event_entry_missing_data_field", entry_id=entry_id)
        await redis.xack(TXN_EVENTS, GROUP_AGENTS, entry_id)
        return

    try:
        envelope = orjson.loads(raw)
        await process_envelope(envelope)
        await redis.xack(TXN_EVENTS, GROUP_AGENTS, entry_id)
    except Exception as exc:
        logger.exception("event_processing_failed", entry_id=entry_id, error=str(exc))
        deliveries = await _delivery_count(redis, entry_id)
        if deliveries >= MAX_DELIVERIES:
            await redis.xadd(TXN_EVENTS_DLQ, {**fields, "error": str(exc), "original_id": entry_id})
            await redis.xack(TXN_EVENTS, GROUP_AGENTS, entry_id)
            logger.error("event_moved_to_dlq", entry_id=entry_id, deliveries=deliveries)
        # else: leave un-acked/pending - `_reclaim_stale` retries it once idle long enough.


async def _consume_new(redis: Any) -> None:
    resp = await redis.xreadgroup(
        GROUP_AGENTS, CONSUMER_NAME, {TXN_EVENTS: ">"}, count=BATCH_COUNT, block=BLOCK_MS
    )
    for _stream_name, entries in resp or []:
        for entry_id, fields in entries:
            await _handle_delivery(redis, entry_id, fields)


async def _reclaim_stale(redis: Any) -> None:
    """Reclaim + retry entries idle longer than ``CLAIM_MIN_IDLE_MS`` (crash/timeout retry)."""
    result = await redis.xautoclaim(
        TXN_EVENTS, GROUP_AGENTS, CONSUMER_NAME, min_idle_time=CLAIM_MIN_IDLE_MS,
        start_id="0-0", count=BATCH_COUNT,
    )
    _cursor, claimed, *_rest = result
    for entry_id, fields in claimed:
        await _handle_delivery(redis, entry_id, fields)


async def run_forever(stop_event: asyncio.Event) -> None:
    """Main consume loop: new entries each pass, stale-pending reclaim between passes."""
    setup_logging()
    await ensure_group()
    redis = get_redis()
    logger.info("event_consumer_started", consumer=CONSUMER_NAME, group=GROUP_AGENTS)
    while not stop_event.is_set():
        try:
            await _consume_new(redis)
            if not stop_event.is_set():
                await _reclaim_stale(redis)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("event_consumer_loop_error")
            await asyncio.sleep(1.0)
    logger.info("event_consumer_stopped", consumer=CONSUMER_NAME)


async def _amain() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)
    await run_forever(stop_event)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
