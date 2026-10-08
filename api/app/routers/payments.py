import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, get_settings
from app.core.deps import CurrentUser, SessionDep, require_roles
from app.events.outbox import commit_and_publish
from app.integrations.payments import (
    PaymentGateway,
    PaymentProviderError,
    WebhookError,
    get_gateway,
)
from app.models import Booking, Payment, PromoCode, StripeEvent, User, UserRole
from app.routers.bookings import booking_out
from app.schemas.payments import (
    CheckoutIn,
    CheckoutOut,
    CreditOut,
    CreditsOut,
    PaymentOut,
    PaymentsConfigOut,
    PromoCodeIn,
    PromoCodeOut,
)
from app.services import payments as service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["payments"])

GatewayDep = Annotated[PaymentGateway, Depends(get_gateway)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ClientUser = Annotated[User, Depends(require_roles(UserRole.CLIENT))]
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("/payments/config")
async def payments_config(settings: SettingsDep) -> PaymentsConfigOut:
    return PaymentsConfigOut(
        provider=settings.payment_provider,
        publishable_key=settings.stripe_publishable_key or None,
        currency=settings.currency,
        prices_cents=settings.session_prices_cents,
    )


@router.post("/bookings/{booking_id}/checkout")
async def checkout(
    booking_id: uuid.UUID,
    body: CheckoutIn,
    user: ClientUser,
    session: SessionDep,
    gateway: GatewayDep,
) -> CheckoutOut:
    """Price a held booking (promo code, then account credit) and start payment."""
    booking = await session.get(Booking, booking_id, with_for_update=True)
    if booking is None or booking.client_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found")
    try:
        payment, client_secret = await service.start_checkout(
            session, booking, user, gateway, body.promo_code
        )
    except service.PaymentError as exc:
        code = status.HTTP_409_CONFLICT if exc.code == "not_payable" else 422
        raise HTTPException(code, {"code": exc.code, "message": exc.message}) from exc
    except PaymentProviderError as exc:
        logger.exception("Payment provider error at checkout")
        raise HTTPException(503, "Payments are unavailable right now — please try again") from exc
    await commit_and_publish(session)
    return CheckoutOut(
        booking=await booking_out(session, booking, user),
        payment=PaymentOut.model_validate(payment),
        client_secret=client_secret,
    )


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    session: SessionDep,
    gateway: GatewayDep,
    stripe_signature: Annotated[str | None, Header()] = None,
) -> Response:
    """Stripe → us. Signature-verified; each event is handled once (Stripe retries until 2xx)."""
    try:
        event = gateway.parse_webhook(await request.body(), stripe_signature)
    except WebhookError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid webhook") from exc

    first_time = await session.scalar(
        pg_insert(StripeEvent)
        .values(id=event["id"], type=event["type"])
        .on_conflict_do_nothing()
        .returning(StripeEvent.id)
    )
    if first_time is None:
        return Response(status_code=200)

    intent = event.get("data", {}).get("object", {})
    if event["type"] == "payment_intent.succeeded":
        await service.handle_payment_succeeded(session, intent["id"])
    elif event["type"] == "payment_intent.payment_failed":
        error = intent.get("last_payment_error") or {}
        await service.handle_payment_failed(session, intent["id"], error.get("message"))
    await commit_and_publish(session)
    return Response(status_code=200)


async def _own_fake_payment(
    session: SessionDep, payment_id: uuid.UUID, user: User, settings: Settings
) -> Payment:
    if settings.payment_provider != "fake":
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    payment = await session.get(Payment, payment_id)
    if payment is None or payment.user_id != user.id or not payment.provider_payment_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    return payment


@router.post("/dev-payments/{payment_id}/succeed", include_in_schema=False)
async def simulate_success(
    payment_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> Response:
    """Fake gateway only: behaves like Stripe's payment_intent.succeeded webhook."""
    payment = await _own_fake_payment(session, payment_id, user, settings)
    assert payment.provider_payment_id
    await service.handle_payment_succeeded(session, payment.provider_payment_id)
    await commit_and_publish(session)
    return Response(status_code=204)


@router.post("/dev-payments/{payment_id}/fail", include_in_schema=False)
async def simulate_failure(
    payment_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> Response:
    payment = await _own_fake_payment(session, payment_id, user, settings)
    assert payment.provider_payment_id
    await service.handle_payment_failed(session, payment.provider_payment_id, "Card declined")
    await session.commit()
    return Response(status_code=204)


@router.get("/me/credits")
async def my_credits(user: CurrentUser, session: SessionDep, settings: SettingsDep) -> CreditsOut:
    credits = await service.list_credits(session, user.id, settings.currency)
    return CreditsOut(
        currency=settings.currency,
        balance_cents=sum(c.remaining_cents for c in credits),
        credits=[CreditOut.model_validate(c) for c in credits],
    )


@router.post("/admin/promo-codes", status_code=status.HTTP_201_CREATED)
async def create_promo_code(
    body: PromoCodeIn, _: AdminUser, session: SessionDep, settings: SettingsDep
) -> PromoCodeOut:
    promo = PromoCode(**body.model_dump(), currency=settings.currency)
    session.add(promo)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "That code already exists") from exc
    return PromoCodeOut.model_validate(promo)


@router.get("/admin/promo-codes")
async def list_promo_codes(_: AdminUser, session: SessionDep) -> list[PromoCodeOut]:
    rows = await session.scalars(select(PromoCode).order_by(PromoCode.created_at.desc()))
    return [PromoCodeOut.model_validate(p) for p in rows]


@router.post("/admin/promo-codes/{promo_id}/deactivate")
async def deactivate_promo_code(
    promo_id: uuid.UUID, _: AdminUser, session: SessionDep
) -> PromoCodeOut:
    promo = await session.get(PromoCode, promo_id)
    if promo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    promo.active = False
    await session.commit()
    return PromoCodeOut.model_validate(promo)
