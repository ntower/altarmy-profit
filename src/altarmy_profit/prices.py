"""Price sources and the price store. All money is integer copper.

Every source (Auctionator's SavedVariables, CSV, a manual price) records a snapshot for one auction house
(`record_snapshot`). A snapshot writes observations only for items it tells something new about, and those
move `price_current`, which the engine reads: the newest price per auction house and item. Auctionator's
per-day history also fills `price_daily`. Observations are pruned after `KEEP_DAYS`; daily rows are kept.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import Connection, delete, func, select

from . import auctionator, db, schema
from .auctionator import ItemPrice

KEEP_DAYS = 90  # observations older than this are pruned (price_daily is kept)
AUCTIONATOR = "auctionator"


@dataclass(frozen=True)
class Observation:
    """One item's price in a snapshot."""

    item_id: int
    min_buyout: int
    seen_at: datetime  # when that price was on the auction house
    quantity: int | None = None
    listings: int | None = None


# --- auction houses --------------------------------------------------------------------------------
def find_auction_house(conn: Connection, game_version: str, realm: str, faction: str) -> int | None:
    """The auction house a realm/faction's characters use: their faction's, else one the realm shares."""
    t = schema.auction_houses
    for f in dict.fromkeys((faction, "")):
        found = conn.execute(
            select(t.c.id).where(t.c.game_version == game_version, t.c.realm == realm, t.c.faction == f)
        ).scalar_one_or_none()
        if found is not None:
            return int(found)
    return None


def auction_house(conn: Connection, game_version: str, realm: str, faction: str) -> int:
    """The auction house keyed (version, realm, faction), created if new. Faction "" means shared."""
    t = schema.auction_houses
    key = {"game_version": game_version, "realm": realm, "faction": faction}
    db.upsert(conn, t, [key], list(key))
    found: int = conn.execute(
        select(t.c.id).where(t.c.game_version == game_version, t.c.realm == realm, t.c.faction == faction)
    ).scalar_one()
    return found


def unnamed_auction_house(conn: Connection, game_version: str) -> int:
    """Where prices go when no realm is known (CLI use without characters)."""
    return auction_house(conn, game_version, "", "")


def auctionator_auction_house(conn: Connection, game_version: str, key: str, realm: str, faction: str) -> int:
    """The auction house Auctionator's `key` prices for a realm/faction's characters: their faction's if
    the key names it (split auction houses, "Dreamscythe Horde"), else one both factions share. Records
    the key as an alias."""
    split = bool(faction) and key.endswith(f" {faction}")
    ah = auction_house(conn, game_version, realm, faction if split else "")
    _add_alias(conn, ah, AUCTIONATOR, key)
    return ah


def find_auction_house_by_key(conn: Connection, game_version: str, key: str) -> int | None:
    """The auction house that has Auctionator realm `key` as an alias, if any."""
    t, a = schema.auction_houses, schema.realm_aliases
    found = conn.execute(
        select(t.c.id)
        .join(a, a.c.auction_house_id == t.c.id)
        .where(t.c.game_version == game_version, a.c.kind == AUCTIONATOR, a.c.value == key)
        .order_by(t.c.id)
        .limit(1)
    ).scalar_one_or_none()
    return None if found is None else int(found)


def find_auction_house_by_alias(conn: Connection, game_version: str, realm: str, faction: str) -> int | None:
    """The auction house a realm/faction's characters use when it was named after Auctionator's key (a
    scan uploaded before the characters): the key forms `service.match_auctionator_realm` tries."""
    nospace = realm.replace(" ", "")
    for key in dict.fromkeys((f"{nospace} {faction}", nospace, f"{realm} {faction}", realm)):
        found = find_auction_house_by_key(conn, game_version, key)
        if found is not None:
            return found
    return None


def auction_house_for_auctionator_key(conn: Connection, game_version: str, key: str) -> int:
    """The auction house an Auctionator realm key names: a known alias, else parsed from the key (a
    trailing faction means a split auction house; the realm is then as Auctionator spells it)."""
    found = find_auction_house_by_key(conn, game_version, key)
    if found is not None:
        return found
    realm, _, faction = key.rpartition(" ")
    if faction not in ("Horde", "Alliance") or not realm:
        realm, faction = key, ""
    return auctionator_auction_house(conn, game_version, key, realm, faction)


