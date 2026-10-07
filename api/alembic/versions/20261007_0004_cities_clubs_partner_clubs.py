"""Club discovery: geocoded cities (+ input aliases), tennis clubs/courts with PostGIS locations,
and the clubs each partner plays at.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07 22:09:26.696200
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("bbox_south", sa.Float(), nullable=False),
        sa.Column("bbox_west", sa.Float(), nullable=False),
        sa.Column("bbox_north", sa.Float(), nullable=False),
        sa.Column("bbox_east", sa.Float(), nullable=False),
        sa.Column("geocoder", sa.String(length=32), nullable=False),
        sa.Column("geocoder_place_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "ready", "failed", name="discovery_status"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("club_count", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cities")),
        sa.UniqueConstraint("key", name=op.f("uq_cities_key")),
    )
    op.create_table(
        "city_aliases",
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("city_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["city_id"],
            ["cities.id"],
            name=op.f("fk_city_aliases_city_id_cities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_city_aliases")),
    )
    op.create_table(
        "clubs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("city_id", sa.UUID(), nullable=False),
        sa.Column("external_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("club", "sports_centre", "public_courts", name="club_kind"),
            nullable=False,
        ),
        sa.Column(
            "location",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeogFromText",
                name="geography",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("court_count", sa.Integer(), nullable=True),
        sa.Column("surface", sa.String(length=64), nullable=True),
        sa.Column("access", sa.String(length=32), nullable=True),
        sa.Column("lit", sa.Boolean(), nullable=True),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["city_id"], ["cities.id"], name=op.f("fk_clubs_city_id_cities"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clubs")),
        sa.UniqueConstraint("external_key", name=op.f("uq_clubs_external_key")),
    )
    op.create_index(op.f("ix_clubs_city_id"), "clubs", ["city_id"], unique=False)
    op.create_index(
        "ix_clubs_location", "clubs", ["location"], unique=False, postgresql_using="gist"
    )
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


def downgrade() -> None:
    op.drop_index(op.f("ix_partner_clubs_club_id"), table_name="partner_clubs")
    op.drop_table("partner_clubs")
    op.drop_index("ix_clubs_location", table_name="clubs", postgresql_using="gist")
    op.drop_index(op.f("ix_clubs_city_id"), table_name="clubs")
    op.drop_table("clubs")
    op.drop_table("city_aliases")
    op.drop_table("cities")
    op.execute("DROP TYPE club_kind")
    op.execute("DROP TYPE discovery_status")
