import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from altarmy_profit import cmangos

WORLD_SCHEMA = """
CREATE TABLE creature (guid INTEGER, id INTEGER);
CREATE TABLE creature_spawn_entry (guid INTEGER, entry INTEGER);
CREATE TABLE creature_template (Entry INTEGER, Name TEXT, VendorTemplateId INTEGER);
CREATE TABLE npc_vendor (
    entry INTEGER, item INTEGER, maxcount INTEGER, ExtendedCost INTEGER, condition_id INTEGER
);
CREATE TABLE npc_vendor_template (
    entry INTEGER, item INTEGER, maxcount INTEGER, ExtendedCost INTEGER, condition_id INTEGER
);
CREATE TABLE item_template (entry INTEGER, name TEXT);
"""


@pytest.fixture
def world(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """Vendor 1 spawns directly, vendor 3 only through a spawn's entry list, vendor 2 never; vendor 3 sells
    through vendor template 50."""
    conn = sqlite3.connect(tmp_path / "tbcmangos.sqlite")
    conn.executescript(WORLD_SCHEMA)
    conn.executemany("INSERT INTO creature VALUES (?,?)", [(1, 1), (2, 0)])
    conn.executemany("INSERT INTO creature_spawn_entry VALUES (?,?)", [(2, 3)])
    conn.executemany(
        "INSERT INTO creature_template VALUES (?,?,?)",
        [(1, "Trader", 0), (2, "Ghost Trader", 0), (3, "Supplier", 50)],
    )
    conn.executemany(
        "INSERT INTO npc_vendor VALUES (?,?,?,?,?)",
        [
            (1, 100, 0, 0, 0),  # unlimited, for gold
            (1, 101, 2, 0, 0),  # limited stock
            (1, 102, 0, 0, 7),  # behind a condition
            (1, 105, 0, 1432, 0),  # costs honor or badges
            (2, 103, 0, 0, 0),  # vendor never spawns
        ],
    )
    conn.executemany(
        "INSERT INTO npc_vendor_template VALUES (?,?,?,?,?)", [(50, 104, 0, 0, 0), (50, 100, 0, 0, 0)]
    )
    conn.executemany("INSERT INTO item_template VALUES (?,?)", [(100, "Rune Thread"), (104, "Imbued Vial")])
    yield conn
    conn.close()


def test_vendor_items_are_unlimited_unconditional_gold_and_spawned(world: sqlite3.Connection) -> None:
    assert cmangos.vendor_items(world) == [(100, "Rune Thread"), (104, "Imbued Vial")]


def test_world_db_url_picks_the_sqlite_dump() -> None:
    release = {
        "assets": [
            {"name": "tbc-world-db.zip", "updated_at": "2026-09-24T11:01:00Z", "browser_download_url": "x"},
            {"name": "tbc-sqlite-db.zip", "updated_at": "2026-09-24T11:00:59Z", "browser_download_url": "y"},
        ]
    }
    assert cmangos.world_db_url(json.dumps(release).encode()) == ("2026-09-24", "y")
    with pytest.raises(ValueError):
        cmangos.world_db_url(b'{"assets": []}')
