"""Importing the SQLite files of older releases (one per game version, and the pre-versions file)."""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select

from altarmy_profit import db, legacy, prices, schema, store, users
from altarmy_profit.altarmy import Character, Profession
from altarmy_profit.versions import VERSIONS

from .conftest import FOREVER, ME


def old_file(path: Path, build: str | None, *, oldest_items: bool = False) -> sqlite3.Connection:
    """An old per-version file; `oldest_items` gives it the first release's items table (the tooltip
    columns were added later)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = legacy.connect(path)
    if oldest_items:
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
            " quality INTEGER NOT NULL DEFAULT 1, item_level INTEGER NOT NULL DEFAULT 0,"
            " required_level INTEGER NOT NULL DEFAULT 0,"
            " class_id INTEGER NOT NULL DEFAULT 0, subclass_id INTEGER NOT NULL DEFAULT 0,"
            " sell_price INTEGER NOT NULL DEFAULT 0, buy_price INTEGER NOT NULL DEFAULT 0,"
            " bonding INTEGER NOT NULL DEFAULT 0)"
        )
    legacy.init_schema(conn)
    if build:
        conn.execute("INSERT INTO meta VALUES ('build', ?)", (build,))
    conn.commit()
    return conn


def fill(conn: sqlite3.Connection) -> None:
    """Game data, a synced Dreamscythe Horde selection, prices from Auctionator and by hand, a block;
    closes the file."""
    conn.executescript(
        """
        INSERT INTO items (id, name, sell_price, buy_price, stack_size) VALUES
            (1, 'Linen Cloth', 13, 0, 20), (2, 'Coarse Thread', 10, 51, 1), (3, 'Green Robe', 500, 0, 1);
        INSERT INTO recipes VALUES (100, 900, 'Green Robe', 197, 'Tailoring', 1, 30, 60, 3, 1);
        INSERT INTO recipe_reagents VALUES (100, 2, 1);  -- slot order: thread was read first here
        INSERT INTO recipe_reagents VALUES (100, 1, 10);
        INSERT INTO disenchant VALUES (4, 2, 5, 15, 10940, 0.8, 1, 2), (4, 2, 5, 15, 10938, 0.2, 1, 1);
        INSERT INTO vendor_items VALUES (2);
        INSERT INTO characters VALUES (7, 'Dreamscythe', 'Frell', 'Horde', 'MAGE', 70);
        INSERT INTO character_professions VALUES (7, 'Tailoring', 50, 75), (7, 'Cooking', 1, 75);
        INSERT INTO character_recipes VALUES (7, 'Tailoring', 900);
        INSERT INTO ah_blocked VALUES (3, '2026-09-20 10:00:00');
        INSERT INTO prices VALUES (1, 20, 'auctionator', '2026-09-24 20:53:16'),
                                  (2, 100, 'auctionator', '2026-09-24 20:53:16'),
                                  (3, 999, 'manual', '2026-09-21 08:00:00'),
                                  (4, 5, 'vendor', '2026-09-21 08:00:00');
        INSERT INTO meta VALUES ('selected_realm', 'Dreamscythe'), ('selected_faction', 'Horde'),
            ('auctionator_realm', 'Dreamscythe Horde'),
            ('auctionator_for', 'Dreamscythe' || char(9) || 'Horde'),
            ('auctionator_mtime', '1790278648673069200'), ('data_version', '3'),
            ('altarmy_path', 'C:\\x.lua');
        """
    )
    conn.commit()
    conn.close()


def test_import_copies_everything_and_renames_the_file(database: db.Database, tmp_path: Path) -> None:
    path = legacy.version_file("tbc", tmp_path)
    fill(old_file(path, "2.5.6.69795", oldest_items=True))
    assert legacy.import_version_files(database, tmp_path) == [path]
    assert not path.exists()
    assert (tmp_path / "altarmy-profit-tbc.db.imported").is_file()
    assert legacy.import_version_files(database, tmp_path) == []  # nothing left to import

    with database.begin() as conn:
        assert db.get_build(conn, "tbc") == "2.5.6.69795"
        assert db.get_build(conn, FOREVER) is None
        assert users.get_settings(conn, ME, "tbc") == users.UserSettings("Dreamscythe", "Horde", 3)
        sync = users.get_sync(conn, ME, "tbc")
        assert sync.altarmy_path == "C:\\x.lua"
        assert sync.auctionator_for == "Dreamscythe\tHorde"
        assert sync.auctionator_mtime is None  # the next sync re-reads the file
        assert store.load_characters(conn, ME, "tbc") == [
            Character(
                "Dreamscythe",
                "Frell",
                "Horde",
                "MAGE",
                70,
                (
                    Profession("Cooking", 1, 75, frozenset()),
                    Profession("Tailoring", 50, 75, frozenset({900})),
                ),
            )
        ]
        assert store.load_ah_blocked(conn, ME, "tbc") == [(3, "2026-09-20 10:00:00")]

        ah = prices.find_auction_house(conn, "tbc", "Dreamscythe", "Horde")
        assert ah is not None and prices.find_auction_house(conn, "tbc", "Dreamscythe", "Alliance") is None
        assert prices.load_current(conn, ah) == {1: 20, 2: 100, 3: 999, 4: 5}
        assert prices.last_import(conn, ah) == "2026-09-24 20:53:16"  # when it was synced, not imported
        snap = schema.price_snapshots
        got = conn.execute(select(snap.c.source, snap.c.item_count).order_by(snap.c.source)).all()
        assert got == [("auctionator", 2), ("manual", 2)]  # the old "vendor" source counts as manual

        market = store.load_market(conn, "tbc", ah)
        assert market.items[2].vendor_price == 51
        assert market.items[3].stack_size == 1
        (robe,) = market.recipes
        assert robe.reagents == ((2, 1), (1, 10))  # the old slot order
        assert [d.result_item_id for d in market.disenchant] == [10940, 10938]
        assert store.load_market(conn, FOREVER, None).items == {}


def test_import_without_a_synced_realm_uses_the_unnamed_auction_house(
    database: db.Database, tmp_path: Path
) -> None:
    conn = old_file(legacy.version_file(FOREVER, tmp_path), None)
    conn.execute("INSERT INTO prices VALUES (1, 20, 'csv', '2026-09-24 20:53:16')")
    conn.commit()
    conn.close()
    legacy.import_version_files(database, tmp_path)
    with database.begin() as c:
        assert prices.load_current(c, prices.find_auction_house(c, FOREVER, "", "")) == {1: 20}


def test_import_replaces_what_the_version_had(database: db.Database, tmp_path: Path) -> None:
    with database.begin() as conn:
        store.save_characters(conn, ME, "tbc", [Character("Old", "Gone", "Horde", "MAGE", 1, ())])
        store.save_characters(conn, ME, FOREVER, [Character("Stays", "Here", "Horde", "MAGE", 1, ())])
    fill(old_file(legacy.version_file("tbc", tmp_path), None))
    legacy.import_version_files(database, tmp_path)
    with database.begin() as conn:
        assert [c.name for c in store.load_characters(conn, ME, "tbc")] == ["Frell"]
        assert [c.name for c in store.load_characters(conn, ME, FOREVER)] == ["Here"]


@pytest.mark.parametrize(
    ("build", "key"), [("1.60.1.69913", "forever"), ("2.5.6.69795", "tbc"), (None, "forever")]
)
def test_migrate_legacy_db_moves_it_to_its_versions_file(tmp_path: Path, build: str | None, key: str) -> None:
    legacy_db = tmp_path / "altarmy-profit.db"
    old_file(legacy_db, build).close()
    assert legacy.migrate_legacy_db(legacy_db) == legacy.version_file(key, tmp_path)
    assert not legacy_db.exists()


def test_migrate_legacy_db_leaves_existing_files_alone(tmp_path: Path) -> None:
    assert legacy.migrate_legacy_db(tmp_path / "altarmy-profit.db") is None  # nothing to move
    legacy_db = tmp_path / "altarmy-profit.db"
    old_file(legacy_db, "1.60.1.69913").close()
    legacy.version_file("forever", tmp_path).write_bytes(b"")
    assert legacy.migrate_legacy_db(legacy_db) is None
    assert legacy_db.is_file()


def test_the_pre_versions_file_is_imported_too(database: db.Database, tmp_path: Path) -> None:
    fill(old_file(tmp_path / "altarmy-profit.db", "2.5.6.69795"))
    assert legacy.import_version_files(database, tmp_path, VERSIONS) == [legacy.version_file("tbc", tmp_path)]
    with database.begin() as conn:
        assert [c.name for c in store.load_characters(conn, ME, "tbc")] == ["Frell"]
