import re
import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    WithJsonSchema,
    model_validator,
)

from app.models import ExceptionKind, PartnerBackground, PlayStyle
from app.schemas.profiles import NtrpRating

_TIME = re.compile(r"^([01]\d|2[0-4]):([0-5]\d)$")
GRANULARITY = 15


def _to_minutes(value: object) -> object:
    """'07:30' → 450. Times are 15-minute aligned; '24:00' means end of day."""
    if not isinstance(value, str):
        return value
    match = _TIME.match(value)
    if not match:
        raise ValueError("Use HH:MM")
    minutes = int(match[1]) * 60 + int(match[2])
    if minutes > 1440:
        raise ValueError("Time must be 24:00 or earlier")
    if minutes % GRANULARITY:
        raise ValueError(f"Use {GRANULARITY}-minute steps")
    return minutes


def _to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# Stored/handled as minutes after midnight; "HH:MM" on the wire in both directions.
Minutes = Annotated[
    int,
    BeforeValidator(_to_minutes),
    Field(ge=0, le=1440),
    PlainSerializer(_to_hhmm, return_type=str),
    WithJsonSchema({"type": "string", "pattern": _TIME.pattern, "examples": ["07:30"]}),
]


class WeeklyWindowIn(BaseModel):
    weekday: int = Field(ge=0, le=6, description="0 = Monday")
    start: Minutes
    end: Minutes

    @model_validator(mode="after")
    def _ordered(self) -> "WeeklyWindowIn":
        if self.start >= self.end:
            raise ValueError("End must be after start")
        return self


class WeeklyScheduleIn(BaseModel):
    timezone: str = Field(min_length=1, max_length=64, description="IANA name, e.g. Europe/Madrid")
    windows: list[WeeklyWindowIn] = Field(max_length=40)


class ExceptionIn(BaseModel):
    date: date
    kind: ExceptionKind
    start: Minutes | None = None
    end: Minutes | None = None
    note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _ordered(self) -> "ExceptionIn":
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("End must be after start")
        return self


class ExceptionOut(ExceptionIn):
    id: uuid.UUID


class AvailabilityOut(BaseModel):
    timezone: str | None
    windows: list[WeeklyWindowIn]
    exceptions: list[ExceptionOut]


class DaySlotsOut(BaseModel):
    date: date
    slots: list[datetime]


class SlotsOut(BaseModel):
    timezone: str
    duration_minutes: int
    days: list[DaySlotsOut]


class ClubRefOut(BaseModel):
    id: uuid.UUID
    name: str
    distance_km: float | None = None


class PartnerCardOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    avatar_url: str | None
    ntrp_rating: NtrpRating | None
    background: PartnerBackground | None
    play_style: PlayStyle | None
    years_playing: int | None
    bio: str
    timezone: str
    distance_km: float
    clubs: list[ClubRefOut]
    slots: list[datetime]
    next_slot: datetime | None


class PartnerPublicOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    avatar_url: str | None
    ntrp_rating: NtrpRating | None
    background: PartnerBackground | None
    play_style: PlayStyle | None
    dominant_hand: str | None
    years_playing: int | None
    bio: str
    city: str
    region: str | None
    timezone: str | None
    clubs: list[ClubRefOut]
