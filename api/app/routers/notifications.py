import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.deps import CurrentUser, SessionDep
from app.integrations.sms import SmsError, SmsSender, get_sms_sender, twilio_signature_valid
from app.models import ClientProfile, PartnerProfile, User
from app.services import notifications as service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["notifications"])

SmsDep = Annotated[SmsSender, Depends(get_sms_sender)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class NotificationSettingsOut(BaseModel):
    phone: str | None
    phone_verified: bool
    sms_reminders: bool
    email_reminders: bool


class NotificationSettingsIn(BaseModel):
    sms_reminders: bool
    email_reminders: bool


class PhoneIn(BaseModel):
    phone: str = Field(min_length=4, max_length=32)


class CodeIn(BaseModel):
    code: str = Field(min_length=4, max_length=10)


def settings_out(user: User) -> NotificationSettingsOut:
    return NotificationSettingsOut(
        phone=user.phone,
        phone_verified=user.phone_verified_at is not None,
        sms_reminders=service.sms_allowed(user),
        email_reminders=user.email_reminders,
    )


def _error(exc: service.NotificationError) -> HTTPException:
    code = 429 if exc.code.startswith("too_many") else status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(code, {"code": exc.code, "message": exc.message})


async def _region(session: SessionDep, user: User) -> str:
    """Country used to read numbers typed without a +country prefix."""
    client = await session.get(ClientProfile, user.id)
    if client is not None:
        return client.country_code
    partner = await session.get(PartnerProfile, user.id)
    return partner.country_code if partner is not None else "US"


@router.get("/me/notifications")
async def get_notification_settings(user: CurrentUser) -> NotificationSettingsOut:
    return settings_out(user)


@router.put("/me/notifications")
async def put_notification_settings(
    body: NotificationSettingsIn, user: CurrentUser, session: SessionDep
) -> NotificationSettingsOut:
    try:
        service.set_preferences(user, sms=body.sms_reminders, email=body.email_reminders)
    except service.NotificationError as exc:
        raise _error(exc) from exc
    await session.commit()
    return settings_out(user)


@router.post("/me/phone", status_code=status.HTTP_202_ACCEPTED)
async def add_phone(
    body: PhoneIn, user: CurrentUser, session: SessionDep, sms: SmsDep
) -> dict[str, str]:
    """Text a 6-digit code to the number; confirm with POST /me/phone/verify."""
    region = await _region(session, user)
    try:
        phone = await service.start_phone_verification(session, user, body.phone, region, sms)
    except service.NotificationError as exc:
        raise _error(exc) from exc
    except SmsError as exc:
        logger.exception("Couldn't send verification SMS")
        raise HTTPException(503, "We couldn't send a text right now — try again shortly") from exc
    await session.commit()
    return {"phone": phone}


@router.post("/me/phone/verify")
async def verify_phone(
    body: CodeIn, user: CurrentUser, session: SessionDep
) -> NotificationSettingsOut:
    try:
        await service.confirm_phone(session, user, body.code)
    except service.NotificationError as exc:
        await session.commit()  # keep the attempt count
        raise _error(exc) from exc
    await session.commit()
    return settings_out(user)


@router.delete("/me/phone")
async def delete_phone(user: CurrentUser, session: SessionDep) -> NotificationSettingsOut:
    service.remove_phone(user)
    await session.commit()
    return settings_out(user)


@router.post("/webhooks/twilio/sms", include_in_schema=False)
async def twilio_inbound(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    x_twilio_signature: Annotated[str | None, Header()] = None,
) -> Response:
    """Inbound texts: STOP (and synonyms) turns text reminders off for that number."""
    form = {k: str(v) for k, v in (await request.form()).items()}
    if not twilio_signature_valid(
        str(request.url), form, x_twilio_signature, settings.twilio_auth_token.get_secret_value()
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")
    if form.get("Body", "").strip().upper() in service.STOP_WORDS and form.get("From"):
        await service.opt_out_by_phone(session, form["From"])
        await session.commit()
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response/>', media_type="text/xml")
