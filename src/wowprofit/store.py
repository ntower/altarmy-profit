"""Load SQLite data into the engine's plain dataclasses."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import prices
from .engine import DisenchantRow, Item, Market, Recipe

DISENCHANT_CSV = Path("data/disenchant.csv")
CACHE_DIR = Path("cache")


def load_market(conn: sqlite3.Connection) -> Market:
    items = {
        r["id"]: Item(r["id"], r["name"], r["quality"], r["item_level"], r["class_id"], r["sell_price"])
        for r in conn.execute("SELECT * FROM items")
    }
    reagents: dict[int, list[tuple[int, int]]] = {}
    for r in conn.execute("SELECT recipe_id, item_id, count FROM recipe_reagents"):
        reagents.setdefault(r["recipe_id"], []).append((r["item_id"], r["count"]))
    recipes = [
        Recipe(
            r["id"],
            r["name"],
            r["output_item_id"],
            r["output_count"],
            tuple(reagents.get(r["id"], ())),
            r["skill_name"],
            r["min_skill"],
        )
        for r in conn.execute("SELECT * FROM recipes")
    ]
    de = [DisenchantRow(*tuple(r)) for r in conn.execute("SELECT * FROM disenchant")]
    return Market(items, recipes, prices.load_prices(conn), de)
