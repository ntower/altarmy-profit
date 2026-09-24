"""Users and their per-version state rows: settings (selection, data version) and local mode's addon file
sync. Functions take a `Connection` and never commit."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Table, select

from . import db, schema
from .auth import User


def ensure_user(conn: Connection, user: User) -> None:
    """Create the user's row on first sight, and follow tier changes (the first link sets `linked_at`)."""
    t = schema.users
    row = conn.execute(select(t.c.tier, t.c.linked_at).where(t.c.uid == user.uid)).one_or_none()
    now = db.utcnow()
    linked_at = now if user.linked else None
    if row is None:
        db.upsert(
            conn,
            t,
            [{"uid": user.uid, "created_at": now, "linked_at": linked_at, "tier": user.tier}],
            ["uid"],
            update=[],
        )
    elif row.tier != user.tier:
        values: dict[str, Any] = {"tier": user.tier}
        if user.linked and row.linked_at is None:
            values["linked_at"] = now
        conn.execute(t.update().where(t.c.uid == user.uid).values(**values))


@dataclass(frozen=True)
class UserSettings:
    selected_realm: str | None = None  # with selected_faction: whose characters count
    selected_faction: str | None = None
    data_version: int = 0  # bumped when the user's characters or prices were re-imported


@dataclass(frozen=True)
class LocalSync:
    """Local mode's addon file sync state: which files, their last seen mtime (ns) and sync time."""

    altarmy_path: str | None = None
    altarmy_mtime: int | None = None
    altarmy_synced: datetime | None = None
    auctionator_path: str | None = None
    auctionator_mtime: int | None = None
    auctionator_synced: datetime | None = None
    auctionator_realm: str | None = None  # Auctionator's key for the selection; "" if it has none
    auctionator_for: str | None = None  # "realm\tfaction" the prices were recorded for


def _get(conn: Connection, t: Table, user_uid: str, game_version: str) -> dict[str, Any] | None:
    row = (
        conn.execute(select(t).where(t.c.user_uid == user_uid, t.c.game_version == game_version))
        .mappings()
        .one_or_none()
    )
    return None if row is None else dict(row)


def _put(conn: Connection, t: Table, user_uid: str, game_version: str, values: dict[str, Any]) -> None:
    row = {"user_uid": user_uid, "game_version": game_version, **values}
    db.upsert(conn, t, [row], ["user_uid", "game_version"])


def get_settings(conn: Connection, user_uid: str, game_version: str) -> UserSettings:
    row = _get(conn, schema.user_settings, user_uid, game_version)
    if row is None:
        return UserSettings()
    return UserSettings(**{f.name: row[f.name] for f in fields(UserSettings)})


def update_settings(conn: Connection, user_uid: str, game_version: str, **changes: Any) -> UserSettings:
    """Change some settings (keyword per `UserSettings` field); returns them all."""
    new = replace(get_settings(conn, user_uid, game_version), **changes)
    _put(conn, schema.user_settings, user_uid, game_version, asdict(new))
    return new


def get_sync(conn: Connection, user_uid: str, game_version: str) -> LocalSync:
    row = _get(conn, schema.local_sync, user_uid, game_version)
    if row is None:
        return LocalSync()
    values = {f.name: row[f.name] for f in fields(LocalSync)}
    for key in ("altarmy_synced", "auctionator_synced"):
        if values[key] is not None:
            values[key] = db.utc(values[key])
    return LocalSync(**values)


def update_sync(conn: Connection, user_uid: str, game_version: str, **changes: Any) -> LocalSync:
    """Change some sync fields (keyword per `LocalSync` field); returns them all."""
    new = replace(get_sync(conn, user_uid, game_version), **changes)
    _put(conn, schema.local_sync, user_uid, game_version, asdict(new))
    return new
