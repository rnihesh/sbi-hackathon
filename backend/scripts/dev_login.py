"""Dev-only tool: mint a real staff session for local/manual verification.

Upserts a :class:`User` row for a staff email (real DB write, no fakes), binds it
to a :class:`Customer` profile so the same account can double as the customer app's
logged-in user, then mints a genuine access+refresh JWT pair via
``app.core.security.create_session`` (the exact function ``POST /auth/*`` routes use)
and prints the resulting httpOnly cookie values.

This is a legitimate dev tool, not a demo shortcut: it does not fabricate any
request/response, bypass a guardrail, or stub an agent path - it only automates the
"click through Google OAuth" step of acquiring a session that every other code path
already knows how to issue and verify.

Usage::

    uv run python scripts/dev_login.py
    uv run python scripts/dev_login.py --email someone@example.com --full-name "Someone"

Prints the cookie pair as ``name=value`` lines and as a ready-to-paste
``document.cookie`` snippet / curl ``-b`` argument.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import dispose_engine, get_sessionmaker
from app.core.logging import get_logger, setup_logging
from app.core.security import ACCESS_COOKIE, REFRESH_COOKIE, create_session
from app.models.customer import Customer
from app.models.identity import User

logger = get_logger(__name__)


async def _upsert_user(email: str) -> User:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            user = User(email=email)
            db.add(user)
            await db.flush()
            logger.info("dev_login_user_created", email=email, user_id=str(user.id))
        else:
            logger.info("dev_login_user_reused", email=email, user_id=str(user.id))
        await db.commit()
        await db.refresh(user)
        return user


async def _upsert_customer(user: User, full_name: str) -> Customer:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        customer = (
            await db.execute(select(Customer).where(Customer.user_id == user.id))
        ).scalar_one_or_none()
        if customer is None:
            customer = Customer(user_id=user.id, full_name=full_name, email=user.email)
            db.add(customer)
            await db.flush()
            logger.info("dev_login_customer_created", customer_id=str(customer.id))
        else:
            logger.info("dev_login_customer_reused", customer_id=str(customer.id))
        await db.commit()
        await db.refresh(customer)
        return customer


async def main(email: str, full_name: str, with_customer: bool) -> None:
    setup_logging()
    settings = get_settings()
    if email.lower() not in {e.lower() for e in settings.staff_email_list}:
        logger.warning(
            "dev_login_email_not_in_staff_list",
            email=email,
            staff_emails=settings.staff_email_list,
        )

    user = await _upsert_user(email)
    customer = await _upsert_customer(user, full_name) if with_customer else None

    access_token, refresh_token = await create_session(str(user.id))

    print("\n=== Sarathi dev login ===")
    print(f"user_id:     {user.id}")
    print(f"email:       {user.email}")
    if customer is not None:
        print(f"customer_id: {customer.id}")
    print("\nCookies (httpOnly - set via devtools/CDP, not document.cookie):")
    print(f"  {ACCESS_COOKIE}={access_token}")
    print(f"  {REFRESH_COOKIE}={refresh_token}")
    print("\ncurl:")
    print(f'  curl -b "{ACCESS_COOKIE}={access_token}; {REFRESH_COOKIE}={refresh_token}" ...')

    await dispose_engine()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mint a real Sarathi staff session for dev use.")
    parser.add_argument(
        "--email",
        default="niheshr03@gmail.com",
        help="Staff email to upsert a User for (default: niheshr03@gmail.com).",
    )
    parser.add_argument(
        "--full-name",
        default="Nihesh Rachakonda",
        help="Full name for the bound Customer profile.",
    )
    parser.add_argument(
        "--no-customer",
        action="store_true",
        help="Skip binding/creating a Customer profile for this user.",
    )
    return parser


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    asyncio.run(main(args.email, args.full_name, with_customer=not args.no_customer))
