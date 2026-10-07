"""Postal codes: geocoded postcode cache (focus points) and an optional postcode on profiles.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08 00:36:15.837061
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "postal_codes",
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("postal_code", sa.String(length=12), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("city_name", sa.String(length=120), nullable=True),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("city_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["city_id"],
            ["cities.id"],
            name=op.f("fk_postal_codes_city_id_cities"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("country_code", "postal_code", name=op.f("pk_postal_codes")),
    )
    op.add_column("client_profiles", sa.Column("postal_code", sa.String(length=12), nullable=True))
    op.add_column("partner_profiles", sa.Column("postal_code", sa.String(length=12), nullable=True))


def downgrade() -> None:
    op.drop_column("partner_profiles", "postal_code")
    op.drop_column("client_profiles", "postal_code")
    op.drop_table("postal_codes")
