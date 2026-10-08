import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import CreditReason, PaymentStatus
from app.schemas.bookings import BookingOut


class PaymentsConfigOut(BaseModel):
    enabled: bool
    provider: str
    publishable_key: str | None
    currency: str
    prices_cents: dict[int, int]


class CheckoutIn(BaseModel):
    promo_code: str | None = Field(default=None, max_length=40)


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    status: PaymentStatus
    currency: str
    price_cents: int
    discount_cents: int
    credit_applied_cents: int
    amount_cents: int


class CheckoutOut(BaseModel):
    booking: BookingOut
    payment: PaymentOut
    # Pass to Stripe.js to confirm the card payment; absent when credit covered everything.
    client_secret: str | None


class CreditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount_cents: int
    remaining_cents: int
    reason: CreditReason
    expires_at: datetime | None
    created_at: datetime


class CreditsOut(BaseModel):
    currency: str
    balance_cents: int
    credits: list[CreditOut]


class PromoCodeIn(BaseModel):
    code: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    percent_off: int | None = Field(default=None, ge=1, le=100)
    amount_off_cents: int | None = Field(default=None, gt=0)
    first_booking_only: bool = False
    max_redemptions: int | None = Field(default=None, gt=0)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _one_discount(self) -> "PromoCodeIn":
        if (self.percent_off is None) == (self.amount_off_cents is None):
            raise ValueError("Give either percent_off or amount_off_cents")
        self.code = self.code.upper()
        return self


class PromoCodeOut(PromoCodeIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    currency: str
    redemptions: int
    active: bool
