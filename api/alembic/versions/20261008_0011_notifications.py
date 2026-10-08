"""Notifications: scheduled reminders/follow-ups, phone verification, and phone/consent
preferences on users.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-08 15:03:10.616680
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "phone_verifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_phone_verifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phone_verifications")),
    )
    op.create_index(
        op.f("ix_phone_verifications_user_id"), "phone_verifications", ["user_id"], unique=False
    )
    op.create_table(
        "scheduled_notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("booking_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("reminder_24h", "reminder_2h", "follow_up", name="notification_kind"),
            nullable=False,
        ),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "sent", "skipped", name="notification_status"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["bookings.id"],
            name=op.f("fk_scheduled_notifications_booking_id_bookings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_notifications")),
        sa.UniqueConstraint(
            "booking_id", "kind", name=op.f("uq_scheduled_notifications_booking_id")
        ),
    )
    op.create_index(
        "ix_scheduled_notifications_due",
        "scheduled_notifications",
        ["status", "send_at"],
        unique=False,
    )
    op.add_column("users", sa.Column("phone", sa.String(length=20), nullable=True))
    op.add_column(
        "users", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("sms_opt_in_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users", sa.Column("email_reminders", sa.Boolean(), server_default="true", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("users", "email_reminders")
    op.drop_column("users", "sms_opt_in_at")
    op.drop_column("users", "phone_verified_at")
    op.drop_column("users", "phone")
    op.drop_index("ix_scheduled_notifications_due", table_name="scheduled_notifications")
    op.drop_table("scheduled_notifications")
    op.execute("DROP TYPE notification_kind")
    op.execute("DROP TYPE notification_status")
    op.drop_index(op.f("ix_phone_verifications_user_id"), table_name="phone_verifications")
    op.drop_table("phone_verifications")
