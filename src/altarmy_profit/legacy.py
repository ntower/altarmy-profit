"""Import the SQLite files of older releases into the current database.

Before Phase 2 each game version had its own file, `data/altarmy-profit-<version>.db` (raw SQL schema
below), and before that a single `data/altarmy-profit.db`. `import_version_files` copies each version file
into the shared database (game data; the local user's settings, characters and AH blocks; prices as
snapshots) in one transaction, then renames it to `*.imported` so it is never imported twice and stays as
a backup.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Table, delete

from . import db, prices, schema, users, versions
from .db import LOCAL_UID
from .prices import Observation
from .versions import GameVersion

LEGACY_DB = Path("data/altarmy-profit.db")  # the single database from before game versions
IMPORTED_SUFFIX = ".imported"

# The per-version file's schema as the last release created it (init_schema brings older files up to it).
SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    quality INTEGER NOT NULL DEFAULT 1,
    item_level INTEGER NOT NULL DEFAULT 0,
    required_level INTEGER NOT NULL DEFAULT 0,
    class_id INTEGER NOT NULL DEFAULT 0,
    subclass_id INTEGER NOT NULL DEFAULT 0,
    sell_price INTEGER NOT NULL DEFAULT 0,
    buy_price INTEGER NOT NULL DEFAULT 0,
    bonding INTEGER NOT NULL DEFAULT 0,
    inventory_type INTEGER NOT NULL DEFAULT 0,
    item_delay INTEGER NOT NULL DEFAULT 0,
    container_slots INTEGER NOT NULL DEFAULT 0,
    subclass_name TEXT,
    required_skill TEXT,
    required_skill_rank INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    icon TEXT,
    buy_count INTEGER NOT NULL DEFAULT 1,
    stack_size INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY,
    spell_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    skill_line INTEGER NOT NULL,
    skill_name TEXT NOT NULL,
    min_skill INTEGER NOT NULL DEFAULT 0,
    trivial_low INTEGER NOT NULL DEFAULT 0,
    trivial_high INTEGER NOT NULL DEFAULT 0,
    output_item_id INTEGER NOT NULL,
    output_count INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS recipe_reagents (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id),
    item_id INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (recipe_id, item_id)
);
CREATE TABLE IF NOT EXISTS disenchant (
    item_class INTEGER NOT NULL,
    quality INTEGER NOT NULL,
    min_ilvl INTEGER NOT NULL,
    max_ilvl INTEGER NOT NULL,
    result_item_id INTEGER NOT NULL,
    chance REAL NOT NULL,
    min_count INTEGER NOT NULL,
    max_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS vendor_items (item_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS prices (
    item_id INTEGER PRIMARY KEY,
    price INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ah_blocked (
    item_id INTEGER PRIMARY KEY,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY,
    realm TEXT NOT NULL,
    name TEXT NOT NULL,
    faction TEXT NOT NULL,
    class_file TEXT NOT NULL,
    level INTEGER NOT NULL,
    UNIQUE (realm, name)
);
CREATE TABLE IF NOT EXISTS character_professions (
    character_id INTEGER NOT NULL REFERENCES characters(id),
    skill_name TEXT NOT NULL,
    rank INTEGER NOT NULL,
    max_rank INTEGER NOT NULL,
    PRIMARY KEY (character_id, skill_name)
);
CREATE TABLE IF NOT EXISTS character_recipes (
    character_id INTEGER NOT NULL REFERENCES characters(id),
    skill_name TEXT NOT NULL,
    spell_id INTEGER NOT NULL,
    PRIMARY KEY (character_id, skill_name, spell_id)
);
"""

# Item columns added after the first release: name -> column definition for ALTER TABLE.
ITEM_COLUMNS = {
    "inventory_type": "INTEGER NOT NULL DEFAULT 0",
    "item_delay": "INTEGER NOT NULL DEFAULT 0",
    "container_slots": "INTEGER NOT NULL DEFAULT 0",
    "subclass_name": "TEXT",
    "required_skill": "TEXT",
    "required_skill_rank": "INTEGER NOT NULL DEFAULT 0",
    "description": "TEXT",
    "icon": "TEXT",
    "buy_count": "INTEGER NOT NULL DEFAULT 1",
    "stack_size": "INTEGER NOT NULL DEFAULT 1",
}

