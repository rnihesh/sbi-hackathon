"""Auth API: Google OAuth, WebAuthn passkeys, email OTP, and session lifecycle.

All routes here are the exact Wave 3 frontend contract — see the docstrings on each
handler for request/response shapes. Every route that establishes or refreshes a
session sets the ``sarathi_access``/``sarathi_refresh`` httpOnly cookies via
``app.core.security``; none of them return the tokens in the JSON body.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.jose import JsonWebKey
from authlib.jose import jwt as jose_jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import (
    bytes_to_base64url,
    parse_authentication_credential_json,
    parse_client_data_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.config import get_settings
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.security import (
    SessionError,
    clear_session_cookies,
    create_session,
    get_current_user,
    revoke_session_from_refresh_token,
    rotate_session,
    set_session_cookies,
)
from app.models.customer import Customer
from app.models.enums import CredentialTransport
from app.models.identity import Credential, OtpCode, User
from app.schemas.auth import (
    CustomerOut,
    MeResponse,
    MessageResponse,
    OtpSendRequest,
    OtpVerifyRequest,
    PasskeyLoginBeginRequest,
    PasskeyLoginCompleteRequest,
    PasskeyRegisterCompleteRequest,
    PasskeyRegisterCompleteResponse,
    UserOut,
)
from app.services.email import EmailNotConfigured, send_templated

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
# `/me` intentionally lives outside the `/auth` prefix; mounted separately in
# `app/api/v1/__init__.py`.
me_router = APIRouter(tags=["auth"])


# ========================================================================================
# Shared helpers
# ========================================================================================


def _placeholder_name(email: str) -> str:
    """Best-effort display name when a flow (OTP, passkey) never collects one."""
    local = email.split("@", 1)[0]
    cleaned = local.replace(".", " ").replace("_", " ").replace("-", " ").strip()
    return cleaned.title() if cleaned else "Sarathi Customer"


async def _get_or_create_user_by_email(db: AsyncSession, email: str) -> tuple[User, bool]:
    """Fetch the user with ``email``, creating one if none exists.

    Returns ``(user, created)``. Flushes so a newly created user's server-generated
    ``created_at`` (and client-generated ``id``, which SQLAlchemy also only assigns at
    flush time) are populated before the caller uses them.
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is not None:
        return user, False
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user, True


async def _upsert_user_from_google(db: AsyncSession, claims: dict[str, Any]) -> tuple[User, bool]:
    """Upsert a :class:`User` from verified Google id_token claims.

    Match order: existing ``google_sub`` first, then fall back to an existing user with
    the same verified email (linking the Google identity to it), else create new.
    """
    google_sub = str(claims["sub"])
    email = str(claims["email"]).lower()

    result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()
    if user is not None:
        return user, False

    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.google_sub = google_sub
        await db.flush()
        return existing, False

    user = User(email=email, google_sub=google_sub)
    db.add(user)
    await db.flush()
    return user, True


async def _ensure_customer_for_user(
    db: AsyncSession, user: User, *, full_name: str | None, email: str | None
) -> Customer:
    """Fetch or create the minimal :class:`Customer` profile backing ``user``."""
    result = await db.execute(select(Customer).where(Customer.user_id == user.id))
    customer = result.scalar_one_or_none()
    if customer is not None:
        return customer
    customer = Customer(
        user_id=user.id,
        full_name=full_name or _placeholder_name(user.email),
        email=email or user.email,
    )
    db.add(customer)
    await db.flush()
    return customer


async def _send_welcome_best_effort(user: User, customer: Customer) -> None:
    """Send the post-onboarding welcome email; never let this break the auth flow."""
    settings = get_settings()
    try:
        await send_templated(
            user.email,
            "welcome",
            {"full_name": customer.full_name, "cta_url": f"{settings.frontend_url}/app/home"},
        )
    except EmailNotConfigured:
        logger.warning("welcome_email_skipped_no_creds", user_id=str(user.id))
    except Exception:
        logger.exception("welcome_email_send_failed", user_id=str(user.id))


def _me_response(user: User, customer: Customer | None) -> MeResponse:
    return MeResponse(
        user=UserOut.model_validate(user),
        customer=CustomerOut.model_validate(customer) if customer is not None else None,
    )