@dataclass(frozen=True)
class AuctionHouseInfo:
    id: int
    realm: str  # "" for the unnamed auction house
    faction: str  # "" if both factions share it
    prices: int  # items with a current price
    last_scan: datetime | None  # newest price seen


def auction_houses(conn: Connection, game_version: str) -> list[AuctionHouseInfo]:
    """The version's auction houses by realm then faction, with how many prices each has."""
    t, pc = schema.auction_houses, schema.price_current
    rows = conn.execute(
        select(t.c.id, t.c.realm, t.c.faction, func.count(pc.c.item_id), func.max(pc.c.seen_at))
        .select_from(t.outerjoin(pc, pc.c.auction_house_id == t.c.id))
        .where(t.c.game_version == game_version)
        .group_by(t.c.id, t.c.realm, t.c.faction)
        .order_by(t.c.realm, t.c.faction)
    )
    return [
        AuctionHouseInfo(r[0], r[1], r[2], int(r[3]), None if r[4] is None else db.utc(r[4])) for r in rows
    ]


def game_version_of(conn: Connection, auction_house_id: int) -> str | None:
    t = schema.auction_houses
    found = conn.execute(select(t.c.game_version).where(t.c.id == auction_house_id)).scalar_one_or_none()
    return None if found is None else str(found)


def _add_alias(conn: Connection, auction_house_id: int, kind: str, value: str) -> None:
    row = {"auction_house_id": auction_house_id, "kind": kind, "value": value}
    db.upsert(conn, schema.realm_aliases, [row], list(row))


# --- recording -------------------------------------------------------------------------------------
def record_snapshot(
    conn: Connection,
    auction_house_id: int,
    source: str,
    scanned_at: datetime,
    observations: Sequence[Observation],
    *,
    received_at: datetime | None = None,
    uploader_uid: str | None = None,
) -> int:
    """Store a snapshot and whatever it adds to `price_current`. Returns how many items it moved.

    An observation is news when the auction house has no price for the item, when it was seen on a later
    day, or when it was seen no earlier and its price differs. Re-sending the same scan writes nothing."""
    snap = schema.price_snapshots
    snapshot_id: int = conn.execute(
        snap.insert()
        .values(
            auction_house_id=auction_house_id,
            source=source,
            uploader_uid=uploader_uid,
            scanned_at=db.utc(scanned_at),
            received_at=db.utc(received_at or db.utcnow()),
            item_count=len(observations),
            status="accepted",
        )
        .returning(snap.c.id)
    ).scalar_one()
    current = _current(conn, auction_house_id)
    news = [o for o in observations if _is_news(o, current.get(o.item_id))]
    if not news:
        return 0
    conn.execute(
        schema.price_observations.insert(),
        [
            {
                "snapshot_id": snapshot_id,
                "item_id": o.item_id,
                "min_buyout": o.min_buyout,
                "quantity": o.quantity,
                "listings": o.listings,
            }
            for o in news
        ],
    )
    pc = schema.price_current
    rows = [
        {
            "auction_house_id": auction_house_id,
            "item_id": o.item_id,
            "price": o.min_buyout,
            "seen_at": db.utc(o.seen_at),
            "snapshot_id": snapshot_id,
        }
        for o in news
    ]
    db.upsert(conn, pc, rows, ["auction_house_id", "item_id"], ["price", "seen_at", "snapshot_id"])
    return len(news)


def _current(conn: Connection, auction_house_id: int) -> dict[int, tuple[int, datetime]]:
    pc = schema.price_current
    rows = conn.execute(
        select(pc.c.item_id, pc.c.price, pc.c.seen_at).where(pc.c.auction_house_id == auction_house_id)
    )
    return {r.item_id: (r.price, db.utc(r.seen_at)) for r in rows}


def _is_news(o: Observation, current: tuple[int, datetime] | None) -> bool:
    if current is None:
        return True
    price, seen_at = current
    new_seen = db.utc(o.seen_at)
    return new_seen.date() > seen_at.date() or (new_seen >= seen_at and o.min_buyout != price)


