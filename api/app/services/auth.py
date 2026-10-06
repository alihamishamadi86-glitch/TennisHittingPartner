"""Authentication use cases. Functions mutate the session but never commit; callers own the
transaction (so a failed login's attempt counter is committed even though it raises)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from app.events.catalog import (
    EMAIL_VERIFICATION_REQUESTED,
    PASSWORD_RESET_REQUESTED,
    USER_REGISTERED,
)
from app.events.outbox import record_event
from app.integrations.google_oauth import GoogleIdentity
from app.models import AuthIdentity, EmailToken, EmailTokenPurpose, RefreshToken, User, UserRole

GOOGLE = "google"
# A just-rotated refresh token presented again within this window is treated as a benign race
# (two tabs refreshing at once) rather than token theft.
ROTATION_GRACE = timedelta(seconds=30)
VERIFICATION_RESEND_COOLDOWN = timedelta(seconds=60)
SELF_SERVICE_ROLES = frozenset({UserRole.CLIENT, UserRole.PARTNER})


class AuthError(Exception):
    pass


class InvalidCredentialsError(AuthError):
    pass


class AccountLockedError(AuthError):
    pass


class EmailTakenError(AuthError):
    pass


class InvalidTokenError(AuthError):
    pass


class RoleNotAllowedError(AuthError):
    pass


class GoogleEmailNotVerifiedError(AuthError):
    pass


@dataclass(frozen=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    refresh_token_id: uuid.UUID
    refresh_expires_at: datetime


@dataclass(frozen=True)
class ClientInfo:
    user_agent: str | None = None
    ip_address: str | None = None


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _now() -> datetime:
    return datetime.now(UTC)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == normalize_email(email)))


# --- Registration & login ---------------------------------------------------------------


async def register_user(
    session: AsyncSession, *, email: str, password: str, full_name: str, role: UserRole
) -> User:
    if role not in SELF_SERVICE_ROLES:
        raise RoleNotAllowedError
    if await get_user_by_email(session, email):
        raise EmailTakenError
    user = User(
        id=uuid.uuid4(),
        email=normalize_email(email),
        password_hash=hash_password(password),
        full_name=full_name.strip(),
        role=role,
        last_login_at=_now(),
    )
    session.add(user)
    record_event(session, USER_REGISTERED, {"user_id": str(user.id), "method": "password"})
    await session.flush()
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    settings = get_settings()
    user = await session.scalar(
        select(User).where(User.email == normalize_email(email)).with_for_update()
    )
    now = _now()
    if user and user.locked_until and user.locked_until > now:
        raise AccountLockedError

    if user is None or not verify_password(password, user.password_hash) or not user.is_active:
        if user is not None:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.max_failed_logins:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_login_attempts = 0
        raise InvalidCredentialsError

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    if user.password_hash and password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


# --- Sessions ---------------------------------------------------------------------------


async def issue_session(
    session: AsyncSession,
    user: User,
    client: ClientInfo,
    family_id: uuid.UUID | None = None,
) -> SessionTokens:
    raw = generate_token()
    expires_at = _now() + timedelta(days=get_settings().refresh_token_ttl_days)
    token = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_id or uuid.uuid4(),
        token_hash=hash_token(raw),
        expires_at=expires_at,
        user_agent=(client.user_agent or "")[:512] or None,
        ip_address=client.ip_address,
    )
    session.add(token)
    await session.flush()
    return SessionTokens(create_access_token(user.id), raw, token.id, expires_at)


async def rotate_refresh_token(
    session: AsyncSession, raw: str, client: ClientInfo
) -> tuple[User, SessionTokens]:
    token = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)).with_for_update()
    )
    now = _now()
    if token is None:
        raise InvalidTokenError
    if token.revoked_at is not None:
        rotated_recently = token.replaced_by_id is not None and token.revoked_at > now - (
            ROTATION_GRACE
        )
        if not rotated_recently:
            # Reuse of a rotated token: assume it was stolen and end the whole session family.
            await _revoke_family(session, token.family_id)
        raise InvalidTokenError
    if token.expires_at <= now:
        raise InvalidTokenError

    user = await session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError

    tokens = await issue_session(session, user, client, family_id=token.family_id)
    token.revoked_at = now
    token.replaced_by_id = tokens.refresh_token_id
    return user, tokens


async def revoke_session(session: AsyncSession, raw: str) -> None:
    token = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))
    )
    if token is not None:
        await _revoke_family(session, token.family_id)


async def revoke_all_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


# --- Email tokens -----------------------------------------------------------------------


async def create_email_token(
    session: AsyncSession, user_id: uuid.UUID, purpose: EmailTokenPurpose
) -> str:
    """Create a single-use email token and return the raw value (only ever put in the email)."""
    settings = get_settings()
    ttl = (
        timedelta(hours=settings.email_verification_ttl_hours)
        if purpose is EmailTokenPurpose.VERIFY_EMAIL
        else timedelta(minutes=settings.password_reset_ttl_minutes)
    )
    raw = generate_token()
    session.add(
        EmailToken(
            user_id=user_id, purpose=purpose, token_hash=hash_token(raw), expires_at=_now() + ttl
        )
    )
    await session.flush()
    return raw


async def _consume_email_token(session: AsyncSession, raw: str, purpose: EmailTokenPurpose) -> User:
    token = await session.scalar(
        select(EmailToken)
        .where(EmailToken.token_hash == hash_token(raw), EmailToken.purpose == purpose)
        .with_for_update()
    )
    now = _now()
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise InvalidTokenError
    user = await session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError
    # Using one token invalidates every other outstanding token of the same purpose.
    await session.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    return user


async def verify_email(session: AsyncSession, raw: str) -> User:
    user = await _consume_email_token(session, raw, EmailTokenPurpose.VERIFY_EMAIL)
    if user.email_verified_at is None:
        user.email_verified_at = _now()
    return user


async def request_email_verification(session: AsyncSession, user: User) -> None:
    if user.is_email_verified:
        return
    latest = await session.scalar(
        select(EmailToken.created_at)
        .where(EmailToken.user_id == user.id, EmailToken.purpose == EmailTokenPurpose.VERIFY_EMAIL)
        .order_by(EmailToken.created_at.desc())
        .limit(1)
    )
    if latest and latest > _now() - VERIFICATION_RESEND_COOLDOWN:
        return
    record_event(session, EMAIL_VERIFICATION_REQUESTED, {"user_id": str(user.id)})


async def request_password_reset(session: AsyncSession, email: str) -> None:
    """Always succeeds silently so the response doesn't reveal whether the email exists."""
    user = await get_user_by_email(session, email)
    if user is not None and user.is_active:
        record_event(session, PASSWORD_RESET_REQUESTED, {"user_id": str(user.id)})


