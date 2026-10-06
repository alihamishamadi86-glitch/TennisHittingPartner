import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.models import (
    ClientGoal,
    DominantHand,
    PartnerBackground,
    PartnerStatus,
    PlayStyle,
)

# Decimals are exact for 0.5 steps; serialize as JSON numbers rather than strings.
NtrpRating = Annotated[
    Decimal,
    Field(ge=Decimal("1.5"), le=Decimal("7.0"), multiple_of=Decimal("0.5")),
    PlainSerializer(float, return_type=float, when_used="json"),
]
UtrRating = Annotated[
    Decimal,
    Field(ge=Decimal("1"), le=Decimal("16.5"), decimal_places=2),
    PlainSerializer(float, return_type=float, when_used="json"),
]


class LevelFields(BaseModel):
    ntrp_rating: NtrpRating
    utr_rating: UtrRating | None = None
    years_playing: int | None = Field(default=None, ge=0, le=80)
    dominant_hand: DominantHand | None = None
    play_style: PlayStyle | None = None
    city: str = Field(min_length=1, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    country_code: str = Field(default="US", pattern=r"^[A-Z]{2}$")

    @field_validator("city", "region")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class ClientProfileIn(LevelFields):
    goals: list[ClientGoal] = Field(default_factory=list, max_length=len(ClientGoal))

    @field_validator("goals")
    @classmethod
    def _unique_goals(cls, goals: list[ClientGoal]) -> list[ClientGoal]:
        return list(dict.fromkeys(goals))


class ClientProfileOut(ClientProfileIn):
    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime


class PartnerProfileIn(LevelFields):
    background: PartnerBackground | None = None
    bio: str = Field(default="", max_length=2000)
    service_radius_km: int = Field(default=15, ge=1, le=100)


class PartnerProfileOut(PartnerProfileIn):
    model_config = ConfigDict(from_attributes=True)

    status: PartnerStatus
    verified_ntrp_rating: NtrpRating | None
    submitted_at: datetime | None
    approved_at: datetime | None
    updated_at: datetime
    # Requirements still unmet before the application can be submitted.
    missing_for_application: list[str] = Field(default_factory=list)


# --- Photos -----------------------------------------------------------------------------


class PhotoUploadIn(BaseModel):
    content_type: str = Field(max_length=100)
    size: int = Field(gt=0)


class PhotoUploadOut(BaseModel):
    object_name: str
    upload_url: str
    method: str
    headers: dict[str, str]


class PhotoAttachIn(BaseModel):
    object_name: str = Field(max_length=300)


# --- Level questionnaire ----------------------------------------------------------------


class QuestionOut(BaseModel):
    key: str
    prompt: str
    options: list[str]


class QuestionnaireOut(BaseModel):
    questions: list[QuestionOut]


Answer = Annotated[int, Field(ge=0, le=3)]


class LevelAnswersIn(BaseModel):
    experience: Answer
    rally: Answer
    backhand: Answer
    serve: Answer
    net: Answer
    competition: Answer


class LevelSuggestionOut(BaseModel):
    ntrp_rating: NtrpRating
    description: str


# --- Admin: partner verification ---------------------------------------------------------


class AdminDecision(enum.StrEnum):
    SCREENED = "screened"
    APPROVED = "approved"
    REJECTED = "rejected"


class PartnerDecisionIn(BaseModel):
    decision: AdminDecision
    note: str = Field(default="", max_length=1000)
    verified_ntrp_rating: NtrpRating | None = None


class PartnerApplicationOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: str
    avatar_url: str | None
    status: PartnerStatus
    ntrp_rating: NtrpRating
    verified_ntrp_rating: NtrpRating | None
    background: PartnerBackground | None
    city: str
    region: str | None
    submitted_at: datetime | None


class VerificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: PartnerStatus
    to_status: PartnerStatus
    actor_id: uuid.UUID | None
    note: str
    created_at: datetime


class PartnerApplicationDetailOut(PartnerApplicationOut):
    profile: PartnerProfileOut
    history: list[VerificationOut]
