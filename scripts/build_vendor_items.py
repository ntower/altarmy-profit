"""Regenerate data/vendor_items.csv from vmangos' world database (downloaded once into cache/vmangos).

Usage: python scripts/build_vendor_items.py
Then run a game data update (or `altarmy-profit ingest`) to load it.
"""

import sqlite3
from pathlib import Path

from altarmy_profit import vmangos

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "vendor_items.csv"

world = vmangos.download_world_db(ROOT / "cache")
conn = sqlite3.connect(world)
rows = vmangos.vendor_items(conn)
conn.close()
vmangos.write_csv(rows, OUT)
print(f"wrote {len(rows)} vendor items to {OUT}")
