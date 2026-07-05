"""Runtime-overridable operational settings, backed by Redis.

A SMALL, FIXED allowlist of operational knobs can be overridden at runtime -
without a process restart or a prod ``.env`` edit + redeploy (see
``infra/DEPLOY.md``) - by writing a value to a Redis key. Every consuming code
path reads the override first and falls back to the static pydantic
:class:`~app.core.config.Settings` value when no override is set.

Why an allowlist, and why only these keys
-----------------------------------------
Almost all of :class:`Settings` is boot-time infrastructure (database URLs, the
JWT secret, provider API keys, CORS origins, cookie domains) that is unsafe to
mutate on a live process: a typo would take the app down, and secrets must never
be settable from an API. Runtime overrides are therefore deliberately confined to
a hand-picked set of *operational* switches that (a) are safe to flip on a running
system, (b) have a well-defined validated range/enum, and (c) deliver real ops
value when changed without a restart. Concretely, exactly these five keys:

- ``scheduler_enabled`` (bool) - master switch for the proactive sweep loop.
- ``standing_instructions_enabled`` (bool) - kill switch for recurring auto-transfers.
- ``llm_daily_budget_usd`` (float, clamped to 0..10) - the daily spend ceiling the
  event pipeline throttles itself against.
- ``openai_model_smart`` (enum ``gpt-4o-mini`` | ``gpt-4o``) - the smart-tier model.
- ``openai_model_fast`` (enum ``gpt-4o-mini``) - the fast-tier model.

Anything not in :data:`OVERRIDABLE_KEYS` can never be overridden: both
:func:`get_override` and the admin API reject unknown keys.

Defensive by construction
-------------------------
A Redis outage (or any client error) while *reading* an override is swallowed and
treated as "no override", so the static config value is used and nothing crashes.
Overrides are read live on each call (no in-process cache) so a change takes
effect immediately across every worker sharing the Redis - which is the entire
point (flip a switch in the console, the scheduler honours it on its next tick
with no redeploy).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, get_args

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger(__name__)

RuntimeSettingKey = Literal[
    "scheduler_enabled",
    "standing_instructions_enabled",
    "llm_daily_budget_usd",
    "openai_model_smart",
    "openai_model_fast",
]
"""The complete, fixed allowlist of runtime-overridable keys (a ``Literal`` so the
admin API's request schema rejects anything else at validation time)."""

SettingType = Literal["bool", "float", "enum"]

_REDIS_PREFIX = "runtime_settings"
"""Namespace for override keys (``runtime_settings:{key}``)."""

# Budget is clamped, never allowed above this - a hard rail so a fat-fingered
# console entry (or a compromised staff session) can never uncork spend.
_BUDGET_MIN = 0.0
_BUDGET_MAX = 10.0


@dataclass(frozen=True, slots=True)
class OverrideSpec:
    """How one allowlisted key is validated, stored, and defaulted."""

    key: RuntimeSettingKey
    type: SettingType
    settings_attr: str
    """Attribute on :class:`Settings` holding the static (default) value."""
    enum_values: tuple[str, ...] = ()
    min_value: float = _BUDGET_MIN
    max_value: float = _BUDGET_MAX


OVERRIDE_SPECS: dict[str, OverrideSpec] = {
    "scheduler_enabled": OverrideSpec(
        "scheduler_enabled", "bool", "scheduler_enabled"
    ),
    "standing_instructions_enabled": OverrideSpec(
        "standing_instructions_enabled", "bool", "standing_instructions_enabled"
    ),
    "llm_daily_budget_usd": OverrideSpec(
        "llm_daily_budget_usd",
        "float",
        "llm_daily_budget_usd",
        min_value=_BUDGET_MIN,
        max_value=_BUDGET_MAX,
    ),
    "openai_model_smart": OverrideSpec(
        "openai_model_smart",
        "enum",
        "openai_model_smart",
        enum_values=("gpt-4o-mini", "gpt-4o"),
    ),
    "openai_model_fast": OverrideSpec(
        "openai_model_fast",
        "enum",
        "openai_model_fast",
        enum_values=("gpt-4o-mini",),
    ),
}

OVERRIDABLE_KEYS: tuple[str, ...] = get_args(RuntimeSettingKey)
"""The allowlist as a tuple, ordered as declared in :data:`RuntimeSettingKey`."""

# Fail fast if the two sources of truth ever drift.
assert set(OVERRIDABLE_KEYS) == set(OVERRIDE_SPECS), "runtime settings allowlist drift"

SettingValue = bool | float | str


def is_overridable(key: str) -> bool:
    """Whether ``key`` is in the fixed override allowlist."""
    return key in OVERRIDE_SPECS


def _spec(key: str) -> OverrideSpec:
    spec = OVERRIDE_SPECS.get(key)
    if spec is None:
        raise ValueError(f"{key!r} is not an overridable runtime setting")
    return spec


def _redis_key(key: str) -> str:
    return f"{_REDIS_PREFIX}:{key}"


# ---------------------------------------------------------------------------
# validation + (de)serialization
# ---------------------------------------------------------------------------


def validate_value(key: str, value: object) -> SettingValue:
    """Validate/coerce ``value`` for ``key``, returning the typed value to store.

    Raises :class:`ValueError` for an unknown key, a wrong-typed value, or an
    out-of-enum choice. A ``float`` value is *clamped* into ``[min, max]`` rather
    than rejected (so a budget of 999 safely becomes the 10.0 ceiling), but a
    non-numeric budget is rejected.
    """
    spec = _spec(key)
    if spec.type == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        raise ValueError(f"{key} expects a boolean value")
    if spec.type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError(f"{key} expects a number")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} expects a number") from exc
        if not math.isfinite(number):
            raise ValueError(f"{key} must be a finite number")
        return min(max(number, spec.min_value), spec.max_value)
    # enum
    if not isinstance(value, str) or value not in spec.enum_values:
        allowed = ", ".join(spec.enum_values)
        raise ValueError(f"{key} must be one of: {allowed}")
    return value


