"""Load SQLite data into the engine's plain dataclasses."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, fields
from pathlib import Path

from . import prices
from .engine import DisenchantRow, Item, Market, Recipe

DISENCHANT_CSV = Path("data/disenchant.csv")
CACHE_DIR = Path("cache")
SQLITE_MAX_VARIABLES = 900  # stay under older SQLite builds' 999 bound parameters


@dataclass(frozen=True)
class ItemDetails:
    """What an item tooltip shows. Not needed by the engine, so it is not part of engine.Item."""

    id: int
    name: str
    quality: int
    class_id: int
    subclass_name: str | None
    inventory_type: int
    bonding: int
    item_delay: int  # ms
    container_slots: int
    required_level: int
    required_skill: str | None
    required_skill_rank: int
    description: str | None
    sell_price: int
    icon: str | None


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


def load_item_details(conn: sqlite3.Connection, ids: Iterable[int]) -> dict[int, ItemDetails]:
    """Tooltip details for the given item ids; unknown ids are left out."""
    wanted = sorted(set(ids))
    columns = ", ".join(f.name for f in fields(ItemDetails))
    out: dict[int, ItemDetails] = {}
    for start in range(0, len(wanted), SQLITE_MAX_VARIABLES):
        chunk = wanted[start : start + SQLITE_MAX_VARIABLES]
        query = f"SELECT {columns} FROM items WHERE id IN ({', '.join('?' * len(chunk))})"
        for r in conn.execute(query, chunk):
            out[r["id"]] = ItemDetails(*r)
    return out
