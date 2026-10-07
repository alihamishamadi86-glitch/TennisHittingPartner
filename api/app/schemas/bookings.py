import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer, model_validator

from app.models import BookingStatus
from app.schemas.profiles import NtrpRating
from app.services.booking_policy import Action

# Share of the session fee, e.g. 0.5 — a JSON number regardless of DB/in-memory scale.
FeeFraction = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class WaiverOut(BaseModel):
    version: int
    title: str
    body: str
    signed: bool


class WaiverSignIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    agree: bool

    @model_validator(mode="after")
    def _agreed(self) -> "WaiverSignIn":
        if not self.agree:
            raise ValueError("You must agree to the waiver")
        return self


class BookingIn(BaseModel):
    partner_id: uuid.UUID
    club_id: uuid.UUID
    starts_at: datetime
    duration_minutes: int
    note: str = Field(default="", max_length=500)


class BookingActionIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class PersonOut(BaseModel):
    id: uuid.UUID
    full_name: str
    avatar_url: str | None
    ntrp_rating: NtrpRating | None = None


class BookingClubOut(BaseModel):
    id: uuid.UUID
    name: str
    address: str | None
    lat: float
    lon: float


class CancellationTermsOut(BaseModel):
    free_until: datetime
    fee_fraction_if_cancelled_now: FeeFraction


class BookingOut(BaseModel):
    id: uuid.UUID
    status: BookingStatus
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int
    timezone: str
    club: BookingClubOut
    client: PersonOut
    partner: PersonOut
    hold_expires_at: datetime | None
    confirmed_at: datetime | None
    note: str
    cancelled_at: datetime | None
    cancellation_reason: str
    cancellation_fee_fraction: FeeFraction | None
    credit_issued: bool
    # What the viewer may do now, and what cancelling would cost them.
    actions: list[Action]
    cancellation_terms: CancellationTermsOut | None
