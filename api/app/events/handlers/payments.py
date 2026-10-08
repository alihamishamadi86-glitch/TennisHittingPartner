import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.catalog import PAYMENT_REFUND_REQUESTED
from app.events.envelope import EventEnvelope
from app.events.registry import handles
from app.integrations.email import get_email_sender
from app.integrations.payments import get_gateway
from app.models import Payment, Refund, RefundStatus, User
from app.services.email_templates import refund_email
from app.services.payments import execute_refund


@handles(PAYMENT_REFUND_REQUESTED, consumer="payments.execute_refund")
async def run_refund(session: AsyncSession, envelope: EventEnvelope) -> None:
    """Provider errors propagate so Pub/Sub retries; the idempotency key makes that safe."""
    refund_id = uuid.UUID(envelope.data["refund_id"])
    await execute_refund(session, refund_id, get_gateway())
    refund = await session.get(Refund, refund_id)
    if refund is None or refund.status is not RefundStatus.SUCCEEDED:
        return
    payment = await session.get(Payment, refund.payment_id)
    user = await session.get(User, payment.user_id) if payment else None
    if payment and user:
        await get_email_sender().send(refund_email(user, refund.amount_cents, payment.currency))