# The old `meta` keys kept as the local user's sync state. `auctionator_mtime` is left out so the first sync
# re-reads the file and records Auctionator's full daily history, which the old files never kept.
SYNC_TEXT_META = ("altarmy_path", "auctionator_path", "auctionator_realm", "auctionator_for")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Bring an old file up to the last per-version schema."""
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
    for name, definition in ITEM_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE items ADD COLUMN {name} {definition}")
    conn.commit()


def version_file(key: str, data_dir: Path = versions.DATA_DIR) -> Path:
    """A version's database from before Phase 2, e.g. data/altarmy-profit-tbc.db."""
    return data_dir / f"altarmy-profit-{key}.db"


def migrate_legacy_db(legacy: Path = LEGACY_DB, data_dir: Path | None = None) -> Path | None:
    """Rename the pre-versions database to its version's file, picked from the build it holds (no build
    means Forever, the only version back then). Returns the new path; None if there was nothing to move or
    that version already has a file."""
    if not legacy.is_file():
        return None
    conn = connect(legacy)
    try:
        init_schema(conn)
        row = conn.execute("SELECT value FROM meta WHERE key = 'build'").fetchone()
    finally:
        conn.close()
    target = version_file(versions.version_of_build(row[0] if row else ""), data_dir or legacy.parent)
    if target.exists():
        return None
    legacy.rename(target)
    return target


def import_version_files(
    database: db.Database,
    data_dir: Path = versions.DATA_DIR,
    game_versions: Mapping[str, GameVersion] = versions.VERSIONS,
) -> list[Path]:
    """Import every old per-version file found in `data_dir` (after moving the pre-versions file into
    place), renaming each to `*.imported`. Returns the files imported."""
    migrate_legacy_db(data_dir / LEGACY_DB.name, data_dir)
    done = []
    for key in game_versions:
        path = version_file(key, data_dir)
        if not path.is_file():
            continue
        with database.begin() as conn:
            import_version_file(conn, key, path)
        path.rename(path.with_name(path.name + IMPORTED_SUFFIX))
        done.append(path)
    return done


def import_version_file(conn: Connection, game_version: str, path: Path) -> None:
    """Copy one old file into the database as `game_version`, replacing that version's game data and
    the local user's settings, characters and AH blocks there; its prices become snapshots."""
    old = connect(path)
    try:
        init_schema(old)
        meta = {
            r["key"]: r["value"] for r in old.execute("SELECT key, value FROM meta") if r["value"] is not None
        }
        _clear(conn, game_version)
        _copy_game_data(conn, old, game_version, meta.get("build"))
        _copy_state(conn, old, game_version, meta)
        _copy_prices(conn, old, game_version, meta)
    finally:
        old.close()


def _clear(conn: Connection, gv: str) -> None:
    for t in (schema.recipe_reagents, schema.recipes, schema.items, schema.disenchant, schema.vendor_items):
        conn.execute(delete(t).where(t.c.game_version == gv))
    for t in (schema.user_settings, schema.local_sync, schema.characters, schema.ah_blocked):
        conn.execute(delete(t).where(t.c.user_uid == LOCAL_UID, t.c.game_version == gv))


def _rows(old: sqlite3.Connection, query: str, *params: object) -> list[dict[str, object]]:
    return [dict(r) for r in old.execute(query, params)]


def _insert(conn: Connection, table: Table, rows: list[dict[str, object]]) -> None:
    if rows:
        conn.execute(table.insert(), rows)


