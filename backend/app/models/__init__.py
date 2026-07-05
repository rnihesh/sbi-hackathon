"""SQLAlchemy ORM models.

Importing this package registers every model on ``Base.metadata`` (required for
Alembic autogenerate and for relationship string-resolution).
"""

from __future__ import annotations

from app.models.audit import GENESIS_HASH, AuditLog, chain_hash
from app.models.banking import Account, Transaction
from app.models.base import Base
from app.models.catalog import Holding, Product
from app.models.conversation import Conversation, Message
from app.models.crm import Lead
from app.models.customer import Customer
from app.models.engagement import LifeEvent, Notification, Nudge, Proposal
from app.models.enums import (
    AccountStatus,
    AccountType,
    AgentRunStatus,
    AgentStepKind,
    AgentTriggerType,
    ConversationChannel,
    CredentialTransport,
    DigitalMaturity,
    GoalStatus,
    HandoffStatus,
    HandoffUrgency,
    HoldingStatus,
    LeadStage,
    LifeEventStatus,
    LifeEventType,
    LlmTier,
    MemoryKind,
    MessageRole,
    NotificationKind,
    NudgeStatus,
    ProposalKind,
    ProposalStatus,
    StandingCadence,
    StandingPurpose,
    StandingStatus,
    TxnChannel,
    TxnDirection,
)
from app.models.goal import SavingsGoal
from app.models.handoff import HandoffRequest
from app.models.identity import Credential, OtpCode, User
from app.models.memory import EMBEDDING_DIM, AgentMemory
from app.models.notes import StaffNote
from app.models.sim_injection import SimInjection
from app.models.standing import StandingInstruction
from app.models.tracing import AgentRun, AgentStep, LlmCall

__all__ = [  # noqa: RUF022 - grouped by domain for readability, not sorted
    "EMBEDDING_DIM",
    "GENESIS_HASH",
    # base
    "Base",
    # identity
    "User",
    "Credential",
    "OtpCode",
    # customer
    "Customer",
    # banking
    "Account",
    "Transaction",
    # catalog
    "Product",
    "Holding",
    # crm
    "Lead",
    # goals
    "SavingsGoal",
    # standing instructions
    "StandingInstruction",
    # handoff
    "HandoffRequest",
    # conversation
    "Conversation",
    "Message",
    # tracing
    "AgentRun",
    "AgentStep",
    "LlmCall",
    # engagement
    "Proposal",
    "Nudge",
    "Notification",
    "LifeEvent",
    # sim
    "SimInjection",
    # audit
    "AuditLog",
    "chain_hash",
    # memory
    "AgentMemory",
    # notes
    "StaffNote",
    # enums
    "AccountStatus",
    "AccountType",
    "AgentRunStatus",
    "AgentStepKind",
    "AgentTriggerType",
    "ConversationChannel",
    "CredentialTransport",
    "DigitalMaturity",
    "GoalStatus",
    "HandoffStatus",
    "HandoffUrgency",
    "HoldingStatus",
    "LeadStage",
    "LifeEventStatus",
    "LifeEventType",
    "LlmTier",
    "MemoryKind",
    "MessageRole",
    "NotificationKind",
    "NudgeStatus",
    "ProposalKind",
    "ProposalStatus",
    "StandingCadence",
    "StandingPurpose",
    "StandingStatus",
    "TxnChannel",
    "TxnDirection",
]
