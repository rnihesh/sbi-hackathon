"""Guardrails: PII redaction, policy/compliance engine, and hash-chained audit.

Three independent, deterministic layers that wrap every agent turn:

1. :class:`PIIRedactor` — strips PAN / Aadhaar / phone / email / account numbers
   to typed placeholders (``<PAN_1>``) *before* any text reaches an LLM, keeping
   a reversible map so tool arguments can be restored to real values.
2. :class:`PolicyEngine` — appends mandated disclosures, blocks disallowed claims
   ("guaranteed returns", "zero risk"), and gates investment suggestions behind a
   suitability check (income + risk on file).
3. :class:`AuditTrail` — writes tamper-evident, hash-chained ``audit_logs`` rows;
   appends are serialised with a Postgres advisory lock so the chain stays linear
   under concurrency, with a retry fallback on conflict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.audit import GENESIS_HASH, AuditLog, chain_hash

# ===========================================================================
# 1. PII redaction
# ===========================================================================

# (placeholder_type, compiled pattern). Order matters: longer/structured
# identifiers are consumed first so their digits can't be re-matched by a
# broader numeric rule (e.g. Aadhaar before phone before account number).
_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("AADHAAR", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    ("PHONE", re.compile(r"(?:\+91[\-\s]?|0)?[6-9]\d{9}\b")),
    ("ACCOUNT", re.compile(r"\b\d{9,18}\b")),
]


@dataclass(slots=True)
class RedactionResult:
    """Redacted text plus a reversible placeholder→original map."""

    text: str
    mapping: dict[str, str] = field(default_factory=dict)

    def restore(self, text: str) -> str:
        """Replace any placeholders in ``text`` with their original values."""
        out = text
        # Replace longer placeholders first (``<PAN_11>`` before ``<PAN_1>``).
        for placeholder in sorted(self.mapping, key=len, reverse=True):
            out = out.replace(placeholder, self.mapping[placeholder])
        return out

    def restore_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Restore placeholders inside string values of a tool-args dict."""
        return {
            k: (self.restore(v) if isinstance(v, str) else v) for k, v in args.items()
        }


class PIIRedactor:
    """Regex PII redactor with typed, reversible placeholders."""

    def redact(self, text: str) -> RedactionResult:
        mapping: dict[str, str] = {}
        reverse: dict[tuple[str, str], str] = {}  # (type, original) -> placeholder
        counters: dict[str, int] = {}
        result = text

        for kind, pattern in _PII_PATTERNS:
            def _sub(match: re.Match[str], kind: str = kind) -> str:
                original = match.group(0)
                key = (kind, original)
                if key in reverse:
                    return reverse[key]
                counters[kind] = counters.get(kind, 0) + 1
                placeholder = f"<{kind}_{counters[kind]}>"
                reverse[key] = placeholder
                mapping[placeholder] = original
                return placeholder

            result = pattern.sub(_sub, result)

        return RedactionResult(text=result, mapping=mapping)

    def redact_text(self, text: str) -> str:
        """Convenience: return just the redacted string."""
        return self.redact(text).text


# ===========================================================================
# 2. Policy / compliance engine
# ===========================================================================

_MF_DISCLOSURE = (
    "Mutual fund investments are subject to market risks. "
    "Read all scheme related documents carefully before investing."
)
_INSURANCE_DISCLOSURE = (
    "Insurance is the subject matter of solicitation. "
    "Please read the policy terms and conditions carefully."
)

_INVESTMENT_KEYWORDS = (
    "mutual fund", "mutual funds", " sip", "sip ", "equity", "market-linked",
    "market linked", "elss", "portfolio", "wealth", "invest",
)
_INSURANCE_KEYWORDS = ("insurance", "term plan", "life cover", "policy premium", "accident cover")

# Disallowed marketing claims → compliant rewrite.
_BLOCKED_CLAIMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"guaranteed\s+returns?", re.I), "potential returns (subject to market risk)"),
    (re.compile(r"assured\s+returns?", re.I), "indicative returns (not assured)"),
    (re.compile(r"guaranteed\s+profits?", re.I), "possible gains (not guaranteed)"),
    (re.compile(r"zero[\s\-]*risk", re.I), "lower-risk"),
    (re.compile(r"risk[\s\-]*free", re.I), "lower-risk"),
    (re.compile(r"\bno\s+risk\b", re.I), "reduced risk"),
    (re.compile(r"100%\s*safe", re.I), "designed to be low-risk"),
    (re.compile(r"\bdouble\s+your\s+money\b", re.I), "grow your money over time"),
]

# Phrases that indicate an active investment *suggestion* (triggers suitability).
_SUGGESTION_RE = re.compile(
    r"\b(you should|i (?:recommend|suggest)|recommend|suggest|consider|start|open|invest in|"
    r"go for|opt for)\b",
    re.I,
)


@dataclass(slots=True)
class Verdict:
    """Result of a policy check. ``fixed_text`` is always safe to send."""

    allowed: bool
    fixed_text: str
    violations: list[str] = field(default_factory=list)
    disclosures_added: list[str] = field(default_factory=list)