def auctionator_observations(item_prices: Mapping[int, ItemPrice], scanned_at: datetime) -> list[Observation]:
    """Observations for one realm of Auctionator's database. An item was seen at the scan time if its
    newest day is the scan's day (Auctionator counts days in local time, as does this process), else at
    the start of that day; the quantity is that day's."""
    scan = db.utc(scanned_at)
    scan_day = scan.astimezone().date()
    out = []
    for item_id, p in sorted(item_prices.items()):
        last = p.last_seen
        if last is None or last >= scan_day:
            seen_at, quantity = scan, p.days[last].available if last is not None else None
        else:
            seen_at, quantity = datetime.combine(last, time(), scan.tzinfo), p.days[last].available
        out.append(Observation(item_id, p.min_buyout, seen_at, quantity))
    return out


def record_daily(conn: Connection, auction_house_id: int, item_prices: Mapping[int, ItemPrice]) -> int:
    """Upsert Auctionator's per-day history into `price_daily`, from the newest day already stored on
    (earlier days no longer change). Returns the rows written."""
    pd = schema.price_daily
    newest = conn.execute(
        select(func.max(pd.c.day)).where(pd.c.auction_house_id == auction_house_id)
    ).scalar_one_or_none()
    rows = [
        {
            "auction_house_id": auction_house_id,
            "item_id": item_id,
            "day": day,
            "low": s.low,
            "high": s.high,
            "available": s.available,
        }
        for item_id, p in item_prices.items()
        for day, s in p.days.items()
        if newest is None or day >= newest
    ]
    db.upsert(conn, pd, rows, ["auction_house_id", "item_id", "day"], ["low", "high", "available"])
    return len(rows)


def record_auctionator(
    conn: Connection,
    auction_house_id: int,
    item_prices: Mapping[int, ItemPrice],
    scanned_at: datetime,
    uploader_uid: str | None = None,
) -> int:
    """One realm of an Auctionator scan: a snapshot plus its daily history. Returns the items moved."""
    observations = auctionator_observations(item_prices, scanned_at)
    moved = record_snapshot(
        conn, auction_house_id, AUCTIONATOR, scanned_at, observations, uploader_uid=uploader_uid
    )
    record_daily(conn, auction_house_id, item_prices)
    return moved


def prune(conn: Connection, now: datetime | None = None, keep_days: int = KEEP_DAYS) -> None:
    """Drop observations of snapshots older than `keep_days`, and those snapshots unless `price_current`
    still points at them."""
    cutoff = db.utc(now or db.utcnow()) - timedelta(days=keep_days)
    snap, obs, pc = schema.price_snapshots, schema.price_observations, schema.price_current
    old = select(snap.c.id).where(snap.c.scanned_at < cutoff)
    conn.execute(delete(obs).where(obs.c.snapshot_id.in_(old)))
    conn.execute(delete(snap).where(snap.c.scanned_at < cutoff, snap.c.id.not_in(select(pc.c.snapshot_id))))


# --- reading ---------------------------------------------------------------------------------------
def load_current(conn: Connection, auction_house_id: int | None) -> dict[int, int]:
    """{item_id: price} for the auction house; empty for None."""
    if auction_house_id is None:
        return {}
    pc = schema.price_current
    rows = conn.execute(select(pc.c.item_id, pc.c.price).where(pc.c.auction_house_id == auction_house_id))
    return {r.item_id: r.price for r in rows}


def count_current(conn: Connection, auction_house_id: int | None) -> int:
    if auction_house_id is None:
        return 0
    pc = schema.price_current
    return int(
        conn.execute(
            select(func.count()).select_from(pc).where(pc.c.auction_house_id == auction_house_id)
        ).scalar_one()
    )


def last_import(conn: Connection, auction_house_id: int | None, source: str = AUCTIONATOR) -> str | None:
    """When the newest snapshot from `source` for the auction house arrived, as UTC text."""
    if auction_house_id is None:
        return None
    snap = schema.price_snapshots
    newest = conn.execute(
        select(func.max(snap.c.received_at)).where(
            snap.c.auction_house_id == auction_house_id, snap.c.source == source
        )
    ).scalar_one_or_none()
    return db.timestamp_text(newest)


