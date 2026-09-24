"""Write data/tbc/disenchant.csv from Auctionator's disenchant brackets.

Usage: python scripts/build_disenchant.py [--auctionator <Interface/AddOns/Auctionator folder>]
Without --auctionator it uses the copy installed in the TBC Anniversary client (`_anniversary_`) under the
usual WoW install folders. Then run a TBC game data update (or `altarmy-profit --game-version tbc ingest`).
The Forever table (data/forever/disenchant.csv) is hand-checked and is not regenerated.
"""

import argparse
import csv
import sys
from pathlib import Path

from altarmy_profit import disenchant_rates, prices

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "tbc" / "disenchant.csv"
COLUMNS = [
    "item_class",
    "quality",
    "min_ilvl",
    "max_ilvl",
    "result_item_id",
    "chance",
    "min_count",
    "max_count",
]


def installed_addon() -> Path | None:
    for root in prices.WOW_ROOTS:
        addon = root / "_anniversary_" / "Interface" / "AddOns" / "Auctionator"
        if disenchant_rates.auctionator_table(addon).is_file():
            return addon
    return None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--auctionator", type=Path, help="Auctionator's addon folder")
    args = p.parse_args()
    addon = args.auctionator or installed_addon()
    if addon is None:
        sys.exit("Auctionator not found under the TBC client; pass --auctionator <its addon folder>.")
    source = disenchant_rates.auctionator_table(addon)
    parsed = list(disenchant_rates.parse(source.read_text(encoding="utf-8")))
    rows = disenchant_rates.to_rows(parsed, disenchant_rates.TBC_MAX_ILVL)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow(
                [
                    r.item_class,
                    r.quality,
                    r.min_ilvl,
                    r.max_ilvl,
                    r.result_item_id,
                    f"{r.chance:g}",
                    r.min_count,
                    r.max_count,
                ]
            )
    print(f"wrote {len(rows)} rows from {source} to {OUT}")


if __name__ == "__main__":
    main()
