import json
import sqlite3
from pathlib import Path

import pytest

from altarmy_profit import db, ingest

from .conftest import write_csv


def test_build_db_loads_items_and_recipes(db2_paths: dict[str, Path], conn: sqlite3.Connection) -> None:
    stats = ingest.build_db(db2_paths, conn)
    assert stats == {"items": 3, "recipes": 1, "disenchant_rows": 0, "vendor_items": 0}

    robe = conn.execute("SELECT * FROM items WHERE id = 3").fetchone()
    assert (robe["name"], robe["quality"], robe["item_level"], robe["class_id"], robe["sell_price"]) == (
        "Green Robe",
        2,
        20,
        4,
        500,
    )

    recipe = conn.execute("SELECT * FROM recipes").fetchone()
    assert (recipe["id"], recipe["name"], recipe["skill_name"], recipe["output_item_id"]) == (
        100,
        "Green Robe",
        "Tailoring",
        3,
    )
    assert recipe["min_skill"] == 25 and recipe["output_count"] == 1

    reagents = {r["item_id"]: r["count"] for r in conn.execute("SELECT * FROM recipe_reagents")}
    assert reagents == {1: 10, 2: 1}


def test_build_db_loads_tooltip_fields(db2_paths: dict[str, Path], conn: sqlite3.Connection) -> None:
    ingest.build_db(db2_paths, conn)
    robe = conn.execute("SELECT * FROM items WHERE id = 3").fetchone()
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
    icons = dict(conn.execute("SELECT id, icon FROM items WHERE id IN (1, 2)").fetchall())
    assert icons == {1: "inv_fabric_linen_01", 2: None}  # 2's icon file is not in the manifest
    linen = conn.execute(
        "SELECT subclass_name, required_skill, description FROM items WHERE id = 1"
    ).fetchone()
    assert tuple(linen) == (None, None, None)


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


def test_build_db_preserves_prices(db2_paths: dict[str, Path], conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO prices(item_id, price) VALUES (1, 45)")
    ingest.build_db(db2_paths, conn)
    ingest.build_db(db2_paths, conn)  # idempotent rebuild
    assert conn.execute("SELECT price FROM prices WHERE item_id = 1").fetchone()["price"] == 45
    assert conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0] == 1


def test_build_db_loads_disenchant_csv(
    db2_paths: dict[str, Path], conn: sqlite3.Connection, tmp_path: Path
) -> None:
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
    assert ingest.build_db(db2_paths, conn, de)["disenchant_rows"] == 1


def test_build_db_loads_vendor_items(
    db2_paths: dict[str, Path], conn: sqlite3.Connection, vendor_csv: Path
) -> None:
    assert ingest.build_db(db2_paths, conn, vendor_csv=vendor_csv)["vendor_items"] == 2
    assert [r[0] for r in conn.execute("SELECT item_id FROM vendor_items")] == [2, 99]
    thread = conn.execute("SELECT buy_price, buy_count FROM items WHERE id = 2").fetchone()
    assert tuple(thread) == (51, 5)
    ingest.build_db(db2_paths, conn, vendor_csv=vendor_csv)  # rebuild replaces, not appends
    assert conn.execute("SELECT COUNT(*) FROM vendor_items").fetchone()[0] == 2


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
    assert ingest.parse_latest_build(payload) == "1.60.1.69977"
    assert ingest.parse_latest_build(payload, "wow") == "12.1.0.69933"
    with pytest.raises(ValueError, match="wow_nope"):
        ingest.parse_latest_build(payload, "wow_nope")


def test_update_downloads_builds_and_records_build(
    db2_paths: dict[str, Path], conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, Path]] = []

    def fake_download_all(build: str, cache_dir: Path) -> dict[str, Path]:
        calls.append((build, cache_dir))
        return db2_paths

    monkeypatch.setattr(ingest, "download_all", fake_download_all)
    stats = ingest.update(conn, "1.2.3.4", tmp_path / "cache")
    assert calls == [("1.2.3.4", tmp_path / "cache")]
    assert stats["recipes"] == 1
    assert db.get_meta(conn, "build") == "1.2.3.4"
