"""uploads and api keys: upload history and the watcher's API keys (new tables only)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-24 16:50:17.508769
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_uid", sa.String(length=128), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_uid"], ["users.uid"], name=op.f("fk_api_keys_user_uid_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_keys_key_hash")),
    )
    op.create_table(
        "uploads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_uid", sa.String(length=128), nullable=False),
        sa.Column("game_version", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("via", sa.String(length=16), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.CheckConstraint("kind IN ('altarmy', 'auctionator')", name=op.f("ck_uploads_kind")),
        sa.CheckConstraint("outcome IN ('accepted', 'rejected')", name=op.f("ck_uploads_outcome")),
        sa.CheckConstraint("via IN ('browser', 'watcher')", name=op.f("ck_uploads_via")),
        sa.ForeignKeyConstraint(
            ["game_version"], ["game_versions.id"], name=op.f("fk_uploads_game_version_game_versions")
        ),
        sa.ForeignKeyConstraint(
            ["user_uid"], ["users.uid"], name=op.f("fk_uploads_user_uid_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
    )
    with op.batch_alter_table("uploads", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_uploads_user_uid_received_at"), ["user_uid", "received_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("uploads", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_uploads_user_uid_received_at"))

    op.drop_table("uploads")
    op.drop_table("api_keys")
