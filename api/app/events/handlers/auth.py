"""Auth emails. Tokens are minted here in the worker so raw values never sit in the outbox or
in Pub/Sub messages; if sending fails the transaction (and the token) rolls back and Pub/Sub
redelivers."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.catalog import (
    EMAIL_VERIFICATION_REQUESTED,
    PASSWORD_RESET_REQUESTED,
    USER_REGISTERED,
)
from app.events.envelope import EventEnvelope
from app.events.registry import handles
from app.integrations.email import get_email_sender
from app.models import EmailTokenPurpose, User
from app.services.auth import create_email_token
from app.services.email_templates import password_reset_email, verification_email


async def _load_user(session: AsyncSession, envelope: EventEnvelope) -> User | None:
    user = await session.get(User, uuid.UUID(envelope.data["user_id"]))
    return user if user is not None and user.is_active else None


async def _send_verification(session: AsyncSession, envelope: EventEnvelope) -> None:
    user = await _load_user(session, envelope)
    if user is None or user.is_email_verified:
        return
    token = await create_email_token(session, user.id, EmailTokenPurpose.VERIFY_EMAIL)
    await get_email_sender().send(verification_email(user, token))


@handles(USER_REGISTERED, consumer="auth.send_verification_on_register")
async def send_verification_on_register(session: AsyncSession, envelope: EventEnvelope) -> None:
    await _send_verification(session, envelope)


@handles(EMAIL_VERIFICATION_REQUESTED, consumer="auth.send_verification")
async def send_verification(session: AsyncSession, envelope: EventEnvelope) -> None:
    await _send_verification(session, envelope)


@handles(PASSWORD_RESET_REQUESTED, consumer="auth.send_password_reset")
async def send_password_reset(session: AsyncSession, envelope: EventEnvelope) -> None:
    user = await _load_user(session, envelope)
    if user is None:
        return
    token = await create_email_token(session, user.id, EmailTokenPurpose.RESET_PASSWORD)
    await get_email_sender().send(password_reset_email(user, token))
