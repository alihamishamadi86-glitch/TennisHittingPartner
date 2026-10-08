import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NotificationKind(enum.StrEnum):
    REMINDER_24H = "reminder_24h"
    REMINDER_2H = "reminder_2h"
    FOLLOW_UP = "follow_up"  # after the session: rebook link


class NotificationStatus(enum.StrEnum):
    PENDING = "pending"
    SENT = "sent"
    SKIPPED = "skipped"  # booking no longer on, or nothing to send


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class ScheduledNotification(Base):
    """A message due at `send_at`, sent by the once-a-minute sweep (at most once)."""

    __tablename__ = "scheduled_notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[NotificationKind] = mapped_column(
        _enum(NotificationKind, "notification_kind"), nullable=False
    )
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        _enum(NotificationStatus, "notification_status"),
        nullable=False,
        default=NotificationStatus.PENDING,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(String(300))

    __table_args__ = (
        UniqueConstraint("booking_id", "kind"),
        Index("ix_scheduled_notifications_due", "status", "send_at"),
    )


class PhoneVerification(Base):
    """A pending SMS code for confirming a user's phone number (only the hash is stored)."""

    __tablename__ = "phone_verifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone: Mapped[str] = mapped_column(String(20), nullable=False)  # E.164
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
