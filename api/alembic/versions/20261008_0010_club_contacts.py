"""Club contacts: email, court-booking link, website source and enrichment status.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-08 14:40:28.493490
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clubs", sa.Column("email", sa.String(length=254), nullable=True))
    op.add_column("clubs", sa.Column("booking_url", sa.String(length=500), nullable=True))
    op.add_column("clubs", sa.Column("website_source", sa.String(length=16), nullable=True))
    op.add_column(
        "clubs", sa.Column("contacts_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("clubs", sa.Column("contacts_status", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("clubs", "contacts_status")
    op.drop_column("clubs", "contacts_checked_at")
    op.drop_column("clubs", "website_source")
    op.drop_column("clubs", "booking_url")
    op.drop_column("clubs", "email")
