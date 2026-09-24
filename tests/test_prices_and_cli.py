import sqlite3
from pathlib import Path

from wowprofit import db, ingest, prices, store

from .conftest import write_csv


def test_import_csv_by_id_and_name(
    db2_paths: dict[str, Path], conn: sqlite3.Connection, tmp_path: Path
) -> None:
    ingest.build_db(db2_paths, conn)
    f = write_csv(
        tmp_path / "prices.csv",
        ["item_id", "name", "price"],
        [
            {"item_id": 1, "price": 45},
            {"item_id": "", "name": "coarse thread", "price": 120},  # case-insensitive
            {"item_id": "", "name": "Nonexistent Item", "price": 9},
        ],
    )
    imported, unresolved = prices.import_csv(conn, f)
    assert imported == 2
    assert unresolved == ["Nonexistent Item"]
    assert prices.load_prices(conn) == {1: 45, 2: 120}


def test_set_price_upserts(conn: sqlite3.Connection) -> None:
    prices.set_price(conn, 1, 10)
    prices.set_price(conn, 1, 20, "addon")
    row = conn.execute("SELECT price, source FROM prices WHERE item_id = 1").fetchone()
    assert (row["price"], row["source"]) == (20, "addon")


def test_load_market_ranks_end_to_end(db2_paths: dict[str, Path], conn: sqlite3.Connection) -> None:
    ingest.build_db(db2_paths, conn)
    prices.set_price(conn, 1, 20)  # linen
    prices.set_price(conn, 2, 100)  # thread
    market = store.load_market(conn)
    (result,) = market.rank()
    assert result.cost == 300
    assert result.profit == 200  # vendors for 500
    assert result.best_exit == "vendor"


def test_find_auctionator_files(tmp_path: Path) -> None:
    sv = tmp_path / "_classic_beta_" / "WTF" / "Account" / "ME" / "SavedVariables"
    sv.mkdir(parents=True)
    (sv / "Auctionator.lua").write_text("")
    (sv / "Other.lua").write_text("")
    assert prices.find_auctionator_files([tmp_path, tmp_path / "missing"]) == [sv / "Auctionator.lua"]


def test_meta_roundtrip(conn: sqlite3.Connection) -> None:
    assert db.get_meta(conn, "x") is None
    db.set_meta(conn, "x", "1")
    db.set_meta(conn, "x", "2")
    assert db.get_meta(conn, "x") == "2"


def test_count_rows_and_last_import(conn: sqlite3.Connection) -> None:
    assert db.count_rows(conn, "prices") == 0
    assert db.last_import(conn) is None
    prices.set_price(conn, 1, 10, "auctionator")
    prices.set_price(conn, 2, 10, "manual")
    conn.commit()
    assert db.count_rows(conn, "prices") == 2
    assert db.last_import(conn) is not None
    assert db.last_import(conn, "csv") is None
