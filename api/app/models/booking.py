import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class BookingStatus(enum.StrEnum):
    HELD = "held"  # reserved while the client completes checkout
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    EXPIRED = "expired"  # hold lapsed
    CANCELLED_FREE = "cancelled_free"  # client cancelled in time
    CANCELLED_LATE = "cancelled_late"  # client cancelled inside the window (fee)
    PARTNER_CANCELLED = "partner_cancelled"
    RAINED_OUT = "rained_out"
    NO_SHOW = "no_show"


# Statuses that occupy the partner's (and client's) time.
ACTIVE_STATUSES = (BookingStatus.HELD, BookingStatus.CONFIRMED)


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class Booking(TimestampMixin, Base):
    """A hitting session. Overlaps are prevented by two exclusion constraints (see migration):
    per partner over [starts_at, blocked_until) — the session plus travel buffer — and per
    client over [starts_at, ends_at), both only while the booking is held or confirmed."""

    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("partner_profiles.user_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    club_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # ends_at + travel buffer: the partner can't start another session before this.
    blocked_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Partner's timezone at booking time, for displaying local times.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        _enum(BookingStatus, "booking_status"), nullable=False, default=BookingStatus.HELD
    )
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Price snapshot at booking time (minor units), so later price changes don't apply.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="usd")
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    partner_pay_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    cancellation_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Share of the session fee the client still owes after cancelling (0, or 0.5 when late).
    cancellation_fee_fraction: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    # Rained-out sessions earn a rebooking credit (ledger and expiry arrive with payments, M6).
    credit_issued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_bookings_status_hold_expires_at", "status", "hold_expires_at"),
        Index("ix_bookings_starts_at", "starts_at"),
    )


class WaiverVersion(Base):
    """Published waiver text. Clients sign the active version before their first booking."""

    __tablename__ = "waiver_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WaiverSignature(Base):
    """Evidence of acceptance: who, which version, when, the typed name and the request origin."""

    __tablename__ = "waiver_signatures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    waiver_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("waiver_versions.id", ondelete="RESTRICT"), nullable=False
    )
    signed_name: Mapped[str] = mapped_column(String(200), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
