"""Enumerations shared across ORM models (stored as VARCHAR + CHECK, not native)."""

from __future__ import annotations

from enum import StrEnum


class DigitalMaturity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AccountType(StrEnum):
    SAVINGS = "savings"
    CURRENT = "current"
    SALARY = "salary"
    FIXED_DEPOSIT = "fixed_deposit"
    RECURRING_DEPOSIT = "recurring_deposit"
    LOAN = "loan"
    CREDIT_CARD = "credit_card"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    DORMANT = "dormant"
    FROZEN = "frozen"
    CLOSED = "closed"


class TxnDirection(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class TxnChannel(StrEnum):
    UPI = "upi"
    CARD = "card"
    NEFT = "neft"
    IMPS = "imps"
    RTGS = "rtgs"
    ATM = "atm"
    CASH = "cash"
    AUTO_DEBIT = "auto_debit"
    NETBANKING = "netbanking"
    CHEQUE = "cheque"


class HoldingStatus(StrEnum):
    OFFERED = "offered"
    ACTIVE = "active"
    DORMANT = "dormant"


class LeadStage(StrEnum):
    NEW = "new"
    QUALIFIED = "qualified"
    CONTACTED = "contacted"
    ONBOARDING = "onboarding"
    CONVERTED = "converted"
    LOST = "lost"


class ConversationChannel(StrEnum):
    APP = "app"
    WHATSAPP = "whatsapp"
    WEB = "web"
    CONSOLE = "console"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class AgentTriggerType(StrEnum):
    CHAT = "chat"
    EVENT = "event"
    SCHEDULED = "scheduled"  # proactive periodic sweep (app.workers.scheduler)


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentStepKind(StrEnum):
    LLM = "llm"
    TOOL = "tool"
    GUARDRAIL = "guardrail"


class ProposalKind(StrEnum):
    PRODUCT_OFFER = "product_offer"
    EMAIL = "email"
    NUDGE = "nudge"
    WALKTHROUGH = "walkthrough"
    ACTION = "action"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


class NudgeStatus(StrEnum):
    SENT = "sent"
    SEEN = "seen"
    ACTED = "acted"
    DISMISSED = "dismissed"


class LifeEventType(StrEnum):
    JOB_CHANGE = "job_change"
    NEW_CHILD = "new_child"
    HOME_INTENT = "home_intent"
    BONUS = "bonus"
    SALARY_HIKE = "salary_hike"
    MARRIAGE = "marriage"
    RELOCATION = "relocation"
    TRAVEL = "travel"


class LifeEventStatus(StrEnum):
    DETECTED = "detected"
    CONFIRMED = "confirmed"
    ACTIONED = "actioned"
    DISMISSED = "dismissed"


class NotificationKind(StrEnum):
    """A customer-facing notification's category (drives its icon and copy)."""

    OFFER = "offer"
    LIFE_EVENT = "life_event"
    ACCOUNT = "account"
    NUDGE = "nudge"
    SYSTEM = "system"


class GoalStatus(StrEnum):
    """Lifecycle of a customer savings goal."""

    ACTIVE = "active"
    ACHIEVED = "achieved"
    ARCHIVED = "archived"


class MemoryKind(StrEnum):
    EPISODIC = "episodic"
    FACT = "fact"
    PREFERENCE = "preference"


class LlmTier(StrEnum):
    FAST = "fast"
    SMART = "smart"


class CredentialTransport(StrEnum):
    """WebAuthn credential kind marker (broad; details live in JSON)."""

    PLATFORM = "platform"
    CROSS_PLATFORM = "cross_platform"
