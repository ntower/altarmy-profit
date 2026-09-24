"""Which items vendors sell, from vmangos' open-source vanilla (1.12) world database.

DB2 does not say what vendors sell (that is server-side data), so `scripts/build_vendor_items.py` uses
this to regenerate `data/vendor_items.csv`, which ingest loads. The price comes from DB2's BuyPrice.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import zipfile
from pathlib import Path

from .ingest import _fetch

RELEASE_URL = "https://api.github.com/repos/vmangos/core/releases/tags/db_latest"
WORLD_DB = "mangos.sqlite"

# Items with unlimited stock and no condition (reputation, event, ...), sold by a vendor that spawns in
# the world, either directly or through a vendor template. A creature spawn can pick from up to five ids.
VENDOR_ITEMS_SQL = """
WITH spawned(entry) AS (
    SELECT id FROM creature UNION SELECT id2 FROM creature UNION SELECT id3 FROM creature
    UNION SELECT id4 FROM creature UNION SELECT id5 FROM creature
),
sold(item) AS (
    SELECT v.item FROM npc_vendor v JOIN spawned s ON s.entry = v.entry
    WHERE v.maxcount = 0 AND v.condition_id = 0
    UNION
    SELECT v.item FROM npc_vendor_template v
    JOIN creature_template ct ON ct.vendor_id = v.entry
    JOIN spawned s ON s.entry = ct.entry
    WHERE v.maxcount = 0 AND v.condition_id = 0
)
SELECT sold.item,
       (SELECT name FROM item_template it WHERE it.entry = sold.item ORDER BY patch DESC LIMIT 1)
FROM sold ORDER BY sold.item
"""


def vendor_items(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """(item id, name) of every item a vendor sells without limit."""
    return [(int(i), str(name or "")) for i, name in conn.execute(VENDOR_ITEMS_SQL)]


def world_db_url(release: bytes) -> tuple[str, str]:
    """(file name, download URL) of the SQLite dump in vmangos' db_latest release JSON."""
    for asset in json.loads(release)["assets"]:
        if asset["name"].startswith("db-sqlite-") and asset["name"].endswith(".zip"):
            return str(asset["name"]), str(asset["browser_download_url"])
    raise ValueError("no db-sqlite-*.zip asset in vmangos' db_latest release")


def download_world_db(cache_dir: Path) -> Path:
    """Download (cached per release file) and extract vmangos' world database; returns its path."""
    name, url = world_db_url(_fetch(RELEASE_URL))
    dest = cache_dir / "vmangos" / name.removesuffix(".zip")
    world = dest / WORLD_DB
    if not world.exists():
        dest.mkdir(parents=True, exist_ok=True)
        archive = dest / name
        archive.write_bytes(_fetch(url))
        with zipfile.ZipFile(archive) as z:
            member = next(m for m in z.namelist() if m.endswith("/" + WORLD_DB))
            world.write_bytes(z.read(member))
        archive.unlink()
    return world


def write_csv(rows: list[tuple[int, str]], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["item_id", "name"])
        w.writerows(rows)
