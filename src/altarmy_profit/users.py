"""Users, their per-version state rows (settings: selection, data version; local mode's addon file sync)
and their API keys. Functions take a `Connection` and never commit."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Table, delete, select

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


TRUST_GAIN = 0.1  # per screened scan that was accepted, up to 1
TRUST_LOSS = 0.5  # a quarantined scan multiplies the trust by this


def trust(conn: Connection, user_uid: str) -> float:
    """How far the user's scans are trusted, 0..1 (1 for unknown users): `prices.screen` allows fewer
    wild prices the lower it is."""
    t = schema.users
    found = conn.execute(select(t.c.trust_score).where(t.c.uid == user_uid)).scalar_one_or_none()
    return 1.0 if found is None else float(found)


def adjust_trust(conn: Connection, user_uid: str, *, quarantined: bool) -> float:
    """Feed a screened scan back into the user's trust: halved by a quarantine, else raised a little."""
    now = trust(conn, user_uid)
    new = now * TRUST_LOSS if quarantined else min(1.0, now + TRUST_GAIN)
    t = schema.users
    conn.execute(t.update().where(t.c.uid == user_uid).values(trust_score=new))
    return new


def delete_user(conn: Connection, user_uid: str) -> None:
    """Delete the user and everything they own (characters, settings, AH blocks, uploads, API keys cascade).
    Their price snapshots stay in the pool, no longer attributed to them."""
    if user_uid == db.LOCAL_UID:
        raise ValueError("the local user can't be deleted")
    snap = schema.price_snapshots
    conn.execute(snap.update().where(snap.c.uploader_uid == user_uid).values(uploader_uid=None))
    conn.execute(delete(schema.users).where(schema.users.c.uid == user_uid))


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


# --- API keys (the CLI watcher's credentials) ------------------------------------------------------
KEY_PREFIX = "ak_"


@dataclass(frozen=True)
class ApiKey:
    id: int
    prefix: str  # the key's first characters, to tell keys apart
    label: str
    created_at: datetime
    last_used_at: datetime | None


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(conn: Connection, user_uid: str, label: str) -> tuple[ApiKey, str]:
    """A new key for the user: its row and the key itself, which is not stored and never shown again."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    now = db.utcnow()
    t = schema.api_keys
    row = {"user_uid": user_uid, "key_hash": _hash(key), "prefix": key[:8], "label": label, "created_at": now}
    key_id: int = conn.execute(t.insert().values(**row).returning(t.c.id)).scalar_one()
    return ApiKey(key_id, key[:8], label, now, None), key


def list_keys(conn: Connection, user_uid: str) -> list[ApiKey]:
    """The user's keys, newest first."""
    t = schema.api_keys
    rows = conn.execute(
        select(t.c.id, t.c.prefix, t.c.label, t.c.created_at, t.c.last_used_at)
        .where(t.c.user_uid == user_uid)
        .order_by(t.c.created_at.desc(), t.c.id.desc())
    )
    return [
        ApiKey(
            r.id,
            r.prefix,
            r.label,
            db.utc(r.created_at),
            None if r.last_used_at is None else db.utc(r.last_used_at),
        )
        for r in rows
    ]


def revoke_key(conn: Connection, user_uid: str, key_id: int) -> bool:
    """Delete one of the user's keys; False if they have no such key."""
    t = schema.api_keys
    return conn.execute(delete(t).where(t.c.id == key_id, t.c.user_uid == user_uid)).rowcount > 0


def user_for_key(conn: Connection, key: str) -> User | None:
    """Whose key this is (with their stored tier), noting its use; None if unknown or revoked."""
    k, u = schema.api_keys, schema.users
    row = conn.execute(
        select(k.c.id, u.c.uid, u.c.tier).join(u, u.c.uid == k.c.user_uid).where(k.c.key_hash == _hash(key))
    ).one_or_none()
    if row is None:
        return None
    conn.execute(k.update().where(k.c.id == row.id).values(last_used_at=db.utcnow()))
    return User(row.uid, "linked" if row.tier == "linked" else "free")
