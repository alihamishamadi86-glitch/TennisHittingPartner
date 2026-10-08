"""Payments: payments, refunds, account credits, promo codes, processed Stripe events, and a
price snapshot on bookings (existing bookings default to USD 0).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-08 10:22:33.161282
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("percent_off", sa.Integer(), nullable=True),
        sa.Column("amount_off_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("first_booking_only", sa.Boolean(), nullable=False),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("redemptions", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(percent_off IS NOT NULL AND percent_off BETWEEN 1 AND 100 AND amount_off_cents IS NULL) OR (amount_off_cents IS NOT NULL AND amount_off_cents > 0 AND percent_off IS NULL)",
            name=op.f("ck_promo_codes_one_discount"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promo_codes")),
        sa.UniqueConstraint("code", name=op.f("uq_promo_codes_code")),
    )
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stripe_events")),
    )
    op.create_table(
        "credits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("remaining_cents", sa.Integer(), nullable=False),
        sa.Column(
            "reason",
            sa.Enum("rain_out", "refund", "goodwill", name="credit_reason"),
            nullable=False,
        ),
        sa.Column("source_booking_id", sa.UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "remaining_cents >= 0 AND remaining_cents <= amount_cents",
            name=op.f("ck_credits_range"),
        ),
        sa.ForeignKeyConstraint(
            ["source_booking_id"],
            ["bookings.id"],
            name=op.f("fk_credits_source_booking_id_bookings"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_credits_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credits")),
    )
    op.create_index(
        "ix_credits_user_remaining", "credits", ["user_id", "remaining_cents"], unique=False
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("booking_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("requires_payment", "succeeded", "failed", "canceled", name="payment_status"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("discount_cents", sa.Integer(), nullable=False),
        sa.Column("credit_applied_cents", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("promo_code_id", sa.UUID(), nullable=True),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_message", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount_cents = price_cents - discount_cents - credit_applied_cents",
            name=op.f("ck_payments_amount_adds_up"),
        ),
        sa.CheckConstraint(
            "amount_cents >= 0 AND price_cents >= 0", name=op.f("ck_payments_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["bookings.id"],
            name=op.f("fk_payments_booking_id_bookings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["promo_code_id"],
            ["promo_codes.id"],
            name=op.f("fk_payments_promo_code_id_promo_codes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_payments_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("provider_payment_id", name=op.f("uq_payments_provider_payment_id")),
    )
    op.create_index(op.f("ix_payments_booking_id"), "payments", ["booking_id"], unique=False)
    op.create_index(op.f("ix_payments_user_id"), "payments", ["user_id"], unique=False)
    op.create_table(
        "promo_redemptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("promo_code_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name=op.f("fk_promo_redemptions_payment_id_payments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["promo_code_id"],
            ["promo_codes.id"],
            name=op.f("fk_promo_redemptions_promo_code_id_promo_codes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_promo_redemptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promo_redemptions")),
        sa.UniqueConstraint(
            "promo_code_id", "user_id", name=op.f("uq_promo_redemptions_promo_code_id")
        ),
    )
    op.create_table(
        "refunds",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "succeeded", "failed", name="refund_status"),
            nullable=False,
        ),
        sa.Column("provider_refund_id", sa.String(length=255), nullable=True),
        sa.Column("failure_message", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_refunds_positive")),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name=op.f("fk_refunds_payment_id_payments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refunds")),
    )
    op.create_index(op.f("ix_refunds_payment_id"), "refunds", ["payment_id"], unique=False)
    op.add_column(
        "bookings",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="usd"),
    )
    op.add_column(
        "bookings", sa.Column("price_cents", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "bookings",
        sa.Column("partner_pay_cents", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("bookings", "partner_pay_cents")
    op.drop_column("bookings", "price_cents")
    op.drop_column("bookings", "currency")
    op.drop_index(op.f("ix_refunds_payment_id"), table_name="refunds")
    op.drop_table("refunds")
    op.drop_table("promo_redemptions")
    op.drop_index(op.f("ix_payments_user_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_booking_id"), table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_credits_user_remaining", table_name="credits")
    op.drop_table("credits")
    op.drop_table("stripe_events")
    op.drop_table("promo_codes")
    for enum_type in ("payment_status", "refund_status", "credit_reason"):
        op.execute(f"DROP TYPE {enum_type}")
