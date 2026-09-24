"""users and tenancy: users, typed user_settings and local_sync, owners on characters and ah_blocked

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24 22:00:00.000000

Everything stored so far becomes the local user's ("local", linked tier). SQLite rebuilds `characters` to
change its unique key, and with foreign keys on, dropping the old table cascade-deletes its professions
and recipes; so on SQLite those are saved first and put back (the rebuild keeps the character ids).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCAL = "local"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"  # how 0001's settings stored timestamps (UTC)

settings = sa.table(
    "settings", sa.column("game_version", sa.String), sa.column("key", sa.String), sa.column("value", sa.Text)
)
users = sa.table(
    "users",
    sa.column("uid", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("linked_at", sa.DateTime(timezone=True)),
    sa.column("tier", sa.String),
    sa.column("trust_score", sa.Float),
)
user_settings = sa.table(
    "user_settings",
    sa.column("user_uid", sa.String),
    sa.column("game_version", sa.String),
    sa.column("selected_realm", sa.Text),
    sa.column("selected_faction", sa.String),
    sa.column("data_version", sa.Integer),
)
local_sync = sa.table(
    "local_sync",
    sa.column("user_uid", sa.String),
    sa.column("game_version", sa.String),
    sa.column("altarmy_path", sa.Text),
    sa.column("altarmy_mtime", sa.BigInteger),
    sa.column("altarmy_synced", sa.DateTime(timezone=True)),
    sa.column("auctionator_path", sa.Text),
    sa.column("auctionator_mtime", sa.BigInteger),
    sa.column("auctionator_synced", sa.DateTime(timezone=True)),
    sa.column("auctionator_realm", sa.Text),
    sa.column("auctionator_for", sa.Text),
)
CHILDREN = ("character_professions", "character_recipes")
SETTING_KEYS = ("selected_realm", "selected_faction", "data_version")
SYNC_TEXT = ("altarmy_path", "auctionator_path", "auctionator_realm", "auctionator_for")
SYNC_INT = ("altarmy_mtime", "auctionator_mtime")
SYNC_TIME = ("altarmy_synced", "auctionator_synced")


def _owner_column() -> sa.Column[str]:
    return sa.Column("user_uid", sa.String(length=128), nullable=True)


@contextmanager
def _keeping_character_children() -> Iterator[None]:
    """Save the characters' professions and recipes around a rebuild of `characters` on SQLite."""
    conn = op.get_bind()
    if conn.dialect.name != "sqlite":
        yield
        return
    saved = {name: sa.Table(name, sa.MetaData(), autoload_with=conn) for name in CHILDREN}
    rows = {name: [dict(r) for r in conn.execute(sa.select(t)).mappings()] for name, t in saved.items()}
    yield
    for name, t in saved.items():
        conn.execute(sa.delete(t))  # whatever the cascade left
        if rows[name]:
            conn.execute(t.insert(), rows[name])


def _time(text: str | None) -> datetime | None:
    return None if not text else datetime.strptime(text[:19], TIME_FORMAT).replace(tzinfo=UTC)


