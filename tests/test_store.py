import sqlite3
from pathlib import Path

from wowprofit import ingest, store


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
