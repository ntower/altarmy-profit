"""Price sources. Every source ends up as rows in the `prices` table (copper per item).

Implemented: CSV import (item_id or item name) and Auctionator's SavedVariables price database.
"""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from . import auctionator


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


WOW_ROOTS = [
    Path(r"C:\Program Files (x86)\World of Warcraft"),
    Path(r"C:\Program Files\World of Warcraft"),
    Path(r"D:\World of Warcraft"),
]


def find_auctionator_files(roots: Iterable[Path] = WOW_ROOTS) -> list[Path]:
    """Account-wide Auctionator SavedVariables under each WoW install's flavor folders (_retail_, ...)."""
    found: list[Path] = []
    for root in roots:
        found += sorted(root.glob("_*_/WTF/Account/*/SavedVariables/Auctionator.lua"))
    return found


def auctionator_realms(path: Path) -> list[str]:
    return sorted(auctionator.parse_price_database(path.read_bytes()))


def import_auctionator(
    conn: sqlite3.Connection, path: Path, realm: str | None = None
) -> tuple[str, int, int]:
    """Import the latest minimum buyouts for one realm. Returns (realm, imported, not in `items`).

    `realm` may be omitted when the file holds a single realm. Items missing from this scan keep
    their previous price.
    """
    realms = auctionator.parse_price_database(path.read_bytes())
    if realm is None:
        if len(realms) != 1:
            raise ValueError(
                f"file has {len(realms)} realms, pick one with --realm: {', '.join(sorted(realms))}"
            )
        (realm,) = realms
    elif realm not in realms:
        raise ValueError(f"realm {realm!r} not in file; found: {', '.join(sorted(realms))}")
    known = {r[0] for r in conn.execute("SELECT id FROM items")}
    item_prices = realms[realm]
    for item_id, price in item_prices.items():
        set_price(conn, item_id, price, "auctionator")
    conn.commit()
    return realm, len(item_prices), len(item_prices.keys() - known)


def set_price(conn: sqlite3.Connection, item_id: int, price: int, source: str = "manual") -> None:
    conn.execute(
        "INSERT INTO prices(item_id, price, source) VALUES (?,?,?) "
        "ON CONFLICT(item_id) DO UPDATE SET price=excluded.price, source=excluded.source, "
        "updated_at=CURRENT_TIMESTAMP",
        (item_id, price, source),
    )


def load_prices(conn: sqlite3.Connection) -> dict[int, int]:
    return {r["item_id"]: r["price"] for r in conn.execute("SELECT item_id, price FROM prices")}
