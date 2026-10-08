"""My courts: partner_clubs becomes user_clubs so players can save their courts too.
Existing partner picks are carried over.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-08 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_clubs",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("club_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["club_id"],
            ["clubs.id"],
            name=op.f("fk_user_clubs_club_id_clubs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_clubs_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "club_id", name=op.f("pk_user_clubs")),
    )
    op.create_index(op.f("ix_user_clubs_club_id"), "user_clubs", ["club_id"], unique=False)
    op.execute(
        "INSERT INTO user_clubs (user_id, club_id, created_at)"
        " SELECT partner_id, club_id, created_at FROM partner_clubs"
    )
    op.drop_index(op.f("ix_partner_clubs_club_id"), table_name="partner_clubs")
    op.drop_table("partner_clubs")


def downgrade() -> None:
    op.create_table(
        "partner_clubs",
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("club_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["club_id"],
            ["clubs.id"],
            name=op.f("fk_partner_clubs_club_id_clubs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"],
            ["partner_profiles.user_id"],
            name=op.f("fk_partner_clubs_partner_id_partner_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("partner_id", "club_id", name=op.f("pk_partner_clubs")),
    )
    op.create_index(op.f("ix_partner_clubs_club_id"), "partner_clubs", ["club_id"], unique=False)
    # Players' courts have no place in the old table; only partners' picks go back.
    op.execute(
        "INSERT INTO partner_clubs (partner_id, club_id, created_at)"
        " SELECT uc.user_id, uc.club_id, uc.created_at FROM user_clubs uc"
        " JOIN partner_profiles pp ON pp.user_id = uc.user_id"
    )
    op.drop_index(op.f("ix_user_clubs_club_id"), table_name="user_clubs")
    op.drop_table("user_clubs")
