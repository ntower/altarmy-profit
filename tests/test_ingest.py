import sqlite3
from pathlib import Path

from wowprofit import ingest

from .conftest import write_csv


def test_build_db_loads_items_and_recipes(db2_paths: dict[str, Path], conn: sqlite3.Connection) -> None:
    stats = ingest.build_db(db2_paths, conn)
    assert stats == {"items": 3, "recipes": 1, "disenchant_rows": 0}

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


def test_int_parsing_is_forgiving() -> None:
    assert ingest._int("12") == 12
    assert ingest._int("3.0") == 3
    assert ingest._int("") == 0
    assert ingest._int(None, 7) == 7
    assert ingest._int("abc", 5) == 5
