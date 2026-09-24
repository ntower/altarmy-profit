"""Which items vendors sell, from cmangos' open-source TBC (2.4.3) world database.

DB2 does not say what vendors sell (that is server-side data), so `scripts/build_vendor_items.py` uses this
to regenerate `data/tbc/vendor_items.csv`, which ingest loads. The price comes from DB2's BuyPrice. The
vanilla counterpart is `vmangos.py`.
"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

from .ingest import _fetch

RELEASE_URL = "https://api.github.com/repos/cmangos/tbc-db/releases/tags/latest"
ASSET = "tbc-sqlite-db.zip"
WORLD_DB = "tbcmangos.sqlite"

# Items with unlimited stock, no condition and no token cost (ExtendedCost: honor, badges, ...), sold by a
# vendor that spawns in the world, directly or through a vendor template. A spawn names its creature in
# `creature.id`, or picks one of several from `creature_spawn_entry` (then `id` is 0).
VENDOR_ITEMS_SQL = """
WITH spawned(entry) AS (
    SELECT id FROM creature WHERE id > 0 UNION SELECT entry FROM creature_spawn_entry
),
sold(item) AS (
    SELECT v.item FROM npc_vendor v JOIN spawned s ON s.entry = v.entry
    WHERE v.maxcount = 0 AND v.condition_id = 0 AND v.ExtendedCost = 0
    UNION
    SELECT v.item FROM npc_vendor_template v
    JOIN creature_template ct ON ct.VendorTemplateId = v.entry
    JOIN spawned s ON s.entry = ct.Entry
    WHERE v.maxcount = 0 AND v.condition_id = 0 AND v.ExtendedCost = 0
)
SELECT sold.item, (SELECT name FROM item_template it WHERE it.entry = sold.item)
FROM sold ORDER BY sold.item
"""


def vendor_items(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """(item id, name) of every item a vendor sells without limit for gold."""
    return [(int(i), str(name or "")) for i, name in conn.execute(VENDOR_ITEMS_SQL)]


def world_db_url(release: bytes) -> tuple[str, str]:
    """(release date, download URL) of the SQLite dump in cmangos' `latest` release JSON."""
    for asset in json.loads(release)["assets"]:
        if asset["name"] == ASSET:
            return str(asset["updated_at"])[:10], str(asset["browser_download_url"])
    raise ValueError(f"no {ASSET} asset in cmangos' latest tbc-db release")


def download_world_db(cache_dir: Path) -> Path:
    """Download (cached per release date) and extract cmangos' TBC world database; returns its path."""
    date, url = world_db_url(_fetch(RELEASE_URL))
    dest = cache_dir / "cmangos" / date
    world = dest / WORLD_DB
    if not world.exists():
        dest.mkdir(parents=True, exist_ok=True)
        archive = dest / ASSET
        archive.write_bytes(_fetch(url))
        with zipfile.ZipFile(archive) as z:
            world.write_bytes(z.read(WORLD_DB))
        archive.unlink()
    return world