def _serialize(spec: OverrideSpec, value: SettingValue) -> str:
    if spec.type == "bool":
        return "true" if value else "false"
    return str(value)


def _deserialize(spec: OverrideSpec, raw: str) -> SettingValue | None:
    """Parse a stored override back to its typed value, or None if malformed
    (defensive: a corrupt/legacy value falls back to the static default)."""
    if spec.type == "bool":
        if raw not in ("true", "false"):
            return None
        return raw == "true"
    if spec.type == "float":
        try:
            number = float(raw)
        except ValueError:
            return None
        if not math.isfinite(number):
            return None
        return number
    # enum: reject anything no longer in the allowlist
    return raw if raw in spec.enum_values else None


# ---------------------------------------------------------------------------
# read / write / clear
# ---------------------------------------------------------------------------


async def get_override(key: str) -> SettingValue | None:
    """Return the Redis override for ``key``, or ``None`` when unset.

    Best-effort: an unknown key, an unset key, a malformed stored value, or any
    Redis error all return ``None`` so the caller falls back to static config.
    """
    spec = OVERRIDE_SPECS.get(key)
    if spec is None:
        return None
    try:
        raw = await get_redis().get(_redis_key(key))
    except Exception as exc:  # pragma: no cover - defensive (Redis down)
        logger.warning("runtime_settings_read_failed", key=key, error=str(exc))
        return None
    if raw is None:
        return None
    return _deserialize(spec, str(raw))


async def set_override(key: str, value: object) -> SettingValue:
    """Validate ``value`` for ``key`` and persist it as the override.

    Returns the coerced (validated, clamped) value that was stored. Raises
    :class:`ValueError` on an unknown key or invalid value (the admin API maps
    that to 422). A Redis write failure propagates (a write that silently no-ops
    would be worse than a surfaced error).
    """
    spec = _spec(key)
    coerced = validate_value(key, value)
    await get_redis().set(_redis_key(key), _serialize(spec, coerced))
    return coerced


async def clear_override(key: str) -> None:
    """Remove ``key``'s override so the effective value reverts to static config."""
    _spec(key)  # validate key is in the allowlist
    await get_redis().delete(_redis_key(key))


def default_value(key: str) -> SettingValue:
    """The static (pre-override) value for ``key`` from :class:`Settings`."""
    spec = _spec(key)
    raw = getattr(get_settings(), spec.settings_attr)
    if spec.type == "bool":
        return bool(raw)
    if spec.type == "float":
        return float(raw)
    return str(raw)


@dataclass(frozen=True, slots=True)
class SettingView:
    """The effective state of one setting, for the admin GET response."""

    key: str
    value: SettingValue
    default: SettingValue
    source: Literal["override", "default"]
    type: SettingType
    options: tuple[str, ...] | None
    min: float | None
    max: float | None


async def describe(key: str) -> SettingView:
    """Effective value + provenance + validation metadata for one key."""
    spec = _spec(key)
    override = await get_override(key)
    default = default_value(key)
    value: SettingValue = override if override is not None else default
    return SettingView(
        key=key,
        value=value,
        default=default,
        source="override" if override is not None else "default",
        type=spec.type,
        options=spec.enum_values or None,
        min=spec.min_value if spec.type == "float" else None,
        max=spec.max_value if spec.type == "float" else None,
    )


async def describe_all() -> list[SettingView]:
    """Effective state of every overridable key, in allowlist order."""
    return [await describe(key) for key in OVERRIDABLE_KEYS]


# ---------------------------------------------------------------------------
# effective-value helpers for consuming code (override first, static fallback)
# ---------------------------------------------------------------------------


async def _effective_bool(key: str) -> bool:
    override = await get_override(key)
    if override is not None:
        return bool(override)
    return bool(default_value(key))


async def scheduler_enabled() -> bool:
    """Effective master switch for the proactive sweep loop."""
    return await _effective_bool("scheduler_enabled")


async def standing_instructions_enabled() -> bool:
    """Effective kill switch for the standing-instruction (auto-transfer) pass."""
    return await _effective_bool("standing_instructions_enabled")


async def effective_daily_budget_usd() -> Decimal:
    """Effective daily LLM spend ceiling (override first, static config fallback)."""
    override = await get_override("llm_daily_budget_usd")
    if override is not None:
        return Decimal(str(override))
    return Decimal(str(get_settings().llm_daily_budget_usd))


async def openai_model_override(tier: str) -> str | None:
    """The OpenAI model override for a router tier (``fast``/``smart``), or None.

    Returns only an *override* (never the static default) so the router can leave
    its statically-built provider chain untouched when nothing is overridden.
    """
    key = "openai_model_fast" if tier == "fast" else "openai_model_smart"
    override = await get_override(key)
    return str(override) if override is not None else None
