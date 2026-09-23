"""SQLite schema and helpers. All money values are integer copper."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB = Path("data/wowprofit.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    quality INTEGER NOT NULL DEFAULT 1,      -- 0 poor, 1 common, 2 uncommon (green), 3 rare, 4 epic
    item_level INTEGER NOT NULL DEFAULT 0,
    required_level INTEGER NOT NULL DEFAULT 0,
    class_id INTEGER NOT NULL DEFAULT 0,     -- 2 weapon, 4 armor, ...
    subclass_id INTEGER NOT NULL DEFAULT 0,
    sell_price INTEGER NOT NULL DEFAULT 0,   -- vendor buys from you
    buy_price INTEGER NOT NULL DEFAULT 0,    -- vendor price (only relevant if a vendor sells it)
    bonding INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS items_name ON items(name);

CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY,                  -- SkillLineAbility.ID
    spell_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    skill_line INTEGER NOT NULL,
    skill_name TEXT NOT NULL,
    min_skill INTEGER NOT NULL DEFAULT 0,
    trivial_low INTEGER NOT NULL DEFAULT 0,  -- yellow -> green threshold
    trivial_high INTEGER NOT NULL DEFAULT 0, -- green -> grey threshold
    output_item_id INTEGER NOT NULL,
    output_count INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS recipes_output ON recipes(output_item_id);

CREATE TABLE IF NOT EXISTS recipe_reagents (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id),
    item_id INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (recipe_id, item_id)
);

-- Disenchant results are server-side loot data, NOT in DB2. Seeded from data/disenchant.csv.
CREATE TABLE IF NOT EXISTS disenchant (
    item_class INTEGER NOT NULL,
    quality INTEGER NOT NULL,
    min_ilvl INTEGER NOT NULL,
    max_ilvl INTEGER NOT NULL,
    result_item_id INTEGER NOT NULL,
    chance REAL NOT NULL,                    -- 0..1 per disenchant
    min_count INTEGER NOT NULL,
    max_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS prices (
    item_id INTEGER PRIMARY KEY,
    price INTEGER NOT NULL,                  -- copper, per single item
    source TEXT NOT NULL DEFAULT 'manual',   -- manual | csv | addon | vendor
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
