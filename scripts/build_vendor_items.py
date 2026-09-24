"""Regenerate data/<version>/vendor_items.csv from an open-source world database.

Forever (vanilla-based) reads vmangos' database, TBC reads cmangos' tbc-db; each is downloaded once into
cache/. Usage: python scripts/build_vendor_items.py [--game-version forever|tbc]
Then run that version's game data update (or `altarmy-profit --game-version <v> ingest`) to load it.
"""

import argparse
import sqlite3
from pathlib import Path

from altarmy_profit import cmangos, versions, vmangos

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--game-version", choices=list(versions.VERSIONS), default=versions.DEFAULT_VERSION)
    args = p.parse_args()
    source = cmangos if args.game_version == "tbc" else vmangos
    out = ROOT / versions.VERSIONS[args.game_version].vendor_csv
    world = source.download_world_db(ROOT / "cache")
    conn = sqlite3.connect(world)
    rows = source.vendor_items(conn)
    conn.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    vmangos.write_csv(rows, out)
    print(f"wrote {len(rows)} vendor items to {out}")


if __name__ == "__main__":
    main()
