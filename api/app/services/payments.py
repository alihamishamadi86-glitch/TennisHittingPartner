"""Checkout, credits, promo codes, payment confirmation and refunds.

Invariants:
  - A booking is confirmed only once money (or credit) is secured — by the provider's webhook
    (or the dev simulator), never by the browser saying "paid".
  - Provider calls never happen inside a request's database transaction except creating the
    PaymentIntent at checkout; refunds are requested via the outbox and executed by the worker
    with idempotency keys.
  - If money arrives for a booking we can no longer honour (hold lapsed and the time was
    taken, or it was released), it is refunded automatically.
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.events.catalog import BOOKING_CONFIRMED, PAYMENT_REFUND_REQUESTED
from app.events.outbox import record_event
from app.integrations.payments import PaymentGateway
from app.models import (
    Booking,
    BookingStatus,
    Credit,
    CreditReason,
    Payment,
    PaymentStatus,
    PromoCode,
    PromoRedemption,
    Refund,
    RefundStatus,
    User,
)

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def pricing_for(duration_minutes: int) -> tuple[int, int]:
    """(client price, partner pay) in minor units."""
    settings = get_settings()
    return (
        settings.session_prices_cents[duration_minutes],
        settings.partner_pay_cents[duration_minutes],
    )


# --- Credits ----------------------------------------------------------------------------


def _usable_credits(user_id: uuid.UUID, currency: str, now: datetime) -> Select[Credit]:
    return (
        select(Credit)
        .where(
            Credit.user_id == user_id,
            Credit.currency == currency,
            Credit.remaining_cents > 0,
            or_(Credit.expires_at.is_(None), Credit.expires_at > now),
        )
        .order_by(Credit.expires_at.asc().nulls_last(), Credit.created_at)
    )


async def credit_balance(
    session: AsyncSession, user_id: uuid.UUID, currency: str, now: datetime | None = None
) -> int:
    rows = (await session.scalars(_usable_credits(user_id, currency, now or _now()))).all()
    return sum(c.remaining_cents for c in rows)


async def list_credits(
    session: AsyncSession, user_id: uuid.UUID, currency: str
) -> Sequence[Credit]:
    return (await session.scalars(_usable_credits(user_id, currency, _now()))).all()


def issue_credit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    amount_cents: int,
    currency: str,
    reason: CreditReason,
    booking_id: uuid.UUID | None,
    expires_at: datetime | None,
) -> Credit | None:
    if amount_cents <= 0:
        return None
    credit = Credit(
        user_id=user_id,
        currency=currency,
        amount_cents=amount_cents,
        remaining_cents=amount_cents,
        reason=reason,
        source_booking_id=booking_id,
        expires_at=expires_at,
    )
    session.add(credit)
    return credit


async def _consume_credits(
    session: AsyncSession, user_id: uuid.UUID, amount_cents: int, currency: str
) -> int:
    """Spend credit, soonest-expiring first. Returns how much was actually available."""
    remaining = amount_cents
    for credit in await session.scalars(
        _usable_credits(user_id, currency, _now()).with_for_update()
    ):
        if remaining <= 0:
            break
        take = min(credit.remaining_cents, remaining)
        credit.remaining_cents -= take
        remaining -= take
    return amount_cents - remaining


# --- Promo codes ------------------------------------------------------------------------


async def resolve_promo(session: AsyncSession, code: str, user: User, currency: str) -> PromoCode:
    promo = await session.scalar(
        select(PromoCode).where(func.upper(PromoCode.code) == code.strip().upper())
    )
    now = _now()
    if promo is None or not promo.active or promo.currency != currency:
        raise PaymentError("promo_invalid", "That code isn't valid")
    if promo.expires_at and promo.expires_at <= now:
        raise PaymentError("promo_expired", "That code has expired")
    if promo.max_redemptions is not None and promo.redemptions >= promo.max_redemptions:
        raise PaymentError("promo_exhausted", "That code has been fully used")
    used = await session.scalar(
        select(PromoRedemption.id).where(
            PromoRedemption.promo_code_id == promo.id, PromoRedemption.user_id == user.id
        )
    )
    if used:
        raise PaymentError("promo_used", "You've already used that code")
    if promo.first_booking_only:
        paid_before = await session.scalar(
            select(Payment.id).where(
                Payment.user_id == user.id, Payment.status == PaymentStatus.SUCCEEDED
            )
        )
        if paid_before:
            raise PaymentError("promo_first_booking", "That code is for your first booking")
    return promo


def discount_for(promo: PromoCode | None, price_cents: int) -> int:
    if promo is None:
        return 0
    if promo.percent_off is not None:
        return min(price_cents, price_cents * promo.percent_off // 100)
    return min(price_cents, promo.amount_off_cents or 0)


# --- Checkout ---------------------------------------------------------------------------


async def start_checkout(
    session: AsyncSession,
    booking: Booking,
    user: User,
    gateway: PaymentGateway,
    promo_code: str | None,
) -> tuple[Payment, str | None]:
    """Price the held booking (promo, then credit) and create the payment.

    Returns (payment, client_secret). With credit covering everything the booking is
    confirmed immediately and there's no client secret.
    """
    if booking.client_id != user.id:
        raise PaymentError("not_found", "Booking not found")
    now = _now()
    if booking.status is not BookingStatus.HELD or (
        booking.hold_expires_at is not None and booking.hold_expires_at <= now
    ):
        raise PaymentError("not_payable", "This booking can't be paid for now")

    promo = await resolve_promo(session, promo_code, user, booking.currency) if promo_code else None
    discount = discount_for(promo, booking.price_cents)
    balance = await credit_balance(session, user.id, booking.currency, now)
    credit = min(balance, booking.price_cents - discount)
    amount = booking.price_cents - discount - credit

    # A new checkout supersedes earlier unpaid attempts (e.g. a promo code was added).
    for previous in await session.scalars(
        select(Payment).where(
            Payment.booking_id == booking.id, Payment.status == PaymentStatus.REQUIRES_PAYMENT
        )
    ):
        previous.status = PaymentStatus.CANCELED

    payment = Payment(
        id=uuid.uuid4(),
        booking_id=booking.id,
        user_id=user.id,
        provider="credit" if amount == 0 else gateway.name,
        status=PaymentStatus.REQUIRES_PAYMENT,
        currency=booking.currency,
        price_cents=booking.price_cents,
        discount_cents=discount,
        credit_applied_cents=credit,
        amount_cents=amount,
        promo_code_id=promo.id if promo else None,
    )
    session.add(payment)
    await session.flush()

    if amount == 0:
        await _settle(session, payment, booking)
        return payment, None

    intent = await gateway.create_intent(
        amount_cents=amount,
        currency=booking.currency,
        metadata={"booking_id": str(booking.id), "payment_id": str(payment.id)},
        idempotency_key=f"payment-{payment.id}",
    )
    payment.provider_payment_id = intent.id
    return payment, intent.client_secret


# --- Confirmation (webhook / dev simulator) ---------------------------------------------


async def _claim_booking(session: AsyncSession, booking: Booking) -> bool:
    """Confirm the booking if we still can. A lapsed hold is revived when the time is still
    free (the exclusion constraint decides); anything else can't be honoured."""
    if booking.status is BookingStatus.HELD:
        booking.status = BookingStatus.CONFIRMED
    elif booking.status is BookingStatus.EXPIRED:
        try:
            async with session.begin_nested():
                booking.status = BookingStatus.CONFIRMED
                await session.flush()
        except IntegrityError:
            await session.refresh(booking)
            return False
    else:
        return False
    booking.confirmed_at = _now()
    booking.hold_expires_at = None
    return True


