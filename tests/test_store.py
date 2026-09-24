from pathlib import Path

from sqlalchemy import Connection

from altarmy_profit import altarmy, ingest, store

from .conftest import FOREVER, set_prices
from .test_altarmy import ALTARMY_SV


def test_load_item_details_returns_requested_items(db2_paths: dict[str, Path], conn: Connection) -> None:
    ingest.build_db(db2_paths, conn, FOREVER)
    got = store.load_item_details(conn, FOREVER, [3, 1, 42])
    assert set(got) == {1, 3}
    robe = got[3]
    assert (robe.name, robe.quality, robe.subclass_name, robe.required_skill) == (
        "Green Robe",
        2,
        "Cloth",
        "Tailoring",
    )
    assert got[1].icon == "inv_fabric_linen_01"
    assert store.load_item_details(conn, FOREVER, []) == {}


def test_load_item_details_handles_many_ids(db2_paths: dict[str, Path], conn: Connection) -> None:
    ingest.build_db(db2_paths, conn, FOREVER)
    assert set(store.load_item_details(conn, FOREVER, range(5000))) == {1, 2, 3}


def test_load_market_prices_vendor_items_per_unit(
    db2_paths: dict[str, Path], conn: Connection, vendor_csv: Path
) -> None:
    ingest.build_db(db2_paths, conn, FOREVER, vendor_csv=vendor_csv)
    items = store.load_market(conn, FOREVER, None).items
    assert items[2].vendor_price == 11  # 51c per stack of 5, rounded up
    assert items[1].vendor_price is None  # not sold by vendors
    assert (items[1].stack_size, items[3].stack_size) == (20, 1)  # robe: no Stackable -> 1


def test_load_market_keeps_spell_ids(db2_paths: dict[str, Path], conn: Connection) -> None:
    ingest.build_db(db2_paths, conn, FOREVER)
    (recipe,) = store.load_market(conn, FOREVER, None).recipes
    assert recipe.spell_id == 900
    assert (recipe.trivial_low, recipe.trivial_high) == (30, 60)


def test_characters_round_trip_and_replace(conn: Connection) -> None:
    chars = altarmy.parse_characters(ALTARMY_SV)
    store.save_characters(conn, FOREVER, chars)
    store.save_characters(conn, "tbc", chars[:2])
    assert store.load_characters(conn, FOREVER) == chars
    store.save_characters(conn, FOREVER, chars[:1])
    assert store.load_characters(conn, FOREVER) == chars[:1]
    assert store.load_characters(conn, "tbc") == chars[:2]  # each version has its own characters


def test_ah_blocked_round_trip_survives_ingest(db2_paths: dict[str, Path], conn: Connection) -> None:
    ingest.build_db(db2_paths, conn, FOREVER)
    assert store.load_ah_blocked(conn, FOREVER) == []
    store.set_ah_blocked(conn, FOREVER, 3, True)
    store.set_ah_blocked(conn, FOREVER, 3, True)  # already there: kept once
    store.set_ah_blocked(conn, FOREVER, 1, True)
    ingest.build_db(db2_paths, conn, FOREVER)
    assert sorted(i for i, _ in store.load_ah_blocked(conn, FOREVER)) == [1, 3]
    assert store.load_ah_blocked(conn, "tbc") == []
    store.set_ah_blocked(conn, FOREVER, 1, False)
    store.set_ah_blocked(conn, FOREVER, 42, False)  # not there: nothing to do
    ((item_id, added_at),) = store.load_ah_blocked(conn, FOREVER)
    assert item_id == 3
    assert len(added_at) == len("2026-09-24 20:53:16")  # UTC text


def test_load_market_prices_from_one_auction_house(db2_paths: dict[str, Path], conn: Connection) -> None:
    ingest.build_db(db2_paths, conn, FOREVER)
    here = set_prices(conn, {1: 20})
    there = set_prices(conn, {1: 99}, realm="Elsewhere")
    assert store.load_market(conn, FOREVER, here).prices == {1: 20}
    assert store.load_market(conn, FOREVER, there).prices == {1: 99}
    assert store.load_market(conn, FOREVER, None).prices == {}
    assert store.load_market(conn, "tbc", here).items == {}  # game data is per version
