import sqlite3
from pathlib import Path

from wowprofit import db, ingest, prices, service
from wowprofit.engine import Market, Recipe


def test_available_professions_keeps_profession_order_and_drops_junk() -> None:
    recipes = [
        Recipe(1, "a", 1, skill_name="Tailoring"),
        Recipe(2, "b", 1, skill_name="Alchemy"),
        Recipe(3, "c", 1, skill_name="Warrior"),
    ]
    assert service.available_professions(Market({}, recipes, {})) == ["Alchemy", "Tailoring"]


def test_default_auctionator_path_prefers_last_then_forever() -> None:
    files = [r"W\_classic_\A.lua", r"W\_classic_beta_\A.lua"]
    assert service.default_auctionator_path(files, None) == files[1]
    assert service.default_auctionator_path(files, files[0]) == files[0]
    assert service.default_auctionator_path(files[:1], None) == files[0]
    assert service.default_auctionator_path([], None) is None
    assert service.default_auctionator_path([], r"C:\custom\A.lua") == r"C:\custom\A.lua"


def test_default_realm() -> None:
    assert service.default_realm(["A", "B"], "B") == "B"
    assert service.default_realm(["A", "B"], "Z") == "A"
    assert service.default_realm([], None) is None


def test_search_only_chains_through_selected_professions(
    db2_paths: dict[str, Path], conn: sqlite3.Connection
) -> None:
    ingest.build_db(db2_paths, conn)
    prices.set_price(conn, 1, 20)
    prices.set_price(conn, 2, 100)
    conn.commit()
    from wowprofit.store import load_market

    base = load_market(conn)
    (r,) = service.search(base, ["tailoring"], min_profit=0, top=10)
    assert r.profit == 200
    assert service.search(base, ["Alchemy"], min_profit=0, top=10) == []
    assert service.search(base, ["Tailoring"], min_profit=201, top=10) == []


def test_market_cache_reloads_only_after_invalidate(
    db2_paths: dict[str, Path], conn: sqlite3.Connection, tmp_path: Path
) -> None:
    ingest.build_db(db2_paths, conn)
    cache = service.MarketCache(tmp_path / "test.db")
    first = cache.get()
    assert cache.get() is first
    prices.set_price(conn, 1, 5)
    conn.commit()
    assert cache.get().prices == {}
    cache.invalidate()
    assert cache.get().prices == {1: 5}


def test_import_auctionator_remembers_path_and_realm(
    db2_paths: dict[str, Path], conn: sqlite3.Connection, tmp_path: Path
) -> None:
    from .test_auctionator import _entry, _saved_variables

    ingest.build_db(db2_paths, conn)
    sv = tmp_path / "Auctionator.lua"
    sv.write_bytes(_saved_variables({"A": {"1": _entry(1)}, "B": {"1": _entry(20), "2": _entry(100)}}))
    assert service.import_auctionator(conn, sv, "B") == ("B", 2, 0)
    assert db.get_meta(conn, "auctionator_path") == str(sv)
    assert db.get_meta(conn, "auctionator_realm") == "B"