def _copy_game_data(conn: Connection, old: sqlite3.Connection, gv: str, build: str | None) -> None:
    item_cols = [c.name for c in schema.items.columns if c.name != "game_version"]
    _insert(
        conn,
        schema.items,
        [{**r, "game_version": gv} for r in _rows(old, f"SELECT {', '.join(item_cols)} FROM items")],
    )
    _insert(conn, schema.recipes, [{**r, "game_version": gv} for r in _rows(old, "SELECT * FROM recipes")])
    reagents = _rows(old, "SELECT recipe_id, item_id, count FROM recipe_reagents ORDER BY recipe_id, rowid")
    slots: dict[object, int] = {}
    for r in reagents:  # rowid order within a recipe is the order ingest read its reagent slots
        r["slot"] = slots[r["recipe_id"]] = slots.get(r["recipe_id"], -1) + 1
        r["game_version"] = gv
    _insert(conn, schema.recipe_reagents, reagents)
    de = _rows(old, "SELECT * FROM disenchant ORDER BY rowid")
    _insert(conn, schema.disenchant, [{**r, "game_version": gv} for r in de])
    vendor = _rows(old, "SELECT item_id FROM vendor_items")
    _insert(conn, schema.vendor_items, [{**r, "game_version": gv} for r in vendor])
    if build:
        db.set_build(conn, gv, build)


def _copy_state(conn: Connection, old: sqlite3.Connection, gv: str, meta: dict[str, str]) -> None:
    users.update_settings(
        conn,
        LOCAL_UID,
        gv,
        selected_realm=meta.get("selected_realm"),
        selected_faction=meta.get("selected_faction"),
        data_version=int(meta.get("data_version") or 0),
    )
    sync: dict[str, Any] = {k: meta.get(k) for k in SYNC_TEXT_META}
    if meta.get("altarmy_mtime"):
        sync["altarmy_mtime"] = int(meta["altarmy_mtime"])
    for key in ("altarmy_synced", "auctionator_synced"):
        if meta.get(key):
            sync[key] = _time(meta[key])
    users.update_sync(conn, LOCAL_UID, gv, **sync)
    c = schema.characters
    for ch in _rows(old, "SELECT * FROM characters ORDER BY id"):
        old_id = ch.pop("id")
        new_id: int = conn.execute(
            c.insert().values(**ch, user_uid=LOCAL_UID, game_version=gv).returning(c.c.id)
        ).scalar_one()
        profs = _rows(
            old, "SELECT skill_name, rank, max_rank FROM character_professions WHERE character_id = ?", old_id
        )
        _insert(conn, schema.character_professions, [{**p, "character_id": new_id} for p in profs])
        known = _rows(
            old, "SELECT skill_name, spell_id FROM character_recipes WHERE character_id = ?", old_id
        )
        _insert(conn, schema.character_recipes, [{**k, "character_id": new_id} for k in known])
    blocked = [
        {
            "user_uid": LOCAL_UID,
            "game_version": gv,
            "item_id": r["item_id"],
            "added_at": _time(str(r["added_at"])),
        }
        for r in _rows(old, "SELECT item_id, added_at FROM ah_blocked")
    ]
    _insert(conn, schema.ah_blocked, blocked)


def _copy_prices(conn: Connection, old: sqlite3.Connection, gv: str, meta: dict[str, str]) -> None:
    """One snapshot per source, on the auction house the Auctionator prices were synced for (the unnamed
    one if that is unknown)."""
    rows = _rows(old, "SELECT item_id, price, source, updated_at FROM prices ORDER BY item_id")
    if not rows:
        return
    realm, _, faction = (meta.get("auctionator_for") or "").partition("\t")
    key = meta.get("auctionator_realm")
    if realm and key:
        ah = prices.auctionator_auction_house(conn, gv, key, realm, faction)
    else:
        ah = prices.unnamed_auction_house(conn, gv)
    by_source: dict[str, list[Observation]] = {}
    for r in rows:
        source = str(r["source"]) if r["source"] in schema.PRICE_SOURCES else "manual"
        obs = Observation(int(str(r["item_id"])), int(str(r["price"])), _time(str(r["updated_at"])))
        by_source.setdefault(source, []).append(obs)
    for source, observations in sorted(by_source.items()):
        scanned_at = max(o.seen_at for o in observations)
        prices.record_snapshot(
            conn, ah, source, scanned_at, observations, received_at=scanned_at, uploader_uid=LOCAL_UID
        )


def _time(text: str) -> datetime:
    """SQLite CURRENT_TIMESTAMP text (UTC) as a datetime."""
    return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
