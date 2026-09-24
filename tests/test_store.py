import sqlite3
from pathlib import Path

from wowprofit import altarmy, ingest, store

from .test_altarmy import ALTARMY_SV


def test_load_item_details_returns_requested_items(
    db2_paths: dict[str, Path], conn: sqlite3.Connection
) -> None:
    ingest.build_db(db2_paths, conn)
    got = store.load_item_details(conn, [3, 1, 42])
    assert set(got) == {1, 3}
    robe = got[3]
    assert (robe.name, robe.quality, robe.subclass_name, robe.required_skill) == (
        "Green Robe",
        2,
        "Cloth",
        "Tailoring",
    )
    assert got[1].icon == "inv_fabric_linen_01"
    assert store.load_item_details(conn, []) == {}


def test_load_item_details_handles_many_ids(db2_paths: dict[str, Path], conn: sqlite3.Connection) -> None:
    ingest.build_db(db2_paths, conn)
    assert set(store.load_item_details(conn, range(5000))) == {1, 2, 3}


def test_load_market_prices_vendor_items_per_unit(
    db2_paths: dict[str, Path], conn: sqlite3.Connection, vendor_csv: Path
) -> None:
    ingest.build_db(db2_paths, conn, vendor_csv=vendor_csv)
    items = store.load_market(conn).items
    assert items[2].vendor_price == 11  # 51c per stack of 5, rounded up
    assert items[1].vendor_price is None  # not sold by vendors
    assert (items[1].stack_size, items[3].stack_size) == (20, 1)  # robe: no Stackable -> 1


def test_load_market_keeps_spell_ids(db2_paths: dict[str, Path], conn: sqlite3.Connection) -> None:
    ingest.build_db(db2_paths, conn)
    (recipe,) = store.load_market(conn).recipes
    assert recipe.spell_id == 900


def test_characters_round_trip_and_replace(conn: sqlite3.Connection) -> None:
    chars = altarmy.parse_characters(ALTARMY_SV)
    store.save_characters(conn, chars)
    assert store.load_characters(conn) == chars
    store.save_characters(conn, chars[:1])
    assert store.load_characters(conn) == chars[:1]
