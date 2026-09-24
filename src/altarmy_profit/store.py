"""Load SQLite data into the engine's plain dataclasses."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from pathlib import Path

from . import prices
from .altarmy import Character, Profession
from .engine import AH_CUT, MAIL_POSTAGE, DisenchantRow, Item, Market, Recipe

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


def load_market(
    conn: sqlite3.Connection, *, ah_cut: float = AH_CUT, mail_postage: int = MAIL_POSTAGE
) -> Market:
    """The database as a Market, with the game version's AH cut and postage per attachment."""
    items = {
        r["id"]: Item(
            r["id"],
            r["name"],
            r["quality"],
            r["item_level"],
            r["class_id"],
            r["sell_price"],
            -(-r["buy_price"] // r["buy_count"]) if r["sold"] and r["buy_price"] > 0 else None,
            r["stack_size"],
        )
        for r in conn.execute(
            "SELECT i.*, v.item_id IS NOT NULL AS sold FROM items i"
            " LEFT JOIN vendor_items v ON v.item_id = i.id"
        )
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
            r["spell_id"],
            r["trivial_low"],
            r["trivial_high"],
        )
        for r in conn.execute("SELECT * FROM recipes")
    ]
    de = [DisenchantRow(*tuple(r)) for r in conn.execute("SELECT * FROM disenchant")]
    return Market(items, recipes, prices.load_prices(conn), de, ah_cut, mail_postage=mail_postage)


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


def save_characters(conn: sqlite3.Connection, chars: Sequence[Character]) -> None:
    """Replace every stored character with `chars` (Alt Army's file is the source of truth)."""
    with conn:
        for table in ("character_recipes", "character_professions", "characters"):
            conn.execute(f"DELETE FROM {table}")
        for c in chars:
            cur = conn.execute(
                "INSERT INTO characters(realm, name, faction, class_file, level) VALUES (?,?,?,?,?)",
                (c.realm, c.name, c.faction, c.class_file, c.level),
            )
            for p in c.professions:
                conn.execute(
                    "INSERT INTO character_professions VALUES (?,?,?,?)",
                    (cur.lastrowid, p.name, p.rank, p.max_rank),
                )
                conn.executemany(
                    "INSERT INTO character_recipes VALUES (?,?,?)",
                    [(cur.lastrowid, p.name, spell) for spell in sorted(p.recipe_ids)],
                )


def load_characters(conn: sqlite3.Connection) -> list[Character]:
    """Stored characters sorted by realm then name, professions sorted by name."""
    recipes: dict[tuple[int, str], set[int]] = {}
    for r in conn.execute("SELECT * FROM character_recipes"):
        recipes.setdefault((r["character_id"], r["skill_name"]), set()).add(r["spell_id"])
    profs: dict[int, list[Profession]] = {}
    for r in conn.execute("SELECT * FROM character_professions ORDER BY skill_name"):
        key = (r["character_id"], r["skill_name"])
        profs.setdefault(r["character_id"], []).append(
            Profession(r["skill_name"], r["rank"], r["max_rank"], frozenset(recipes.get(key, ())))
        )
    return [
        Character(
            r["realm"], r["name"], r["faction"], r["class_file"], r["level"], tuple(profs.get(r["id"], ()))
        )
        for r in conn.execute("SELECT * FROM characters ORDER BY realm, name")
    ]


def load_ah_blocked(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """Items never to sell on the AH as (item id, when added, UTC CURRENT_TIMESTAMP text), newest first."""
    rows = conn.execute("SELECT item_id, added_at FROM ah_blocked ORDER BY added_at DESC, item_id")
    return [(r["item_id"], r["added_at"]) for r in rows]


def set_ah_blocked(conn: sqlite3.Connection, item_id: int, blocked: bool) -> None:
    """Never sell `item_id` on the AH, or allow it again."""
    with conn:
        if blocked:
            conn.execute("INSERT OR IGNORE INTO ah_blocked(item_id) VALUES (?)", (item_id,))
        else:
            conn.execute("DELETE FROM ah_blocked WHERE item_id = ?", (item_id,))
