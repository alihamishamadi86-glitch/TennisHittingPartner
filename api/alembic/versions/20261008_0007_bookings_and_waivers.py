"""Bookings (with DB-enforced no-overlap rules) and versioned waivers; seeds waiver v1.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08 00:55:10.431119
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Initial waiver text. Have it reviewed by a lawyer for your jurisdiction before launch;
# publish changes as a new version (clients re-sign the active version).
WAIVER_V1_TITLE = "Participation Waiver and Release of Liability"
WAIVER_V1_BODY = "\n\n".join(
    [
        "Please read carefully. By signing, you agree to the following for every session you book.",
        "1. Voluntary participation and risks. Tennis is a physical activity with inherent risks, including muscle strains, sprains, falls, impact from balls or rackets, heat-related illness and, rarely, serious injury. You take part voluntarily and accept these risks.",
        "2. Fitness to play. You confirm you are physically able to play tennis and have no medical condition that makes it unsafe for you, or that you have medical clearance to play. You will stop and tell your partner if you feel unwell.",
        "3. Courts and equipment. Sessions take place at public or private courts that we don't own or operate. You are responsible for any court booking or access fee at the venue unless the session description says otherwise, and for following the venue's rules. Bring your own racket, suitable shoes and water.",
        "4. Hitting partners. Partners are independent players screened by the agency for playing level; they are not certified coaches and don't provide instruction or medical advice.",
        "5. Release. To the fullest extent permitted by law, you release the agency, its partners and staff from liability for injury, loss or damage arising from your participation, except where caused by gross negligence or wilful misconduct.",
        "6. Policies. You agree to the cancellation policy shown when booking (free cancellation up to 12 hours before the session; a 50% fee within 12 hours) and that rained-out sessions are credited for rebooking within 30 days.",
        "7. Age. You confirm you are 18 or older.",
    ]
)


def upgrade() -> None:
    op.create_table(
        "waiver_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_waiver_versions")),
        sa.UniqueConstraint("version", name=op.f("uq_waiver_versions_version")),
    )
    op.create_table(
        "waiver_signatures",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("waiver_version_id", sa.UUID(), nullable=False),
        sa.Column("signed_name", sa.String(length=200), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "signed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_waiver_signatures_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["waiver_version_id"],
            ["waiver_versions.id"],
            name=op.f("fk_waiver_signatures_waiver_version_id_waiver_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_waiver_signatures")),
    )
    op.create_index(
        op.f("ix_waiver_signatures_user_id"), "waiver_signatures", ["user_id"], unique=False
    )
    op.create_table(
        "bookings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("club_id", sa.UUID(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "held",
                "confirmed",
                "completed",
                "expired",
                "cancelled_free",
                "cancelled_late",
                "partner_cancelled",
                "rained_out",
                "no_show",
                name="booking_status",
            ),
            nullable=False,
        ),
        sa.Column("hold_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_note", sa.Text(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_id", sa.UUID(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=False),
        sa.Column("cancellation_fee_fraction", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("credit_issued", sa.Boolean(), nullable=False),
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
            ["cancelled_by_id"],
            ["users.id"],
            name=op.f("fk_bookings_cancelled_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["users.id"],
            name=op.f("fk_bookings_client_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["club_id"], ["clubs.id"], name=op.f("fk_bookings_club_id_clubs"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"],
            ["partner_profiles.user_id"],
            name=op.f("fk_bookings_partner_id_partner_profiles"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bookings")),
    )
    op.create_index(op.f("ix_bookings_client_id"), "bookings", ["client_id"], unique=False)
    op.create_index(op.f("ix_bookings_partner_id"), "bookings", ["partner_id"], unique=False)
    op.create_index("ix_bookings_starts_at", "bookings", ["starts_at"], unique=False)
    op.create_index(
        "ix_bookings_status_hold_expires_at",
        "bookings",
        ["status", "hold_expires_at"],
        unique=False,
    )

    # No double-booking, enforced by Postgres (btree_gist, installed in 0001). Only held or
    # confirmed bookings occupy time. Partner ranges include the travel buffer
    # (blocked_until), so back-to-back sessions always leave time to get between courts.
    op.execute(
        """
        ALTER TABLE bookings ADD CONSTRAINT ex_bookings_partner_time
        EXCLUDE USING gist (partner_id WITH =, tstzrange(starts_at, blocked_until) WITH &&)
        WHERE (status IN ('held', 'confirmed'))
        """
    )
    op.execute(
        """
        ALTER TABLE bookings ADD CONSTRAINT ex_bookings_client_time
        EXCLUDE USING gist (client_id WITH =, tstzrange(starts_at, ends_at) WITH &&)
        WHERE (status IN ('held', 'confirmed'))
        """
    )
    op.create_check_constraint("ends_after_start", "bookings", "ends_at > starts_at")
    op.create_check_constraint("buffer_after_end", "bookings", "blocked_until >= ends_at")

    op.execute(
        sa.text(
            "INSERT INTO waiver_versions (id, version, title, body, active) "
            "VALUES (gen_random_uuid(), 1, :title, :body, true)"
        ).bindparams(title=WAIVER_V1_TITLE, body=WAIVER_V1_BODY)
    )


def downgrade() -> None:
    op.drop_index("ix_bookings_status_hold_expires_at", table_name="bookings")
    op.drop_index("ix_bookings_starts_at", table_name="bookings")
    op.drop_index(op.f("ix_bookings_partner_id"), table_name="bookings")
    op.drop_index(op.f("ix_bookings_client_id"), table_name="bookings")
    op.drop_table("bookings")
    op.drop_index(op.f("ix_waiver_signatures_user_id"), table_name="waiver_signatures")
    op.drop_table("waiver_signatures")
    op.drop_table("waiver_versions")
    op.execute("DROP TYPE booking_status")
