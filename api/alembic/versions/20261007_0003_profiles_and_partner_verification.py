"""Profiles: client/partner level profiles and the partner verification audit trail.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-07 00:19:56.904527
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client_profiles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("goals", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("ntrp_rating", sa.Numeric(precision=2, scale=1), nullable=False),
        sa.Column("utr_rating", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("years_playing", sa.Integer(), nullable=True),
        sa.Column(
            "dominant_hand",
            sa.Enum("right", "left", "ambidextrous", name="dominant_hand"),
            nullable=True,
        ),
        sa.Column(
            "play_style",
            sa.Enum(
                "baseliner", "all_court", "serve_and_volley", "counterpuncher", name="play_style"
            ),
            nullable=True,
        ),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
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
            "ntrp_rating * 2 = floor(ntrp_rating * 2)",
            name=op.f("ck_client_profiles_ntrp_half_steps"),
        ),
        sa.CheckConstraint(
            "ntrp_rating BETWEEN 1.5 AND 7.0", name=op.f("ck_client_profiles_ntrp_range")
        ),
        sa.CheckConstraint(
            "utr_rating IS NULL OR utr_rating BETWEEN 1 AND 16.5",
            name=op.f("ck_client_profiles_utr_range"),
        ),
        sa.CheckConstraint(
            "years_playing IS NULL OR years_playing BETWEEN 0 AND 80",
            name=op.f("ck_client_profiles_years_range"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_client_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_client_profiles")),
    )
    op.create_table(
        "partner_profiles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "background",
            sa.Enum(
                "professional",
                "college",
                "high_school_varsity",
                "club",
                "coach",
                "other",
                name="partner_background",
            ),
            nullable=True,
        ),
        sa.Column("bio", sa.Text(), nullable=False),
        sa.Column("service_radius_km", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "applied", "screened", "approved", "rejected", name="partner_status"),
            nullable=False,
        ),
        sa.Column("verified_ntrp_rating", sa.Numeric(precision=2, scale=1), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ntrp_rating", sa.Numeric(precision=2, scale=1), nullable=False),
        sa.Column("utr_rating", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("years_playing", sa.Integer(), nullable=True),
        sa.Column(
            "dominant_hand",
            sa.Enum("right", "left", "ambidextrous", name="dominant_hand"),
            nullable=True,
        ),
        sa.Column(
            "play_style",
            sa.Enum(
                "baseliner", "all_court", "serve_and_volley", "counterpuncher", name="play_style"
            ),
            nullable=True,
        ),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
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
            "ntrp_rating * 2 = floor(ntrp_rating * 2)",
            name=op.f("ck_client_profiles_ntrp_half_steps"),
        ),
        sa.CheckConstraint(
            "ntrp_rating BETWEEN 1.5 AND 7.0", name=op.f("ck_client_profiles_ntrp_range")
        ),
        sa.CheckConstraint(
            "service_radius_km BETWEEN 1 AND 100", name=op.f("ck_partner_profiles_radius_range")
        ),
        sa.CheckConstraint(
            "utr_rating IS NULL OR utr_rating BETWEEN 1 AND 16.5",
            name=op.f("ck_client_profiles_utr_range"),
        ),
        sa.CheckConstraint(
            "verified_ntrp_rating IS NULL OR verified_ntrp_rating BETWEEN 1.5 AND 7.0",
            name=op.f("ck_partner_profiles_verified_ntrp_range"),
        ),
        sa.CheckConstraint(
            "years_playing IS NULL OR years_playing BETWEEN 0 AND 80",
            name=op.f("ck_client_profiles_years_range"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_partner_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_partner_profiles")),
    )
    op.create_table(
        "partner_verifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column(
            "from_status",
            sa.Enum("draft", "applied", "screened", "approved", "rejected", name="partner_status"),
            nullable=False,
        ),
        sa.Column(
            "to_status",
            sa.Enum("draft", "applied", "screened", "approved", "rejected", name="partner_status"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_partner_verifications_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"],
            ["partner_profiles.user_id"],
            name=op.f("fk_partner_verifications_partner_id_partner_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_partner_verifications")),
    )
    op.create_index(
        op.f("ix_partner_verifications_partner_id"),
        "partner_verifications",
        ["partner_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_partner_verifications_partner_id"), table_name="partner_verifications")
    op.drop_table("partner_verifications")
    op.drop_table("partner_profiles")
    op.drop_table("client_profiles")
    for enum_type in ("partner_status", "partner_background", "play_style", "dominant_hand"):
        op.execute(f"DROP TYPE {enum_type}")