async def _settle(session: AsyncSession, payment: Payment, booking: Booking) -> None:
    payment.status = PaymentStatus.SUCCEEDED
    payment.succeeded_at = _now()
    if not await _claim_booking(session, booking):
        logger.warning("Payment %s arrived for unclaimable booking %s", payment.id, booking.id)
        request_refund(session, payment, payment.amount_cents, "booking_unavailable")
        return
    if payment.credit_applied_cents:
        spent = await _consume_credits(
            session, payment.user_id, payment.credit_applied_cents, payment.currency
        )
        if spent < payment.credit_applied_cents:
            logger.error(
                "Credit shortfall on payment %s: %s cents",
                payment.id,
                payment.credit_applied_cents - spent,
            )
    if payment.promo_code_id:
        redeemed = await session.scalar(
            pg_insert(PromoRedemption)
            .values(
                promo_code_id=payment.promo_code_id, user_id=payment.user_id, payment_id=payment.id
            )
            .on_conflict_do_nothing()
            .returning(PromoRedemption.id)
        )
        if redeemed:
            promo = await session.get(PromoCode, payment.promo_code_id, with_for_update=True)
            if promo:
                promo.redemptions += 1
    record_event(session, BOOKING_CONFIRMED, {"booking_id": str(booking.id)})


