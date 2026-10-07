import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Times of day are minutes after local midnight (0–1440) so a window can end at 24:00.
MINUTES_PER_DAY = 1440


class ExceptionKind(enum.StrEnum):
    UNAVAILABLE = "unavailable"  # day off (no times) or blocked hours
    AVAILABLE = "available"  # extra hours on top of the weekly rules


class AvailabilityRule(Base):
    """Weekly recurring availability window, in the partner's timezone."""

    __tablename__ = "availability_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    partner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("partner_profiles.user_id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0 = Monday
    start_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    end_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint(
            f"start_minute >= 0 AND end_minute <= {MINUTES_PER_DAY} AND start_minute < end_minute",
            name="window_range",
        ),
        Index("ix_availability_rules_partner_weekday", "partner_id", "weekday"),
    )


class AvailabilityException(Base):
    """One-off change on a specific local date."""

    __tablename__ = "availability_exceptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    partner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("partner_profiles.user_id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[ExceptionKind] = mapped_column(
        Enum(ExceptionKind, name="exception_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # Both null = the whole day (only meaningful for "unavailable").
    start_minute: Mapped[int | None] = mapped_column(SmallInteger)
    end_minute: Mapped[int | None] = mapped_column(SmallInteger)
    note: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(start_minute IS NULL AND end_minute IS NULL AND kind = 'unavailable') OR "
            f"(start_minute >= 0 AND end_minute <= {MINUTES_PER_DAY} "
            "AND start_minute < end_minute)",
            name="window_range",
        ),
        Index("ix_availability_exceptions_partner_date", "partner_id", "date"),
    )
