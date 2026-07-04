"""Ground-truth record of a console-injected sim life event.

The sim's ``POST /console/sim/inject-event`` replays a persona forward through a
life-event script and publishes the resulting transactions onto ``txn.events``.
Persisting *what* was injected (type + customer + time + the script's ground-truth
params) turns each injection into an auditable label the detection scorecard
(``GET /console/analytics/detection``) grades the agent mesh against: did a
``life_event`` of the right family get detected, how confident, and how long
after the inject.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPKMixin


class SimInjection(UUIDPKMixin, Base):
    """One console-triggered life-event injection: the detection ground truth."""

    __tablename__ = "sim_injections"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The sim `LifeEventType` value (e.g. "home_purchase_intent"), which is a
    # distinct namespace from the detected `life_events.type` enum - the scorecard
    # maps between them via a type-family table.
    injected_type: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    injected_by: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    injected_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), index=True, nullable=False
    )
