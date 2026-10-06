import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.catalog import PARTNER_APPLICATION_SUBMITTED, PARTNER_VERIFICATION_DECIDED
from app.events.envelope import EventEnvelope
from app.events.registry import handles
from app.integrations.email import get_email_sender
from app.models import User, UserRole
from app.services.email_templates import partner_application_admin_email, partner_decision_email


@handles(PARTNER_APPLICATION_SUBMITTED, consumer="partners.notify_admins_of_application")
async def notify_admins_of_application(session: AsyncSession, envelope: EventEnvelope) -> None:
    partner = await session.get(User, uuid.UUID(envelope.data["partner_id"]))
    if partner is None:
        return
    admins = await session.scalars(
        select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
    )
    sender = get_email_sender()
    for admin in admins:
        await sender.send(partner_application_admin_email(admin, partner))


@handles(PARTNER_VERIFICATION_DECIDED, consumer="partners.notify_partner_of_decision")
async def notify_partner_of_decision(session: AsyncSession, envelope: EventEnvelope) -> None:
    partner = await session.get(User, uuid.UUID(envelope.data["partner_id"]))
    if partner is None or not partner.is_active:
        return
    await get_email_sender().send(
        partner_decision_email(partner, envelope.data["status"], envelope.data.get("note", ""))
    )