class PolicyEngine:
    """Deterministic compliance rules over outbound agent text."""

    def _mentions(self, text_l: str, keywords: tuple[str, ...]) -> bool:
        return any(k in text_l for k in keywords)

    def check(
        self,
        text: str,
        *,
        profile: dict[str, Any] | None = None,
        suggests_investment: bool | None = None,
    ) -> Verdict:
        """Validate/repair outbound text against policy.

        ``profile`` is used for the suitability gate (needs ``income`` and a risk
        answer to permit an investment suggestion). ``suggests_investment`` can be
        passed explicitly; otherwise it is inferred from the text.
        """
        fixed = text
        violations: list[str] = []
        disclosures: list[str] = []
        text_l = text.lower()

        # -- blocked claims -> rewrite --
        for pattern, replacement in _BLOCKED_CLAIMS:
            if pattern.search(fixed):
                violations.append(f"blocked_claim:{pattern.pattern}")
                fixed = pattern.sub(replacement, fixed)

        mentions_investment = self._mentions(text_l, _INVESTMENT_KEYWORDS)
        mentions_insurance = self._mentions(text_l, _INSURANCE_KEYWORDS)

        # -- suitability gate --
        if suggests_investment is None:
            suggests_investment = mentions_investment and bool(_SUGGESTION_RE.search(text))
        if suggests_investment:
            has_income = bool(profile and profile.get("income"))
            has_risk = bool(profile and profile.get("risk"))
            if not (has_income and has_risk):
                missing = []
                if not has_income:
                    missing.append("income")
                if not has_risk:
                    missing.append("risk appetite")
                violations.append(f"suitability_gate:missing_{'_'.join(missing)}")
                fixed = (
                    fixed.rstrip()
                    + "\n\nBefore I can recommend a specific investment, I'll need to "
                    f"complete a quick suitability check ({' and '.join(missing)}). "
                    "Shall we do that now?"
                )

        # -- mandated disclosures (idempotent) --
        if mentions_investment and _MF_DISCLOSURE not in fixed:
            fixed = fixed.rstrip() + "\n\n" + _MF_DISCLOSURE
            disclosures.append("mutual_fund")
        if mentions_insurance and _INSURANCE_DISCLOSURE not in fixed:
            fixed = fixed.rstrip() + "\n\n" + _INSURANCE_DISCLOSURE
            disclosures.append("insurance")

        return Verdict(
            allowed=not violations,
            fixed_text=fixed,
            violations=violations,
            disclosures_added=disclosures,
        )


# ===========================================================================
# 3. Hash-chained audit trail
# ===========================================================================

# Fixed advisory-lock key for the audit chain (any stable app-wide constant).
_AUDIT_LOCK_KEY = 6072925063
_MAX_APPEND_RETRIES = 5


class AuditTrail:
    """Append-only, tamper-evident audit log with a linear hash chain."""

    async def _tail_hash(self, session: AsyncSession) -> str:
        """Return the hash of the current chain tail, or GENESIS if empty.

        The tail is the row whose ``hash`` is not referenced by any other row's
        ``prev_hash``. Ordering-independent, so it is correct regardless of ``ts``
        ties. Under the advisory lock there is always exactly one tail.
        """
        outer = aliased(AuditLog, name="outer_al")
        inner = aliased(AuditLog, name="inner_al")
        stmt = sa.select(outer.hash).where(
            ~sa.select(inner.id).where(inner.prev_hash == outer.hash).exists()
        )
        tails = list((await session.scalars(stmt)).all())
        if not tails:
            return GENESIS_HASH
        # If (transiently) more than one tail exists, chain from the most recent
        # by timestamp — the advisory lock makes this the common, single-tail case.
        if len(tails) == 1:
            return tails[0]
        latest = await session.scalar(
            sa.select(AuditLog.hash)
            .where(AuditLog.hash.in_(tails))
            .order_by(AuditLog.ts.desc())
            .limit(1)
        )
        return latest or GENESIS_HASH

    async def record(
        self,
        session: AsyncSession,
        actor: str,
        action: str,
        entity: str,
        entity_id: str | None,
        payload: dict[str, Any],
    ) -> AuditLog:
        """Append an audit record, chaining its hash from the current tail.

        Serialised via a Postgres transaction-level advisory lock so concurrent
        appends form a single linear chain; retries on the rare integrity/ordering
        conflict.
        """
        last_error: Exception | None = None
        for _ in range(_MAX_APPEND_RETRIES):
            try:
                await session.execute(
                    sa.text("SELECT pg_advisory_xact_lock(:k)"), {"k": _AUDIT_LOCK_KEY}
                )
                prev_hash = await self._tail_hash(session)
                record = {
                    "actor": actor,
                    "action": action,
                    "entity": entity,
                    "entity_id": entity_id,
                    "payload": payload,
                }
                digest = chain_hash(prev_hash, record)
                row = AuditLog(
                    actor=actor,
                    action=action,
                    entity=entity,
                    entity_id=entity_id,
                    payload=payload,
                    prev_hash=prev_hash,
                    hash=digest,
                )
                session.add(row)
                await session.flush()
                return row
            except IntegrityError as exc:  # unique(hash) collision -> retry
                last_error = exc
                await session.rollback()
                continue
        raise RuntimeError(f"audit append failed after retries: {last_error}")

    @staticmethod
    async def verify(session: AsyncSession) -> bool:
        """Recompute the chain and confirm every link (tamper detection)."""
        rows = list(
            (await session.scalars(sa.select(AuditLog).order_by(AuditLog.ts, AuditLog.id))).all()
        )
        # Rebuild the linked order from prev_hash pointers.
        by_prev: dict[str, AuditLog] = {r.prev_hash: r for r in rows}
        if not rows:
            return True
        ordered: list[AuditLog] = []
        cursor = GENESIS_HASH
        seen: set[str] = set()
        while cursor in by_prev and by_prev[cursor].hash not in seen:
            node = by_prev[cursor]
            ordered.append(node)
            seen.add(node.hash)
            cursor = node.hash
        if len(ordered) != len(rows):
            return False  # broken / forked chain
        prev = GENESIS_HASH
        for node in ordered:
            record = {
                "actor": node.actor,
                "action": node.action,
                "entity": node.entity,
                "entity_id": node.entity_id,
                "payload": node.payload,
            }
            if node.prev_hash != prev or node.hash != chain_hash(prev, record):
                return False
            prev = node.hash
        return True
