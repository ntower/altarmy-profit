import sqlite3
from pathlib import Path

import pytest

from altarmy_profit import cli, db, ingest, prices, store, versions

from .conftest import SV_DIR, write_csv


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


def test_find_altarmy_files(wow_root: Path) -> None:
    assert prices.find_altarmy_files([wow_root]) == [wow_root / SV_DIR / "AltArmy_TBC.lua"]


def test_replace_auctionator_prices_keeps_other_sources(conn: sqlite3.Connection) -> None:
    prices.set_price(conn, 1, 10, "auctionator")
    prices.set_price(conn, 2, 10, "manual")
    prices.set_price(conn, 3, 10, "manual")
    conn.commit()
    assert prices.replace_auctionator_prices(conn, {3: 7, 4: 8}) == 2
    assert prices.load_prices(conn) == {2: 10, 3: 7, 4: 8}


def test_cli_import_altarmy_and_rank_by_realm(
    db2_paths: dict[str, Path], conn: sqlite3.Connection, wow_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ingest.build_db(db2_paths, conn)
    prices.set_price(conn, 1, 20)
    prices.set_price(conn, 2, 100)
    conn.commit()
    dbfile = str(conn.execute("PRAGMA database_list").fetchone()["file"])
    cli.main(["--db", dbfile, "import-altarmy", str(wow_root / SV_DIR / "AltArmy_TBC.lua")])
    assert "Classic Beta PvE (Horde): Tailor Guy" in capsys.readouterr().out

    cli.main(["--db", dbfile, "rank", "--realm", "Dreamscythe", "--faction", "Horde"])
    assert "No profitable recipes" in capsys.readouterr().out
    cli.main(["--db", dbfile, "rank", "--realm", "Classic Beta PvE", "--faction", "Horde"])
    out = capsys.readouterr().out
    assert "Characters: Tailor Guy" in out
    assert "Green Robe" in out
    cli.main(["--db", dbfile, "rank"])  # remembers the realm and faction
    assert "Green Robe" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="both"):
        cli.main(["--db", dbfile, "rank", "--realm", "Dreamscythe"])


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


def test_ui_serves_api_with_uvicorn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn
    from fastapi import FastAPI

    calls: list[tuple[object, str, int]] = []

    def fake_run(app: object, host: str, port: int) -> None:
        calls.append((app, host, port))

    monkeypatch.setattr(uvicorn, "run", fake_run)
    cli.main(["--db", str(tmp_path / "x.db"), "ui", "--port", "9123", "--no-browser"])
    ((app, host, port),) = calls
    assert isinstance(app, FastAPI)
    assert (host, port) == ("127.0.0.1", 9123)


def test_cli_ingest_uses_the_game_versions_build_and_product(
    db2_paths: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    builds: list[str] = []

    def download_all(build: str, cache_dir: Path) -> dict[str, Path]:
        builds.append(build)
        return db2_paths

    monkeypatch.setattr(ingest, "download_all", download_all)
    monkeypatch.setattr(ingest, "latest_build", lambda product: {"wow_anniversary": "2.5.7.1"}[product])
    dbfile = str(tmp_path / "tbc.db")
    cli.main(["--game-version", "tbc", "--db", dbfile, "ingest"])
    cli.main(["--game-version", "tbc", "--db", dbfile, "ingest", "--build", "latest"])
    assert builds == [versions.VERSIONS["tbc"].default_build, "2.5.7.1"]
    assert "Ingested TBC Anniversary build 2.5.7.1" in capsys.readouterr().out