async def handle_payment_succeeded(session: AsyncSession, provider_payment_id: str) -> None:
    payment = await session.scalar(
        select(Payment).where(Payment.provider_payment_id == provider_payment_id).with_for_update()
    )
    if payment is None:
        logger.warning("Success for unknown payment %s", provider_payment_id)
        return
    if payment.status is PaymentStatus.SUCCEEDED:
        return  # duplicate delivery
    booking = await session.get(Booking, payment.booking_id, with_for_update=True)
    assert booking is not None
    await _settle(session, payment, booking)


async def handle_payment_failed(
    session: AsyncSession, provider_payment_id: str, message: str | None
) -> None:
    payment = await session.scalar(
        select(Payment).where(Payment.provider_payment_id == provider_payment_id)
    )
    if payment is not None and payment.status is PaymentStatus.REQUIRES_PAYMENT:
        payment.status = PaymentStatus.FAILED
        payment.failure_message = (message or "")[:500] or None


# --- Refunds & credits after the fact ---------------------------------------------------


def request_refund(session: AsyncSession, payment: Payment, amount_cents: int, reason: str) -> None:
    """Queue a card refund; the worker executes it with an idempotency key."""
    if amount_cents <= 0:
        return
    refund = Refund(
        id=uuid.uuid4(),
        payment_id=payment.id,
        amount_cents=amount_cents,
        reason=reason,
        status=RefundStatus.PENDING,
    )
    session.add(refund)
    record_event(session, PAYMENT_REFUND_REQUESTED, {"refund_id": str(refund.id)})


async def succeeded_payment(session: AsyncSession, booking_id: uuid.UUID) -> Payment | None:
    return await session.scalar(
        select(Payment)
        .where(Payment.booking_id == booking_id, Payment.status == PaymentStatus.SUCCEEDED)
        .order_by(Payment.succeeded_at.desc())
        .limit(1)
    )


def _share(amount: int, fraction: Decimal) -> int:
    return int((Decimal(amount) * fraction).quantize(Decimal(1), rounding=ROUND_HALF_UP))


async def refund_after_cancellation(
    session: AsyncSession, booking: Booking, fee_fraction: Decimal
) -> None:
    """Return what the client paid minus any late fee: card first, then as credit for the
    part that was paid with credit. Discounts aren't money paid, so they aren't returned."""
    payment = await succeeded_payment(session, booking.id)
    if payment is None:
        return
    paid = payment.amount_cents + payment.credit_applied_cents
    refundable = paid - _share(paid, fee_fraction)
    to_card = min(refundable, payment.amount_cents)
    request_refund(session, payment, to_card, "cancellation")
    issue_credit(
        session,
        user_id=booking.client_id,
        amount_cents=refundable - to_card,
        currency=payment.currency,
        reason=CreditReason.REFUND,
        booking_id=booking.id,
        expires_at=None,
    )


async def credit_rain_out(session: AsyncSession, booking: Booking) -> int:
    """Rain-outs aren't refunded; the full amount paid becomes credit for 30 days."""
    payment = await succeeded_payment(session, booking.id)
    if payment is None:
        return 0
    amount = payment.amount_cents + payment.credit_applied_cents
    issue_credit(
        session,
        user_id=booking.client_id,
        amount_cents=amount,
        currency=payment.currency,
        reason=CreditReason.RAIN_OUT,
        booking_id=booking.id,
        expires_at=_now() + timedelta(days=get_settings().rain_credit_days),
    )
    return amount


async def execute_refund(
    session: AsyncSession, refund_id: uuid.UUID, gateway: PaymentGateway
) -> None:
    """Worker: send a pending refund to the provider (idempotent per refund id)."""
    refund = await session.get(Refund, refund_id, with_for_update=True)
    if refund is None or refund.status is not RefundStatus.PENDING:
        return
    payment = await session.get(Payment, refund.payment_id)
    assert payment is not None and payment.provider_payment_id
    refund.provider_refund_id = await gateway.refund(
        intent_id=payment.provider_payment_id,
        amount_cents=refund.amount_cents,
        idempotency_key=f"refund-{refund.id}",
    )
    refund.status = RefundStatus.SUCCEEDED
    refund.completed_at = _now()


async def refunded_cents(session: AsyncSession, booking_id: uuid.UUID) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(Refund.amount_cents), 0))
        .join(Payment, Payment.id == Refund.payment_id)
        .where(Payment.booking_id == booking_id, Refund.status != RefundStatus.FAILED)
    )
    return int(total or 0)
