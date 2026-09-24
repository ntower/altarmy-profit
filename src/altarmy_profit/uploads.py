"""Addon files users upload (from the browser or the CLI watcher): parse, store what they tell us, keep a
history. Functions taking a `Connection` never commit.

An Alt Army file replaces the uploader's characters of that game version. An Auctionator file records a
snapshot for every realm it has prices for, whoever uploads it, so auction houses pool everyone's scans
(the newest `seen_at` wins, see `prices.record_snapshot`). The file itself is never stored.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Connection, func, select

from . import altarmy, auctionator, db, prices, schema, service, store

MAX_BYTES = 32 * 2**20  # decompressed; the biggest real file (TBC Auctionator.lua) is about 5 MB
RATE_LIMIT = 60  # uploads per user per hour
SCAN_WINDOW = timedelta(days=30)  # a file's modified time is trusted this far back
GZIP_MAGIC = b"\x1f\x8b"


class RateLimited(Exception):
    pass


class TooLarge(Exception):
    pass


@dataclass(frozen=True)
class RealmPrices:
    key: str  # Auctionator's realm key, e.g. "Dreamscythe Horde"
    auction_house_id: int
    realm: str
    faction: str
    items: int  # items priced in the scan
    moved: int  # of them, items whose current price changed


@dataclass(frozen=True)
class Imported:
    kind: str  # altarmy | auctionator
    characters: int = 0
    groups: tuple[tuple[str, str, int], ...] = ()  # (realm, faction, characters)
    realms: tuple[RealmPrices, ...] = ()

    @property
    def auction_house_ids(self) -> frozenset[int]:
        return frozenset(r.auction_house_id for r in self.realms)

    @property
    def detail(self) -> str:
        if self.kind == "altarmy":
            where = ", ".join(f"{r} ({f or 'no faction'}): {n}" for r, f, n in self.groups)
            return f"{self.characters} characters" + (f" on {where}" if where else "")
        if not self.realms:
            return "No realm in the file has prices."
        return "; ".join(f"{r.key}: {r.items} prices, {r.moved} changed" for r in self.realms)


@dataclass(frozen=True)
class UploadRow:
    id: int
    game_version: str
    kind: str
    via: str
    size: int
    received_at: datetime
    outcome: str
    detail: str


def decompress(data: bytes, limit: int = MAX_BYTES) -> bytes:
    """`data` as it was before gzip (plain data passes through); TooLarge past `limit` bytes."""
    if not data.startswith(GZIP_MAGIC):
        if len(data) > limit:
            raise TooLarge
        return data
    d = zlib.decompressobj(wbits=31)
    try:
        out = d.decompress(data, limit + 1)
    except zlib.error as e:
        raise ValueError(f"not a valid gzip file: {e}") from e
    if len(out) > limit:
        raise TooLarge
    return out


def scan_time(modified_at: datetime | None, now: datetime) -> datetime:
    """When the file's scan was taken: its modified time, never in the future nor before SCAN_WINDOW."""
    if modified_at is None:
        return now
    return min(max(db.utc(modified_at), now - SCAN_WINDOW), now)


def ingest(
    conn: Connection,
    user_uid: str,
    game_version: str,
    kind: str,
    data: bytes,
    modified_at: datetime | None,
    *,
    now: datetime | None = None,
) -> Imported:
    """Store an uploaded file of `kind`; ValueError if it is not one."""
    now = now or db.utcnow()
    if kind == "altarmy":
        return ingest_altarmy(conn, user_uid, game_version, data)
    if kind == "auctionator":
        return ingest_auctionator(conn, user_uid, game_version, data, scan_time(modified_at, now))
    raise ValueError(f"unknown upload kind {kind!r}")


def ingest_altarmy(conn: Connection, user_uid: str, game_version: str, data: bytes) -> Imported:
    chars = altarmy.parse_characters(data)
    store.save_characters(conn, user_uid, game_version, chars)
    service.bump_data_version(conn, user_uid, game_version)
    groups = tuple((g.realm, g.faction, len(g.characters)) for g in altarmy.groups(chars))
    return Imported("altarmy", characters=len(chars), groups=groups)


def ingest_auctionator(
    conn: Connection, user_uid: str, game_version: str, data: bytes, scanned_at: datetime
) -> Imported:
    realms = auctionator.parse_price_database(data)
    groups = altarmy.groups(store.load_characters(conn, user_uid, game_version))
    recorded = []
    for key, item_prices in sorted(realms.items()):
        if not item_prices:
            continue
        ah = _auction_house(conn, game_version, key, [(g.realm, g.faction) for g in groups])
        moved = prices.record_auctionator(conn, ah, item_prices, scanned_at, uploader_uid=user_uid)
        realm, faction = _name(conn, ah)
        recorded.append(RealmPrices(key, ah, realm, faction, len(item_prices), moved))
    if recorded:
        prices.prune(conn)
        service.bump_data_version(conn, user_uid, game_version)
    return Imported("auctionator", realms=tuple(recorded))


def _auction_house(conn: Connection, game_version: str, key: str, groups: list[tuple[str, str]]) -> int:
    """The auction house an Auctionator key prices: one that already has the key as an alias, else the
    one of the uploader's characters it matches (named as the characters' realm), else parsed from the
    key. The alias comes first so a realm never splits into two auction houses."""
    known = prices.find_auction_house_by_key(conn, game_version, key)
    if known is not None:
        return known
    for realm, faction in groups:
        if service.match_auctionator_realm([key], realm, faction) == key:
            return prices.auctionator_auction_house(conn, game_version, key, realm, faction)
    return prices.auction_house_for_auctionator_key(conn, game_version, key)


def _name(conn: Connection, auction_house_id: int) -> tuple[str, str]:
    t = schema.auction_houses
    row = conn.execute(select(t.c.realm, t.c.faction).where(t.c.id == auction_house_id)).one()
    return str(row.realm), str(row.faction)


# --- history ---------------------------------------------------------------------------------------
def record_upload(
    conn: Connection,
    user_uid: str,
    game_version: str,
    kind: str,
    via: str,
    size: int,
    outcome: str,
    detail: str,
    *,
    now: datetime | None = None,
) -> None:
    conn.execute(
        schema.uploads.insert().values(
            user_uid=user_uid,
            game_version=game_version,
            kind=kind,
            via=via,
            size=size,
            received_at=now or db.utcnow(),
            outcome=outcome,
            detail=detail[:1000],
        )
    )


def check_rate(conn: Connection, user_uid: str, *, now: datetime | None = None) -> None:
    """RateLimited if the user has uploaded RATE_LIMIT files within the past hour."""
    t = schema.uploads
    since = (now or db.utcnow()) - timedelta(hours=1)
    count = conn.execute(
        select(func.count()).where(t.c.user_uid == user_uid, t.c.received_at > since)
    ).scalar_one()
    if count >= RATE_LIMIT:
        raise RateLimited


def recent(conn: Connection, user_uid: str, limit: int = 20) -> list[UploadRow]:
    """The user's newest uploads first."""
    t = schema.uploads
    rows = conn.execute(
        select(
            t.c.id, t.c.game_version, t.c.kind, t.c.via, t.c.size, t.c.received_at, t.c.outcome, t.c.detail
        )
        .where(t.c.user_uid == user_uid)
        .order_by(t.c.received_at.desc(), t.c.id.desc())
        .limit(limit)
    )
    return [UploadRow(r[0], r[1], r[2], r[3], r[4], db.utc(r[5]), r[6], r[7]) for r in rows]
