"""Availability: partner weekly windows, date exceptions and the partner's timezone.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08 00:44:37.589956
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "availability_exceptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "kind", sa.Enum("unavailable", "available", name="exception_kind"), nullable=False
        ),
        sa.Column("start_minute", sa.SmallInteger(), nullable=True),
        sa.Column("end_minute", sa.SmallInteger(), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(start_minute IS NULL AND end_minute IS NULL AND kind = 'unavailable') OR (start_minute >= 0 AND end_minute <= 1440 AND start_minute < end_minute)",
            name=op.f("ck_availability_exceptions_window_range"),
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"],
            ["partner_profiles.user_id"],
            name=op.f("fk_availability_exceptions_partner_id_partner_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_availability_exceptions")),
    )
    op.create_index(
        "ix_availability_exceptions_partner_date",
        "availability_exceptions",
        ["partner_id", "date"],
        unique=False,
    )
    op.create_table(
        "availability_rules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_minute", sa.SmallInteger(), nullable=False),
        sa.Column("end_minute", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "start_minute >= 0 AND end_minute <= 1440 AND start_minute < end_minute",
            name=op.f("ck_availability_rules_window_range"),
        ),
        sa.CheckConstraint(
            "weekday BETWEEN 0 AND 6", name=op.f("ck_availability_rules_weekday_range")
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"],
            ["partner_profiles.user_id"],
            name=op.f("fk_availability_rules_partner_id_partner_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_availability_rules")),
    )
    op.create_index(
        "ix_availability_rules_partner_weekday",
        "availability_rules",
        ["partner_id", "weekday"],
        unique=False,
    )
    op.add_column("partner_profiles", sa.Column("timezone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("partner_profiles", "timezone")
    op.drop_index("ix_availability_rules_partner_weekday", table_name="availability_rules")
    op.drop_table("availability_rules")
    op.drop_index("ix_availability_exceptions_partner_date", table_name="availability_exceptions")
    op.drop_table("availability_exceptions")
    op.execute("DROP TYPE exception_kind")