def daily(conn: Connection, auction_house_id: int, item_id: int) -> list[tuple[date, int, int, int | None]]:
    """An item's price history: (day, low, high, available), oldest first."""
    pd = schema.price_daily
    rows = conn.execute(
        select(pd.c.day, pd.c.low, pd.c.high, pd.c.available)
        .where(pd.c.auction_house_id == auction_house_id, pd.c.item_id == item_id)
        .order_by(pd.c.day)
    )
    return [(r.day, r.low, r.high, r.available) for r in rows]


# --- sources ---------------------------------------------------------------------------------------
def set_price(
    conn: Connection, auction_house_id: int, item_id: int, price: int, source: str = "manual"
) -> None:
    """One price, seen now."""
    now = db.utcnow()
    record_snapshot(conn, auction_house_id, source, now, [Observation(item_id, price, now)])


def import_csv(
    conn: Connection, game_version: str, auction_house_id: int, path: Path
) -> tuple[int, list[str]]:
    """CSV columns: `item_id` or `name`, plus `price` in copper. Returns (imported, unresolved)."""
    items = schema.items
    now = db.utcnow()
    found: dict[int, Observation] = {}
    unresolved = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            item_id = row.get("item_id")
            if not item_id:
                name = (row.get("name") or "").strip()
                match = conn.execute(
                    select(items.c.id)
                    .where(items.c.game_version == game_version, func.lower(items.c.name) == name.lower())
                    .order_by(items.c.id)
                    .limit(1)
                ).scalar_one_or_none()
                if match is None:
                    unresolved.append(name)
                    continue
                item_id = str(match)
            found[int(item_id)] = Observation(int(item_id), int(row["price"]), now)
    record_snapshot(conn, auction_house_id, "csv", now, list(found.values()))
    return len(found), unresolved


WOW_ROOTS = [
    Path(r"C:\Program Files (x86)\World of Warcraft"),
    Path(r"C:\Program Files\World of Warcraft"),
    Path(r"D:\World of Warcraft"),
]


def find_auctionator_files(
    roots: Iterable[Path] = WOW_ROOTS, flavors: Sequence[str] | None = None
) -> list[Path]:
    """Account-wide Auctionator SavedVariables under each WoW install's flavor folders (_retail_, ...), or
    only under `flavors` (e.g. ("_anniversary_",))."""
    return _find(roots, flavors, "Auctionator.lua")


def find_altarmy_files(roots: Iterable[Path] = WOW_ROOTS, flavors: Sequence[str] | None = None) -> list[Path]:
    """Alt Army's account-wide SavedVariables (characters, professions, recipes) under each WoW install,
    or only under `flavors`."""
    return _find(roots, flavors, "AltArmy_TBC.lua")


def _find(roots: Iterable[Path], flavors: Sequence[str] | None, name: str) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        for flavor in flavors if flavors is not None else ("_*_",):
            found += sorted(root.glob(f"{flavor}/WTF/Account/*/SavedVariables/{name}"))
    return found


def auctionator_realms(path: Path) -> list[str]:
    return sorted(auctionator.parse_price_database(path.read_bytes()))


def file_time(path: Path) -> datetime:
    """A file's modification time, UTC: when a SavedVariables scan was written."""
    return datetime.fromtimestamp(path.stat().st_mtime, db.utcnow().tzinfo)


def import_auctionator(
    conn: Connection, game_version: str, path: Path, realm: str | None = None
) -> tuple[str, int, int]:
    """Record one realm's scan for the auction house that realm key names. Returns (realm, prices in the
    scan, how many are not in `items`).

    `realm` may be omitted when the file holds a single realm."""
    realms = auctionator.parse_price_database(path.read_bytes())
    if realm is None:
        if len(realms) != 1:
            raise ValueError(
                f"file has {len(realms)} realms, pick one with --realm: {', '.join(sorted(realms))}"
            )
        (realm,) = realms
    elif realm not in realms:
        raise ValueError(f"realm {realm!r} not in file; found: {', '.join(sorted(realms))}")
    items = schema.items
    known: set[int] = set(
        conn.execute(select(items.c.id).where(items.c.game_version == game_version)).scalars()
    )
    item_prices = realms[realm]
    ah = auction_house_for_auctionator_key(conn, game_version, realm)
    record_auctionator(conn, ah, item_prices, file_time(path))
    return realm, len(item_prices), len(item_prices.keys() - known)