def upgrade() -> None:
    conn = op.get_bind()
    op.create_table(
        "users",
        sa.Column("uid", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tier", sa.String(length=16), nullable=False),
        sa.Column("trust_score", sa.Float(), server_default="1", nullable=False),
        sa.CheckConstraint("tier IN ('free', 'linked')", name=op.f("ck_users_tier")),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk_users")),
    )
    now = datetime.now(UTC)
    conn.execute(
        users.insert().values(uid=LOCAL, created_at=now, linked_at=now, tier="linked", trust_score=1.0)
    )
    new_tables: tuple[tuple[str, list[sa.Column[Any]]], ...] = (
        (
            "user_settings",
            [
                sa.Column("selected_realm", sa.Text(), nullable=True),
                sa.Column("selected_faction", sa.String(length=16), nullable=True),
                sa.Column("data_version", sa.Integer(), server_default="0", nullable=False),
            ],
        ),
        (
            "local_sync",
            [
                sa.Column("altarmy_path", sa.Text(), nullable=True),
                sa.Column("altarmy_mtime", sa.BigInteger(), nullable=True),
                sa.Column("altarmy_synced", sa.DateTime(timezone=True), nullable=True),
                sa.Column("auctionator_path", sa.Text(), nullable=True),
                sa.Column("auctionator_mtime", sa.BigInteger(), nullable=True),
                sa.Column("auctionator_synced", sa.DateTime(timezone=True), nullable=True),
                sa.Column("auctionator_realm", sa.Text(), nullable=True),
                sa.Column("auctionator_for", sa.Text(), nullable=True),
            ],
        ),
    )
    for name, columns in new_tables:
        op.create_table(
            name,
            sa.Column("user_uid", sa.String(length=128), nullable=False),
            sa.Column("game_version", sa.String(length=16), nullable=False),
            *columns,
            sa.ForeignKeyConstraint(
                ["game_version"], ["game_versions.id"], name=op.f(f"fk_{name}_game_version_game_versions")
            ),
            sa.ForeignKeyConstraint(
                ["user_uid"], ["users.uid"], name=op.f(f"fk_{name}_user_uid_users"), ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("user_uid", "game_version", name=op.f(f"pk_{name}")),
        )
    _pivot_settings(conn)
    op.drop_table("settings")

    op.add_column("characters", _owner_column())
    conn.execute(sa.text("UPDATE characters SET user_uid = :uid"), {"uid": LOCAL})
    with _keeping_character_children(), op.batch_alter_table("characters") as batch_op:
        batch_op.alter_column("user_uid", existing_type=sa.String(length=128), nullable=False)
        batch_op.drop_constraint("uq_characters_game_version_realm_name", type_="unique")
        batch_op.create_unique_constraint(
            op.f("uq_characters_user_uid_game_version_realm_name"),
            ["user_uid", "game_version", "realm", "name"],
        )
        batch_op.create_foreign_key(
            op.f("fk_characters_user_uid_users"), "users", ["user_uid"], ["uid"], ondelete="CASCADE"
        )

    op.add_column("ah_blocked", _owner_column())
    conn.execute(sa.text("UPDATE ah_blocked SET user_uid = :uid"), {"uid": LOCAL})
    with op.batch_alter_table("ah_blocked") as batch_op:
        batch_op.alter_column("user_uid", existing_type=sa.String(length=128), nullable=False)
        batch_op.drop_constraint("pk_ah_blocked", type_="primary")
        batch_op.create_primary_key("pk_ah_blocked", ["user_uid", "game_version", "item_id"])
        batch_op.create_foreign_key(
            op.f("fk_ah_blocked_user_uid_users"), "users", ["user_uid"], ["uid"], ondelete="CASCADE"
        )


def _pivot_settings(conn: sa.Connection) -> None:
    """0001's key-value settings (one set per game version) as the local user's typed rows."""
    by_version: dict[str, dict[str, str]] = {}
    for gv, key, value in conn.execute(sa.select(settings.c.game_version, settings.c.key, settings.c.value)):
        by_version.setdefault(gv, {})[key] = value
    for gv, kv in sorted(by_version.items()):
        conn.execute(
            user_settings.insert().values(
                user_uid=LOCAL,
                game_version=gv,
                selected_realm=kv.get("selected_realm"),
                selected_faction=kv.get("selected_faction"),
                data_version=int(kv.get("data_version") or 0),
            )
        )
        sync: dict[str, object] = {k: kv.get(k) for k in SYNC_TEXT}
        sync |= {k: int(kv[k]) if kv.get(k) else None for k in SYNC_INT}
        sync |= {k: _time(kv.get(k)) for k in SYNC_TIME}
        if any(v is not None for v in sync.values()):
            conn.execute(local_sync.insert().values(user_uid=LOCAL, game_version=gv, **sync))


def downgrade() -> None:
    """Back to one key-value settings set per game version: the local user's; other users' state is lost."""
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM ah_blocked WHERE user_uid <> :uid"), {"uid": LOCAL})
    with op.batch_alter_table("ah_blocked") as batch_op:
        batch_op.drop_constraint(op.f("fk_ah_blocked_user_uid_users"), type_="foreignkey")
        batch_op.drop_constraint("pk_ah_blocked", type_="primary")
        batch_op.create_primary_key("pk_ah_blocked", ["game_version", "item_id"])
        batch_op.drop_column("user_uid")

    conn.execute(sa.text("DELETE FROM characters WHERE user_uid <> :uid"), {"uid": LOCAL})
    with _keeping_character_children(), op.batch_alter_table("characters") as batch_op:
        batch_op.drop_constraint(op.f("fk_characters_user_uid_users"), type_="foreignkey")
        batch_op.drop_constraint(op.f("uq_characters_user_uid_game_version_realm_name"), type_="unique")
        batch_op.create_unique_constraint(
            "uq_characters_game_version_realm_name", ["game_version", "realm", "name"]
        )
        batch_op.drop_column("user_uid")

    op.create_table(
        "settings",
        sa.Column("game_version", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["game_version"], ["game_versions.id"], name=op.f("fk_settings_game_version_game_versions")
        ),
        sa.PrimaryKeyConstraint("game_version", "key", name=op.f("pk_settings")),
    )
    rows: list[dict[str, str]] = []
    for r in conn.execute(sa.select(user_settings).where(user_settings.c.user_uid == LOCAL)).mappings():
        kv = {k: r[k] for k in SETTING_KEYS}
        rows += [
            {"game_version": r["game_version"], "key": k, "value": str(v)}
            for k, v in kv.items()
            if v is not None
        ]
    for r in conn.execute(sa.select(local_sync).where(local_sync.c.user_uid == LOCAL)).mappings():
        for k in (*SYNC_TEXT, *SYNC_INT):
            if r[k] is not None:
                rows.append({"game_version": r["game_version"], "key": k, "value": str(r[k])})
        for k in SYNC_TIME:
            if r[k] is not None:
                t = r[k] if r[k].tzinfo else r[k].replace(tzinfo=UTC)
                rows.append(
                    {
                        "game_version": r["game_version"],
                        "key": k,
                        "value": t.astimezone(UTC).strftime(TIME_FORMAT),
                    }
                )
    if rows:
        conn.execute(settings.insert(), rows)
    op.drop_table("local_sync")
    op.drop_table("user_settings")
    op.drop_table("users")