# ========================================================================================
# Google OAuth (authlib, authorization-code, server-side)
# ========================================================================================

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]

OAUTH_STATE_COOKIE = "sarathi_oauth_state"
OAUTH_STATE_MAX_AGE_SECONDS = 60 * 10


def _oauth_state_serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    # Domain-separated from JWT signing via a dedicated salt (itsdangerous derives an
    # independent HMAC key per salt from the same master secret).
    return URLSafeTimedSerializer(settings.jwt_secret, salt="oauth-state")


def _google_redirect_uri() -> str:
    settings = get_settings()
    return f"{settings.backend_url}/api/v1/auth/google/callback"


async def _fetch_google_token(code: str) -> dict[str, Any]:
    """Exchange an authorization ``code`` for tokens at Google's token endpoint."""
    settings = get_settings()
    async with AsyncOAuth2Client(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=_google_redirect_uri(),
    ) as client:
        token: dict[str, Any] = await client.fetch_token(
            GOOGLE_TOKEN_ENDPOINT, code=code, grant_type="authorization_code"
        )
    return token


async def _fetch_google_jwks() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(GOOGLE_JWKS_URI)
        resp.raise_for_status()
        jwks: dict[str, Any] = resp.json()
        return jwks


async def _verify_google_id_token(id_token: str) -> dict[str, Any]:
    """Verify ``id_token``'s signature (against Google's live JWKS) and claims."""
    settings = get_settings()
    jwks = await _fetch_google_jwks()
    key_set = JsonWebKey.import_key_set(jwks)
    claims = jose_jwt.decode(
        id_token,
        key_set,
        claims_options={
            "iss": {"values": GOOGLE_ISSUERS},
            "aud": {"values": [settings.google_client_id]},
        },
    )
    claims.validate()
    if not claims.get("email_verified"):
        raise HTTPException(status_code=400, detail="Google account email is not verified")
    return dict(claims)


@router.get("/google", summary="Redirect to Google's OAuth consent screen")
async def google_login() -> Response:
    """``GET /api/v1/auth/google`` → ``302`` redirect to Google.

    Sets a short-lived, signed, httpOnly ``sarathi_oauth_state`` cookie carrying the
    CSRF nonce echoed back as Google's ``state`` query param.
    """
    settings = get_settings()
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")

    nonce = secrets.token_urlsafe(24)
    async with AsyncOAuth2Client(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=_google_redirect_uri(),
        scope="openid email profile",
    ) as client:
        url, _state = client.create_authorization_url(GOOGLE_AUTH_ENDPOINT, state=nonce)

    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    signed_state = _oauth_state_serializer().dumps(nonce)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        signed_state,
        max_age=OAUTH_STATE_MAX_AGE_SECONDS,
        httponly=True,
        secure=not settings.is_dev,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/google/callback", summary="Google OAuth callback")
async def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    sarathi_oauth_state: Annotated[str | None, Cookie()] = None,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """``GET /api/v1/auth/google/callback`` → ``302`` redirect to ``{FRONTEND_URL}/app/home``.

    Sets session cookies on success. Upserts the :class:`User` (by ``google_sub``,
    falling back to a verified-email match) and creates a minimal :class:`Customer`
    profile if none exists yet.
    """
    settings = get_settings()
    if error or not code or not state:
        raise HTTPException(
            status_code=400, detail=f"Google OAuth error: {error or 'missing code/state'}"
        )
    if not sarathi_oauth_state:
        raise HTTPException(status_code=400, detail="Missing OAuth state cookie")

    try:
        expected_nonce = _oauth_state_serializer().loads(
            sarathi_oauth_state, max_age=OAUTH_STATE_MAX_AGE_SECONDS
        )
    except (BadSignature, SignatureExpired) as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state") from exc

    if not hmac.compare_digest(str(expected_nonce), state):
        raise HTTPException(status_code=400, detail="OAuth state mismatch")

    token = await _fetch_google_token(code)
    id_token = token.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="Google did not return an id_token")

    try:
        claims = await _verify_google_id_token(id_token)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Google id_token: {exc}") from exc

    user, created = await _upsert_user_from_google(db, claims)
    customer = await _ensure_customer_for_user(
        db,
        user,
        full_name=claims.get("name"),
        email=str(claims.get("email", user.email)).lower(),
    )

    access_token, refresh_token = await create_session(str(user.id))

    response = RedirectResponse(
        f"{settings.frontend_url}/app/home", status_code=status.HTTP_302_FOUND
    )
    set_session_cookies(response, access_token=access_token, refresh_token=refresh_token)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")

    if created:
        await _send_welcome_best_effort(user, customer)

    return response


