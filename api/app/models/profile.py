import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.user import User


class DominantHand(enum.StrEnum):
    RIGHT = "right"
    LEFT = "left"
    AMBIDEXTROUS = "ambidextrous"


class PlayStyle(enum.StrEnum):
    BASELINER = "baseliner"
    ALL_COURT = "all_court"
    SERVE_AND_VOLLEY = "serve_and_volley"
    COUNTERPUNCHER = "counterpuncher"


class ClientGoal(enum.StrEnum):
    RALLY = "rally"
    MATCH_PLAY = "match_play"
    FITNESS = "fitness"
    TECHNIQUE = "technique"


class PartnerBackground(enum.StrEnum):
    PROFESSIONAL = "professional"
    COLLEGE = "college"
    HIGH_SCHOOL_VARSITY = "high_school_varsity"
    CLUB = "club"
    COACH = "coach"
    OTHER = "other"


class PartnerStatus(enum.StrEnum):
    DRAFT = "draft"
    APPLIED = "applied"
    SCREENED = "screened"
    APPROVED = "approved"
    REJECTED = "rejected"


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class LevelMixin:
    """Playing-level fields shared by clients and partners."""

    ntrp_rating: Mapped[Decimal] = mapped_column(Numeric(2, 1), nullable=False)
    utr_rating: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    years_playing: Mapped[int | None] = mapped_column(Integer)
    dominant_hand: Mapped[DominantHand | None] = mapped_column(_enum(DominantHand, "dominant_hand"))
    play_style: Mapped[PlayStyle | None] = mapped_column(_enum(PlayStyle, "play_style"))
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str | None] = mapped_column(String(120))  # state / province
    postal_code: Mapped[str | None] = mapped_column(String(12))
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="US")


LEVEL_CHECKS = (
    CheckConstraint("ntrp_rating BETWEEN 1.5 AND 7.0", name="ntrp_range"),
    CheckConstraint("ntrp_rating * 2 = floor(ntrp_rating * 2)", name="ntrp_half_steps"),
    CheckConstraint("utr_rating IS NULL OR utr_rating BETWEEN 1 AND 16.5", name="utr_range"),
    CheckConstraint("years_playing IS NULL OR years_playing BETWEEN 0 AND 80", name="years_range"),
)


class ClientProfile(LevelMixin, TimestampMixin, Base):
    __tablename__ = "client_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    goals: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)

    user: Mapped[User] = relationship()

    __table_args__ = LEVEL_CHECKS


class PartnerProfile(LevelMixin, TimestampMixin, Base):
    __tablename__ = "partner_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    background: Mapped[PartnerBackground | None] = mapped_column(
        _enum(PartnerBackground, "partner_background")
    )
    bio: Mapped[str] = mapped_column(Text, nullable=False, default="")
    service_radius_km: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    # IANA timezone for availability (e.g. "America/Chicago"); set with the weekly schedule.
    timezone: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[PartnerStatus] = mapped_column(
        _enum(PartnerStatus, "partner_status"), nullable=False, default=PartnerStatus.DRAFT
    )
    # Level confirmed by the agency at screening; this is what clients see and match on.
    verified_ntrp_rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()

    __table_args__ = (
        *LEVEL_CHECKS,
        CheckConstraint("service_radius_km BETWEEN 1 AND 100", name="radius_range"),
        CheckConstraint(
            "verified_ntrp_rating IS NULL OR verified_ntrp_rating BETWEEN 1.5 AND 7.0",
            name="verified_ntrp_range",
        ),
    )


class PartnerVerification(Base):
    """Audit trail of partner status changes (who, when, why)."""

    __tablename__ = "partner_verifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    partner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("partner_profiles.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[PartnerStatus] = mapped_column(
        _enum(PartnerStatus, "partner_status"), nullable=False
    )
    to_status: Mapped[PartnerStatus] = mapped_column(
        _enum(PartnerStatus, "partner_status"), nullable=False
    )
    # Null when the partner acted (submit / resubmit).
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
