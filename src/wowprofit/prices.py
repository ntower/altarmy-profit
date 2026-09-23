"""Price sources. Every source ends up as rows in the `prices` table (copper per item).

Implemented: CSV import (item_id or item name). Planned: parsing an AH scanner addon's
SavedVariables Lua file (Auctionator etc.) once we know what Forever's client produces.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


def import_csv(conn: sqlite3.Connection, path: Path, source: str = "csv") -> tuple[int, list[str]]:
    """CSV columns: `item_id` or `name`, plus `price` in copper. Returns (imported, unresolved)."""
    imported, unresolved = 0, []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            item_id = row.get("item_id")
            if not item_id:
                name = (row.get("name") or "").strip()
                found = conn.execute(
                    "SELECT id FROM items WHERE name = ? COLLATE NOCASE ORDER BY id LIMIT 1", (name,)
                ).fetchone()
                if not found:
                    unresolved.append(name)
                    continue
                item_id = found["id"]
            set_price(conn, int(item_id), int(row["price"]), source)
            imported += 1
    conn.commit()
    return imported, unresolved


def set_price(conn: sqlite3.Connection, item_id: int, price: int, source: str = "manual") -> None:
    conn.execute(
        "INSERT INTO prices(item_id, price, source) VALUES (?,?,?) "
        "ON CONFLICT(item_id) DO UPDATE SET price=excluded.price, source=excluded.source, "
        "updated_at=CURRENT_TIMESTAMP",
        (item_id, price, source),
    )


def load_prices(conn: sqlite3.Connection) -> dict[int, int]:
    return {r["item_id"]: r["price"] for r in conn.execute("SELECT item_id, price FROM prices")}