# ========================================================================================
# Passkeys (WebAuthn)
# ========================================================================================


def _reg_challenge_key(user_id: uuid.UUID) -> str:
    return f"webauthn:reg:{user_id}"


def _auth_challenge_key(challenge: bytes) -> str:
    return f"webauthn:authch:{challenge.hex()}"


def _infer_transport(transports: list[AuthenticatorTransport] | None) -> CredentialTransport:
    """Collapse WebAuthn's granular transport list into our coarse platform marker."""
    if transports and AuthenticatorTransport.INTERNAL in transports:
        return CredentialTransport.PLATFORM
    if transports:
        return CredentialTransport.CROSS_PLATFORM
    return CredentialTransport.PLATFORM


def _label_from_user_agent(user_agent: str | None) -> str:
    """Small heuristic UA parse for a human-friendly credential label (e.g. "Chrome on Mac")."""
    if not user_agent:
        return "Passkey"

    if "iPhone" in user_agent:
        device = "iPhone"
    elif "iPad" in user_agent:
        device = "iPad"
    elif "Android" in user_agent:
        device = "Android"
    elif "Macintosh" in user_agent or "Mac OS" in user_agent:
        device = "Mac"
    elif "Windows" in user_agent:
        device = "Windows"
    elif "Linux" in user_agent:
        device = "Linux"
    else:
        device = "device"

    if "Edg/" in user_agent:
        browser = "Edge"
    elif "CriOS" in user_agent or ("Chrome/" in user_agent and "Chromium" not in user_agent):
        browser = "Chrome"
    elif "Firefox/" in user_agent:
        browser = "Firefox"
    elif "Safari/" in user_agent and "Chrome/" not in user_agent:
        browser = "Safari"
    else:
        browser = "Passkey"

    return f"{browser} on {device}"


