import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from wowprofit import vmangos

WORLD_SCHEMA = """
CREATE TABLE creature (guid INTEGER, id INTEGER, id2 INTEGER, id3 INTEGER, id4 INTEGER, id5 INTEGER);
CREATE TABLE creature_template (entry INTEGER, patch INTEGER, name TEXT, vendor_id INTEGER);
CREATE TABLE npc_vendor (entry INTEGER, item INTEGER, maxcount INTEGER, condition_id INTEGER);
CREATE TABLE npc_vendor_template (entry INTEGER, item INTEGER, maxcount INTEGER, condition_id INTEGER);
CREATE TABLE item_template (entry INTEGER, patch INTEGER, name TEXT);
"""


@pytest.fixture
def world(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """Vendors 1 (spawned) and 2 (never spawned) sell directly; vendor 3 (spawned as an alternate id)
    sells through vendor template 50."""
    conn = sqlite3.connect(tmp_path / "mangos.sqlite")
    conn.executescript(WORLD_SCHEMA)
    conn.executemany("INSERT INTO creature VALUES (?,?,?,?,?,?)", [(1, 1, 0, 0, 0, 0), (2, 9, 3, 0, 0, 0)])
    conn.executemany(
        "INSERT INTO creature_template VALUES (?,?,?,?)",
        [(1, 0, "Trader", 0), (2, 0, "Ghost Trader", 0), (3, 0, "Supplier", 50), (3, 1, "Supplier", 50)],
    )
    conn.executemany(
        "INSERT INTO npc_vendor VALUES (?,?,?,?)",
        [
            (1, 100, 0, 0),  # unlimited
            (1, 101, 2, 0),  # limited stock
            (1, 102, 0, 7),  # behind a condition (reputation, event, ...)
            (2, 103, 0, 0),  # vendor never spawns
        ],
    )
    conn.executemany("INSERT INTO npc_vendor_template VALUES (?,?,?,?)", [(50, 104, 0, 0), (50, 100, 0, 0)])
    conn.executemany(
        "INSERT INTO item_template VALUES (?,?,?)",
        [(100, 0, "Rune Thred"), (100, 1, "Rune Thread"), (104, 0, "Empty Vial")],
    )
    yield conn
    conn.close()


def test_vendor_items_are_unlimited_unconditional_and_spawned(world: sqlite3.Connection) -> None:
    assert vmangos.vendor_items(world) == [(100, "Rune Thread"), (104, "Empty Vial")]


def test_world_db_url_picks_the_sqlite_dump() -> None:
    release = {
        "assets": [
            {"name": "db-13b49dc.zip", "browser_download_url": "https://example/db.zip"},
            {"name": "db-sqlite-13b49dc.zip", "browser_download_url": "https://example/db-sqlite.zip"},
        ]
    }
    assert vmangos.world_db_url(json.dumps(release).encode()) == (
        "db-sqlite-13b49dc.zip",
        "https://example/db-sqlite.zip",
    )
    with pytest.raises(ValueError):
        vmangos.world_db_url(b'{"assets": []}')


def test_write_csv_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "vendor_items.csv"
    vmangos.write_csv([(100, "Rune Thread"), (104, "Vial, Empty")], path)
    assert path.read_text(encoding="utf-8").splitlines() == [
        "item_id,name",
        "100,Rune Thread",
        '104,"Vial, Empty"',
    ]
