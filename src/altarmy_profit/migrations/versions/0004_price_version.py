"""price version: auction_houses.price_version, bumped by the merge job (one additive column)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-24 20:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A plain ADD COLUMN, also on SQLite: a batch rebuild of auction_houses would cascade its drop into
    # every price table.
    op.add_column(
        "auction_houses", sa.Column("price_version", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    # Native DROP COLUMN (SQLite 3.35+) for the same reason: no table rebuild.
    op.execute("ALTER TABLE auction_houses DROP COLUMN price_version")