@router.post("/passkey/register/begin", summary="Begin passkey registration (auth required)")
async def passkey_register_begin(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Returns a raw ``PublicKeyCredentialCreationOptions`` JSON object.

    Pass the parsed JSON directly to `@simplewebauthn/browser`'s `startRegistration()`.
    """
    settings = get_settings()
    result = await db.execute(select(Credential).where(Credential.user_id == user.id))
    existing = result.scalars().all()

    customer_result = await db.execute(select(Customer).where(Customer.user_id == user.id))
    customer = customer_result.scalar_one_or_none()
    display_name = customer.full_name if customer else user.email

    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name="Sarathi",
        user_name=user.email,
        user_id=user.id.bytes,
        user_display_name=display_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=c.credential_id) for c in existing
        ],
    )

    redis = get_redis()
    await redis.set(
        _reg_challenge_key(user.id),
        bytes_to_base64url(options.challenge),
        ex=settings.webauthn_challenge_ttl_seconds,
    )
    return Response(content=options_to_json(options), media_type="application/json")


@router.post(
    "/passkey/register/complete",
    response_model=PasskeyRegisterCompleteResponse,
    summary="Complete passkey registration (auth required)",
)
async def passkey_register_complete(
    payload: PasskeyRegisterCompleteRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> PasskeyRegisterCompleteResponse:
    """Body: ``{"credential": <RegistrationResponseJSON>, "label"?: str}``."""
    settings = get_settings()
    redis = get_redis()
    key = _reg_challenge_key(user.id)
    stored_raw = await redis.get(key)
    if not stored_raw:
        raise HTTPException(
            status_code=400, detail="No pending passkey registration (begin again)"
        )
    await redis.delete(key)
    stored = stored_raw.decode() if isinstance(stored_raw, bytes) else stored_raw

    try:
        parsed = parse_registration_credential_json(payload.credential)
        verification = verify_registration_response(
            credential=parsed,
            expected_challenge=base64url_to_bytes(stored),
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
        )
    except InvalidRegistrationResponse as exc:
        raise HTTPException(status_code=400, detail=f"Passkey registration failed: {exc}") from exc

    transport = _infer_transport(parsed.response.transports)
    label = payload.label or _label_from_user_agent(request.headers.get("user-agent"))

    credential = Credential(
        user_id=user.id,
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        transport=transport,
        label=label,
    )
    db.add(credential)
    await db.flush()

    return PasskeyRegisterCompleteResponse(
        credential_id=bytes_to_base64url(verification.credential_id),
        label=label,
        transport=transport.value,
    )


@router.post("/passkey/login/begin", summary="Begin passkey login")
async def passkey_login_begin(
    payload: PasskeyLoginBeginRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Body (optional): ``{"email"?: str}``.

    With ``email``, scopes the ceremony to that user's registered credentials. Without
    it, returns a discoverable/usernameless challenge (``allowCredentials`` omitted).
    Always returns ``200`` with a valid-looking challenge, even for an unknown email, so
    this endpoint does not leak account existence.
    """
    settings = get_settings()
    email = payload.email.lower() if payload and payload.email else None

    allow_credentials: list[PublicKeyCredentialDescriptor] | None = None
    if email:
        result = await db.execute(select(User).where(User.email == email))
        target_user = result.scalar_one_or_none()
        if target_user is not None:
            cred_result = await db.execute(
                select(Credential).where(Credential.user_id == target_user.id)
            )
            allow_credentials = [
                PublicKeyCredentialDescriptor(id=c.credential_id)
                for c in cred_result.scalars().all()
            ]
        else:
            allow_credentials = []

    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    redis = get_redis()
    await redis.set(
        _auth_challenge_key(options.challenge),
        "1",
        ex=settings.webauthn_challenge_ttl_seconds,
    )
    return Response(content=options_to_json(options), media_type="application/json")


@router.post(
    "/passkey/login/complete", response_model=MeResponse, summary="Complete passkey login"
)
async def passkey_login_complete(
    payload: PasskeyLoginCompleteRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Body: ``{"credential": <AuthenticationResponseJSON>}``. Sets session cookies."""
    settings = get_settings()
    try:
        parsed = parse_authentication_credential_json(payload.credential)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Malformed passkey assertion") from exc

    client_data = parse_client_data_json(parsed.response.client_data_json)
    redis = get_redis()
    challenge_key = _auth_challenge_key(client_data.challenge)
    consumed = await redis.delete(challenge_key)
    if not consumed:
        raise HTTPException(status_code=400, detail="Passkey challenge expired or already used")

    result = await db.execute(select(Credential).where(Credential.credential_id == parsed.raw_id))
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(status_code=401, detail="Unknown passkey credential")

    try:
        verification = verify_authentication_response(
            credential=parsed,
            expected_challenge=client_data.challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
            credential_public_key=credential.public_key,
            credential_current_sign_count=credential.sign_count,
        )
    except InvalidAuthenticationResponse as exc:
        raise HTTPException(
            status_code=401, detail=f"Passkey authentication failed: {exc}"
        ) from exc

    credential.sign_count = verification.new_sign_count

    user_result = await db.execute(select(User).where(User.id == credential.user_id))
    user = user_result.scalar_one()
    customer_result = await db.execute(select(Customer).where(Customer.user_id == user.id))
    customer = customer_result.scalar_one_or_none()

    access_token, refresh_token = await create_session(str(user.id))
    set_session_cookies(response, access_token=access_token, refresh_token=refresh_token)

    return _me_response(user, customer)


# ========================================================================================
# Email OTP fallback
# ========================================================================================


async def _bump_and_check_otp_rate_limit(email: str) -> bool:
    """Increment the per-email hourly OTP-send counter; return True if still allowed."""
    settings = get_settings()
    redis = get_redis()
    key = f"otp:rate:{email}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 3600)
    return count <= settings.otp_rate_limit_per_hour


_OTP_SENT_MESSAGE = "If that email is registered, a verification code has been sent."
_OTP_INVALID_MESSAGE = "Invalid or expired code"


@router.post("/otp/send", response_model=MessageResponse, summary="Send an email OTP code")
async def otp_send(
    payload: OtpSendRequest, db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    """Body: ``{"email": str}``. Always returns ``200`` with the same generic message —
    this endpoint never reveals whether the email is registered or rate-limited."""
    settings = get_settings()
    email = payload.email.lower()
    generic_response = MessageResponse(message=_OTP_SENT_MESSAGE)

    if not await _bump_and_check_otp_rate_limit(email):
        logger.warning("otp_rate_limited", email=email)
        return generic_response

    code = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    db.add(
        OtpCode(
            email=email,
            code_hash=code_hash,
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.otp_ttl_seconds),
        )
    )

    try:
        await send_templated(
            email,
            "otp_code",
            {
                "code": code,
                "ttl_minutes": settings.otp_ttl_seconds // 60,
                "full_name": None,
            },
        )
    except EmailNotConfigured:
        logger.warning("otp_email_skipped_no_creds", email=email)
    except Exception:
        logger.exception("otp_email_send_failed", email=email)

    return generic_response


@router.post("/otp/verify", response_model=MeResponse, summary="Verify an email OTP code")
async def otp_verify(
    payload: OtpVerifyRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> MeResponse:
    """Body: ``{"email": str, "code": "123456"}``. Sets session cookies on success.

    Upserts the :class:`User`/:class:`Customer` if this is the email's first sign-in.
    """
    email = payload.email.lower()
    now = datetime.now(UTC)

    result = await db.execute(
        select(OtpCode)
        .where(OtpCode.email == email, OtpCode.consumed.is_(False), OtpCode.expires_at > now)
        .order_by(OtpCode.created_at.desc())
    )
    candidate_hash = hashlib.sha256(payload.code.encode()).hexdigest()
    matched: OtpCode | None = None
    for candidate in result.scalars().all():
        if hmac.compare_digest(candidate.code_hash, candidate_hash):
            matched = candidate
            break

    if matched is None:
        raise HTTPException(status_code=400, detail=_OTP_INVALID_MESSAGE)
    matched.consumed = True

    user, created = await _get_or_create_user_by_email(db, email)
    customer = await _ensure_customer_for_user(db, user, full_name=None, email=email)

    access_token, refresh_token = await create_session(str(user.id))
    set_session_cookies(response, access_token=access_token, refresh_token=refresh_token)

    if created:
        await _send_welcome_best_effort(user, customer)

    return _me_response(user, customer)


# ========================================================================================
# Session lifecycle
# ========================================================================================


@router.post("/refresh", response_model=MessageResponse, summary="Rotate the session")
async def refresh_session(
    response: Response,
    sarathi_refresh: Annotated[str | None, Cookie()] = None,
) -> MessageResponse:
    """No body. Reads ``sarathi_refresh``, rotates it (old jti revoked, new issued)."""
    if not sarathi_refresh:
        clear_session_cookies(response)
        raise HTTPException(status_code=401, detail="No active session")

    try:
        access_token, refresh_token = await rotate_session(sarathi_refresh)
    except SessionError as exc:
        clear_session_cookies(response)
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    set_session_cookies(response, access_token=access_token, refresh_token=refresh_token)
    return MessageResponse(message="ok")


@router.post("/logout", response_model=MessageResponse, summary="Log out")
async def logout(
    response: Response,
    sarathi_refresh: Annotated[str | None, Cookie()] = None,
) -> MessageResponse:
    """No body. Always succeeds (idempotent); revokes the current refresh session."""
    if sarathi_refresh:
        await revoke_session_from_refresh_token(sarathi_refresh)
    clear_session_cookies(response)
    return MessageResponse(message="logged out")


# ========================================================================================
# /me
# ========================================================================================


@me_router.get("/me", response_model=MeResponse, summary="Current user + customer profile")
async def get_me(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    result = await db.execute(select(Customer).where(Customer.user_id == user.id))
    customer = result.scalar_one_or_none()
    return _me_response(user, customer)
