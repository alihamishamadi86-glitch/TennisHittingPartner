import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class PaymentStatus(enum.StrEnum):
    REQUIRES_PAYMENT = "requires_payment"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"  # superseded (e.g. promo code changed) or abandoned


class RefundStatus(enum.StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CreditReason(enum.StrEnum):
    RAIN_OUT = "rain_out"
    REFUND = "refund"  # refunded portion that was originally paid with credit
    GOODWILL = "goodwill"


class Payment(TimestampMixin, Base):
    """One checkout attempt for a booking. Amounts are integer minor units (cents)."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)  # stripe | fake | credit
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    status: Mapped[PaymentStatus] = mapped_column(
        _enum(PaymentStatus, "payment_status"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credit_applied_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # What the card is charged: price - discount - credit.
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    promo_code_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("promo_codes.id", ondelete="SET NULL")
    )
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_message: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        CheckConstraint("amount_cents >= 0 AND price_cents >= 0", name="non_negative"),
        CheckConstraint(
            "amount_cents = price_cents - discount_cents - credit_applied_cents",
            name="amount_adds_up",
        ),
    )


class Refund(Base):
    """Money returned for a payment. Card portions go back via the provider (worker);
    portions originally paid with credit come back as credit immediately."""

    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[RefundStatus] = mapped_column(
        _enum(RefundStatus, "refund_status"), nullable=False
    )
    provider_refund_id: Mapped[str | None] = mapped_column(String(255))
    failure_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("amount_cents > 0", name="positive"),)


class Credit(Base):
    """Account credit (e.g. rain-outs), spent oldest-expiring first at checkout."""

    __tablename__ = "credits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[CreditReason] = mapped_column(
        _enum(CreditReason, "credit_reason"), nullable=False
    )
    source_booking_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("remaining_cents >= 0 AND remaining_cents <= amount_cents", name="range"),
        Index("ix_credits_user_remaining", "user_id", "remaining_cents"),
    )


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)  # upper-case
    percent_off: Mapped[int | None] = mapped_column(Integer)
    amount_off_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    first_booking_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    redemptions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(percent_off IS NOT NULL AND percent_off BETWEEN 1 AND 100"
            " AND amount_off_cents IS NULL)"
            " OR (amount_off_cents IS NOT NULL AND amount_off_cents > 0"
            " AND percent_off IS NULL)",
            name="one_discount",
        ),
    )


class PromoRedemption(Base):
    """A code used by a user (each code once per user)."""

    __tablename__ = "promo_redemptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    promo_code_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("promo_code_id", "user_id"),)


class StripeEvent(Base):
    """Webhook events already handled (Stripe delivers at least once)."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
