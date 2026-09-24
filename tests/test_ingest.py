import json
from pathlib import Path

import pytest
from sqlalchemy import Connection, func, select
from sqlalchemy.engine import Row

from altarmy_profit import db, ingest, prices, schema, store

from .conftest import FOREVER, set_prices, write_csv


def item(conn: Connection, item_id: int, game_version: str = FOREVER) -> Row[tuple[object, ...]]:
    t = schema.items
    return conn.execute(select(t).where(t.c.game_version == game_version, t.c.id == item_id)).one()


def count(conn: Connection, table: str) -> int:
    return int(conn.execute(select(func.count()).select_from(schema.metadata.tables[table])).scalar_one())


def test_build_db_loads_items_and_recipes(db2_paths: dict[str, Path], conn: Connection) -> None:
    stats = ingest.build_db(db2_paths, conn, FOREVER)
    assert stats == {"items": 3, "recipes": 1, "disenchant_rows": 0, "vendor_items": 0}

    robe = item(conn, 3)
    assert (robe.name, robe.quality, robe.item_level, robe.class_id, robe.sell_price) == (
        "Green Robe",
        2,
        20,
        4,
        500,
    )

    recipe = conn.execute(select(schema.recipes)).one()
    assert (recipe.id, recipe.name, recipe.skill_name, recipe.output_item_id) == (
        100,
        "Green Robe",
        "Tailoring",
        3,
    )
    assert recipe.min_skill == 25 and recipe.output_count == 1

    rr = schema.recipe_reagents
    reagents = [tuple(r) for r in conn.execute(select(rr.c.slot, rr.c.item_id, rr.c.count))]
    assert sorted(reagents) == [(0, 1, 10), (1, 2, 1)]


def test_build_db_loads_tooltip_fields(db2_paths: dict[str, Path], conn: Connection) -> None:
    ingest.build_db(db2_paths, conn, FOREVER)
    robe = item(conn, 3)._mapping
    assert {k: robe[k] for k in TOOLTIP_COLUMNS} == {
        "bonding": 2,
        "required_level": 12,
        "inventory_type": 20,
        "item_delay": 0,
        "container_slots": 0,
        "subclass_name": "Cloth",
        "required_skill": "Tailoring",
        "required_skill_rank": 50,
        "description": "Soft and green.",
        "icon": "inv_chest_cloth_39",
    }
    assert (item(conn, 1).icon, item(conn, 2).icon) == ("inv_fabric_linen_01", None)  # 2: not in the manifest
    linen = item(conn, 1)
    assert (linen.subclass_name, linen.required_skill, linen.description) == (None, None, None)


TOOLTIP_COLUMNS = {
    "bonding",
    "required_level",
    "inventory_type",
    "item_delay",
    "container_slots",
    "subclass_name",
    "required_skill",
    "required_skill_rank",
    "description",
    "icon",
}


def test_build_db_preserves_prices_and_other_versions(db2_paths: dict[str, Path], conn: Connection) -> None:
    ah = set_prices(conn, {1: 45})
    ingest.build_db(db2_paths, conn, "tbc")
    ingest.build_db(db2_paths, conn, FOREVER)
    ingest.build_db(db2_paths, conn, FOREVER)  # idempotent rebuild
    assert prices.load_current(conn, ah) == {1: 45}
    assert count(conn, "recipes") == 2  # one per version
    assert store.load_market(conn, "tbc", None).items.keys() == {1, 2, 3}


def test_build_db_loads_disenchant_csv(db2_paths: dict[str, Path], conn: Connection, tmp_path: Path) -> None:
    de = write_csv(
        tmp_path / "de.csv",
        [
            "item_class",
            "quality",
            "min_ilvl",
            "max_ilvl",
            "result_item_id",
            "chance",
            "min_count",
            "max_count",
        ],
        [
            {
                "item_class": 4,
                "quality": 2,
                "min_ilvl": 15,
                "max_ilvl": 25,
                "result_item_id": 9,
                "chance": 0.75,
                "min_count": 1,
                "max_count": 2,
            }
        ],
    )
    assert ingest.build_db(db2_paths, conn, FOREVER, de)["disenchant_rows"] == 1
    ((row),) = store.load_market(conn, FOREVER, None).disenchant
    assert (row.result_item_id, row.chance, row.max_count) == (9, 0.75, 2)