async def reset_password(session: AsyncSession, raw: str, new_password: str) -> User:
    user = await _consume_email_token(session, raw, EmailTokenPurpose.RESET_PASSWORD)
    user.password_hash = hash_password(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    # Receiving the email proves ownership of the address.
    user.email_verified_at = user.email_verified_at or _now()
    await revoke_all_sessions(session, user.id)
    return user


# --- Google -----------------------------------------------------------------------------


async def sign_in_with_google(
    session: AsyncSession, identity: GoogleIdentity, requested_role: UserRole | None
) -> tuple[User, bool]:
    """Find, link or create the user for a Google identity. Returns (user, created)."""
    if not identity.email_verified:
        raise GoogleEmailNotVerifiedError
    now = _now()

    linked = await session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == GOOGLE, AuthIdentity.provider_subject == identity.subject
        )
    )
    if linked is not None:
        user = await session.get(User, linked.user_id)
        if user is None or not user.is_active:
            raise InvalidCredentialsError
        user.last_login_at = now
        return user, False

    user = await get_user_by_email(session, identity.email)
    created = user is None
    if user is None:
        user = User(
            id=uuid.uuid4(),
            email=identity.email,
            email_verified_at=now,
            full_name=identity.name,
            avatar_url=identity.picture,
            role=requested_role if requested_role in SELF_SERVICE_ROLES else None,
        )
        session.add(user)
        record_event(session, USER_REGISTERED, {"user_id": str(user.id), "method": "google"})
    else:
        if not user.is_active:
            raise InvalidCredentialsError
        if not user.is_email_verified:
            # Someone registered this address with a password but never proved ownership; the
            # Google user does own it. Drop that password and its sessions so a squatter can't
            # keep access (pre-account-takeover protection).
            user.password_hash = None
            await revoke_all_sessions(session, user.id)
            user.email_verified_at = now
        user.avatar_url = user.avatar_url or identity.picture
        user.full_name = user.full_name or identity.name

    session.add(
        AuthIdentity(
            user_id=user.id,
            provider=GOOGLE,
            provider_subject=identity.subject,
            email=identity.email,
        )
    )
    user.last_login_at = now
    await session.flush()
    return user, created


async def set_role(session: AsyncSession, user: User, role: UserRole) -> User:
    if role not in SELF_SERVICE_ROLES or user.role is not None:
        raise RoleNotAllowedError
    user.role = role
    return user
