import os
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from altarmy_profit import altarmy, db, ingest, prices, service, store
from altarmy_profit.altarmy import Character, Profession
from altarmy_profit.engine import ALL_EXITS, Filters
from altarmy_profit.service import Selection, SyncResult

from .conftest import SV_DIR
from .test_altarmy import ALTARMY_SV
from .test_auctionator import _entry, _saved_variables


def chars(*names: str) -> list[Character]:
    return [c for c in altarmy.parse_characters(ALTARMY_SV) if not names or c.name in names]


def touch(path: Path) -> None:
    """Move the mtime forward a second (a rewrite within the clock's resolution may not change it)."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))


def test_default_path_prefers_last_then_first_found() -> None:
    files = [r"W\_classic_\A.lua", r"W\_classic_beta_\A.lua"]
    assert service.default_path(files, None) == files[0]
    assert service.default_path(files, files[0]) == files[0]
    assert service.default_path(files[:1], None) == files[0]
    assert service.default_path([], None) is None
    assert service.default_path([], r"C:\custom\A.lua") == r"C:\custom\A.lua"


def test_search_ranks_known_recipes_or_whole_professions(
    db2_paths: dict[str, Path], conn: sqlite3.Connection
) -> None:
    ingest.build_db(db2_paths, conn)
    prices.set_price(conn, 1, 20)
    prices.set_price(conn, 2, 100)
    conn.commit()
    base = store.load_market(conn)

    profitable = Filters(min_profit=0)
    (r,) = service.search(base, chars("Tailor Guy"), False, profitable)
    assert r.profit == 200
    assert service.search(base, chars("Tailor Guy"), False, Filters(min_profit=201)) == []
    assert service.search(base, chars("Tailor Guy"), False, Filters(max_cost=299)) == []
    assert service.search(base, chars("Tailor Guy"), False, profitable, exits=frozenset({"ah"})) == []
    assert service.search(base, chars("Frell", "Ally Alt"), False, profitable) == []
    assert service.search(base, [], True, profitable) == []

    (tailor,) = chars("Tailor Guy")
    novice = replace(tailor, professions=(Profession("Tailoring", 1, 75, frozenset()),))
    assert service.search(base, [novice], False, profitable) == []
    unlearned = service.search(base, [novice], True, profitable)
    assert [r.recipe.name for r in unlearned] == ["Green Robe"]


def test_search_and_evaluate_without_trivial_recipes(
    db2_paths: dict[str, Path], conn: sqlite3.Connection
) -> None:
    ingest.build_db(db2_paths, conn)
    prices.set_price(conn, 1, 20)
    prices.set_price(conn, 2, 100)
    conn.commit()
    base = store.load_market(conn)
    (tailor,) = chars("Tailor Guy")  # Tailoring 50: the robe turns grey at 60
    (robe,) = base.recipes
    profitable = Filters(min_profit=0)
    assert len(service.search(base, [tailor], False, profitable, include_trivial=False)) == 1

    (p,) = [p for p in tailor.professions if p.name == "Tailoring"]
    veteran = replace(tailor, professions=(replace(p, rank=60, max_rank=150),))
    assert len(service.search(base, [veteran], False, profitable)) == 1
    assert service.search(base, [veteran], False, profitable, include_trivial=False) == []
    assert service.evaluate(base, [veteran], False, ALL_EXITS, robe.id, {}, include_trivial=False) is None


def test_evaluate_applies_choices(
    db2_paths: dict[str, Path], conn: sqlite3.Connection, vendor_csv: Path
) -> None:
    ingest.build_db(db2_paths, conn, vendor_csv=vendor_csv)
    prices.set_price(conn, 1, 20)
    prices.set_price(conn, 2, 100)  # vendors sell thread for 11c
    conn.commit()
    base = store.load_market(conn)
    best = service.evaluate(base, chars("Tailor Guy"), False, ALL_EXITS, 100, {})
    assert best is not None
    assert (best.cost, best.tree.inputs[1].source) == (211, "vendor")
    chosen = service.evaluate(base, chars("Tailor Guy"), False, ALL_EXITS, 100, {"r.1": "ah"})
    assert chosen is not None
    assert (chosen.cost, chosen.tree.inputs[1].source) == (300, "ah")
    assert service.evaluate(base, chars("Tailor Guy"), False, ALL_EXITS, 999, {}) is None
    assert service.evaluate(base, chars("Frell"), False, ALL_EXITS, 100, {}) is None


def test_search_and_evaluate_never_sell_blocked_items_on_the_ah(
    db2_paths: dict[str, Path], conn: sqlite3.Connection
) -> None:
    ingest.build_db(db2_paths, conn)
    prices.set_price(conn, 1, 20)
    prices.set_price(conn, 2, 100)
    prices.set_price(conn, 3, 1000)  # the robe: 950 on the AH beats 500 at a vendor
    conn.commit()
    base = store.load_market(conn)
    (r,) = service.search(base, chars("Tailor Guy"), False, Filters())
    assert r.best_exit == "ah"
    (r,) = service.search(base, chars("Tailor Guy"), False, Filters(), no_ah=frozenset({3}))
    assert (r.best_exit, [e.kind for e in r.exits]) == ("vendor", ["vendor"])
    got = service.evaluate(base, chars("Tailor Guy"), False, ALL_EXITS, 100, {}, no_ah=frozenset({3}))
    assert got is not None
    assert got.best_exit == "vendor"


def test_search_without_min_profit_keeps_losses(db2_paths: dict[str, Path], conn: sqlite3.Connection) -> None:
    ingest.build_db(db2_paths, conn)
    prices.set_price(conn, 1, 100)  # 10 linen cost more than the robe sells for
    prices.set_price(conn, 2, 100)
    conn.commit()
    base = store.load_market(conn)
    assert service.search(base, chars("Tailor Guy"), False, Filters(min_profit=0)) == []
    (r,) = service.search(base, chars("Tailor Guy"), False, Filters())
    assert r.profit < 0


@pytest.mark.parametrize(
    ("realms", "realm", "faction", "key"),
    [
        (["ClassicBetaPvE", "ClassicBetaPvP2"], "Classic Beta PvE", "Horde", "ClassicBetaPvE"),
        (["ClassicBetaPvE", "ClassicBetaPvP2"], "Classic Beta PvP 2", "Alliance", "ClassicBetaPvP2"),
        (["Dreamscythe Alliance", "Dreamscythe Horde"], "Dreamscythe", "Horde", "Dreamscythe Horde"),
        (["Defias Pillager Alliance"], "Defias Pillager", "Alliance", "Defias Pillager Alliance"),
        (["Atiesh"], "Dreamscythe", "Horde", None),
    ],
)
def test_match_auctionator_realm(realms: list[str], realm: str, faction: str, key: str | None) -> None:
    assert service.match_auctionator_realm(realms, realm, faction) == key


def test_selection_defaults_to_biggest_group_then_remembers(conn: sqlite3.Connection) -> None:
    assert service.selection(conn, []) is None
    assert service.selected_characters(conn) == (None, [])
    store.save_characters(conn, chars())
    assert service.selection(conn, chars()) == Selection("Dreamscythe", "Horde")

    service.select(conn, "Classic Beta PvE", "Horde")
    sel, selected = service.selected_characters(conn)
    assert sel == Selection("Classic Beta PvE", "Horde")
    assert [c.name for c in selected] == ["Tailor Guy"]
    with pytest.raises(ValueError, match="Nowhere"):
        service.select(conn, "Nowhere", "Horde")

    store.save_characters(conn, chars("Frell"))  # the selected realm is gone from the file
    assert service.selection(conn, chars("Frell")) == Selection("Dreamscythe", "Horde")


def test_sync_finds_files_and_imports_the_selected_realms_prices(
    db2_paths: dict[str, Path], conn: sqlite3.Connection, wow_root: Path
) -> None:
    ingest.build_db(db2_paths, conn)
    prices.set_price(conn, 3, 999)  # a manual price stays through every sync
    conn.commit()

    assert service.sync(conn, [wow_root]) == SyncResult(True, [])
    assert db.get_meta(conn, "altarmy_path") == str(wow_root / SV_DIR / "AltArmy_TBC.lua")
    assert db.get_meta(conn, "auctionator_path") == str(wow_root / SV_DIR / "Auctionator.lua")
    assert len(store.load_characters(conn)) == 4
    assert db.get_meta(conn, "auctionator_realm") == "Dreamscythe Horde"
    assert prices.load_prices(conn) == {1: 5, 3: 999}
    assert service.data_version(conn) == 1

    assert service.sync(conn, [wow_root]) == SyncResult(False, [])  # nothing changed on disk

    service.select(conn, "Classic Beta PvE", "Horde")
    assert service.sync(conn, [wow_root]).changed
    assert db.get_meta(conn, "auctionator_realm") == "ClassicBetaPvE"
    assert prices.load_prices(conn) == {1: 20, 2: 100, 3: 999}
    assert service.data_version(conn) == 2


def test_sync_rereads_files_the_game_rewrote(conn: sqlite3.Connection, wow_root: Path) -> None:
    service.sync(conn, [wow_root])
    alt_army = wow_root / SV_DIR / "AltArmy_TBC.lua"
    alt_army.write_bytes(ALTARMY_SV.replace(b"Tailor Guy", b"Tailor Gal"))
    touch(alt_army)
    assert service.sync(conn, [wow_root]).changed
    assert "Tailor Gal" in [c.name for c in store.load_characters(conn)]

    auctions = wow_root / SV_DIR / "Auctionator.lua"
    auctions.write_bytes(_saved_variables({"Dreamscythe Horde": {"1": _entry(6)}}))
    touch(auctions)
    assert service.sync(conn, [wow_root]).changed
    assert prices.load_prices(conn) == {1: 6}
    assert service.sync(conn, [wow_root], force=True).changed


def test_sync_warnings(conn: sqlite3.Connection, wow_root: Path, tmp_path: Path) -> None:
    res = service.sync(conn, [tmp_path / "no wow here"])
    assert not res.changed
    assert res.warnings == ["No Alt Army file found. Pick AltArmy_TBC.lua on the Manage tab."]

    prices.set_price(conn, 1, 7, "auctionator")  # from some other realm
    conn.commit()
    (wow_root / SV_DIR / "Auctionator.lua").write_bytes(_saved_variables({"Atiesh": {"1": _entry(1)}}))
    db.set_meta(conn, "altarmy_path", str(wow_root / SV_DIR / "AltArmy_TBC.lua"))
    no_prices = "Auctionator has no prices for Dreamscythe (Horde). Scan that auction house in game."
    assert service.sync(conn, [wow_root]) == SyncResult(True, [no_prices])
    assert prices.load_prices(conn) == {}
    assert service.sync(conn, [wow_root]) == SyncResult(False, [no_prices])

    (wow_root / SV_DIR / "Auctionator.lua").write_text("garbage")
    res = service.sync(conn, [wow_root], force=True)
    assert "Could not read" in res.warnings[-1]

    db.set_meta(conn, "altarmy_path", str(tmp_path / "gone.lua"))
    assert service.sync(conn, [wow_root]).warnings[0].startswith("Alt Army file not found")


def test_set_sources(conn: sqlite3.Connection, wow_root: Path, tmp_path: Path) -> None:
    alt_army = str(wow_root / SV_DIR / "AltArmy_TBC.lua")
    service.set_sources(conn, alt_army, None)
    assert db.get_meta(conn, "altarmy_path") == alt_army
    assert db.get_meta(conn, "auctionator_path") is None
    with pytest.raises(FileNotFoundError):
        service.set_sources(conn, None, str(tmp_path / "missing.lua"))


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