def test_build_db_loads_vendor_items(db2_paths: dict[str, Path], conn: Connection, vendor_csv: Path) -> None:
    assert ingest.build_db(db2_paths, conn, FOREVER, vendor_csv=vendor_csv)["vendor_items"] == 2
    assert sorted(conn.execute(select(schema.vendor_items.c.item_id)).scalars()) == [2, 99]
    thread = item(conn, 2)
    assert (thread.buy_price, thread.buy_count) == (51, 5)
    ingest.build_db(db2_paths, conn, FOREVER, vendor_csv=vendor_csv)  # rebuild replaces, not appends
    assert count(conn, "vendor_items") == 2


def test_int_parsing_is_forgiving() -> None:
    assert ingest._int("12") == 12
    assert ingest._int("3.0") == 3
    assert ingest._int("") == 0
    assert ingest._int(None, 7) == 7
    assert ingest._int("abc", 5) == 5


def test_parse_latest_build_picks_product() -> None:
    payload = json.dumps(
        {
            "wow": {"product": "wow", "version": "12.1.0.69933"},
            "wow_classic_beta": {"product": "wow_classic_beta", "version": "1.60.1.69977"},
        }
    ).encode()
    assert ingest.parse_latest_build(payload, "wow_classic_beta") == "1.60.1.69977"
    assert ingest.parse_latest_build(payload, "wow") == "12.1.0.69933"
    with pytest.raises(ValueError, match="wow_nope"):
        ingest.parse_latest_build(payload, "wow_nope")


def test_update_downloads_builds_and_records_build(
    db2_paths: dict[str, Path], conn: Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, Path]] = []

    def fake_download_all(build: str, cache_dir: Path) -> dict[str, Path]:
        calls.append((build, cache_dir))
        return db2_paths

    monkeypatch.setattr(ingest, "download_all", fake_download_all)
    stats = ingest.update(conn, FOREVER, "1.2.3.4", tmp_path / "cache")
    assert calls == [("1.2.3.4", tmp_path / "cache")]
    assert stats["recipes"] == 1
    assert db.get_build(conn, FOREVER) == "1.2.3.4"


@pytest.mark.parametrize(
    ("row", "count"),
    [
        ({"EffectBasePointsF": "3"}, 3),  # Forever: the (average) count as a float
        (
            {"EffectBasePointsF": "0", "EffectBasePoints": "2", "EffectDieSides": "1"},
            3,
        ),  # TBC Thorium Grenade
        ({"EffectBasePointsF": "0", "EffectBasePoints": "199", "EffectDieSides": "1"}, 200),  # Thorium Shells
        (
            {"EffectBasePointsF": "0", "EffectBasePoints": "0", "EffectDieSides": "5"},
            3,
        ),  # Heavy Dynamite: 1-5
        ({"EffectBasePointsF": "0", "EffectBasePoints": "1", "EffectDieSides": "3"}, 3),  # Iron Grenade: 2-4
        ({"EffectBasePointsF": "0", "EffectBasePoints": "0", "EffectDieSides": "0"}, 1),
        ({"EffectBasePointsF": ""}, 1),  # no count columns at all
    ],
)
def test_output_count_from_either_clients_spell_effect(row: dict[str, str], count: int) -> None:
    assert ingest.output_count(row) == count


def test_build_db_reads_tbc_style_output_counts(db2_paths: dict[str, Path], conn: Connection) -> None:
    write_csv(
        db2_paths["SpellEffect"],
        [
            "ID",
            "Effect",
            "EffectItemType",
            "EffectBasePointsF",
            "EffectBasePoints",
            "EffectDieSides",
            "SpellID",
        ],
        [
            {
                "ID": 1,
                "Effect": 24,
                "EffectItemType": 3,
                "EffectBasePointsF": 0,
                "EffectBasePoints": 2,
                "EffectDieSides": 1,
                "SpellID": 900,
            }
        ],
    )
    ingest.build_db(db2_paths, conn, FOREVER)
    assert conn.execute(select(schema.recipes.c.output_count)).scalar_one() == 3
