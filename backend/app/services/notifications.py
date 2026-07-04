"""Customer notification primitive: record that something real happened.

``notify`` is the single creation path. It is deliberately tiny and never calls
an LLM - notifications mirror content that was already generated (an executed
proposal, a detected life event, an opened account, a delivered nudge, readied
demo activity). Callers own the surrounding transaction; ``notify`` flushes but
does not commit, so a notification lands atomically with the event that caused it.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engagement import Notification
from app.models.enums import NotificationKind

# Mirror of the ORM column width so a long generated title cannot overflow.
_TITLE_MAX = 200


async def notify(
    session: AsyncSession,
    customer_id: uuid.UUID,
    kind: NotificationKind | str,
    title: str,
    body: str,
    link: str | None = None,
) -> Notification:
    """Record a customer-facing notification within the caller's transaction."""
    notification = Notification(
        customer_id=customer_id,
        kind=kind if isinstance(kind, NotificationKind) else NotificationKind(kind),
        title=title.strip()[:_TITLE_MAX],
        body=body.strip(),
        link=link,
    )
    session.add(notification)
    await session.flush()
    return notification
