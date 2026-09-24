"""Time loading the market and ranking recipes for each realm/faction's characters. Read-only.

Usage: python scripts/bench_rank.py [--game-version forever|tbc] [--altarmy <AltArmy_TBC.lua>] [--repeat N]
Characters come from --altarmy if given, else from the database (as last synced). Prices are the selected
realm's auction house's. The database is DATABASE_URL, else data/altarmy-profit.sqlite. Prints the best of N
runs per step.
"""

import argparse
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TypeVar

from altarmy_profit import altarmy, db, prices, service, store, versions
from altarmy_profit.engine import Filters

T = TypeVar("T")


def best_of(n: int, fn: Callable[[], T]) -> tuple[float, T]:
    """The fastest of `n` runs (at least one) and the last result."""
    times = []
    for _ in range(max(1, n)):
        start = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - start)
    return min(times), out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--game-version", choices=list(versions.VERSIONS), default=versions.DEFAULT_VERSION)
    p.add_argument("--altarmy", type=Path, help="Alt Army SavedVariables to take characters from")
    p.add_argument("--repeat", type=int, default=3)
    args = p.parse_args()
    v = versions.VERSIONS[args.game_version]
    database = db.Database(db.default_url())
    conn = database.connect()
    ah = service.selected_auction_house(conn, db.LOCAL_UID, v.key)
    print(
        f"{v.label}: build {db.get_build(conn, v.key)}, {db.count_rows(conn, 'items', v.key)} items, "
        f"{db.count_rows(conn, 'recipes', v.key)} recipes, {prices.count_current(conn, ah)} prices"
    )
    load, market = best_of(
        args.repeat, partial(store.load_market, conn, v.key, ah, ah_cut=v.ah_cut, mail_postage=v.mail_postage)
    )
    print(f"load_market: {load:.3f}s")
    chars = (
        altarmy.parse_characters(args.altarmy.read_bytes())
        if args.altarmy
        else store.load_characters(conn, db.LOCAL_UID, v.key)
    )
    everything = Filters(min_profit=-(10**18))
    print(f"{'realm (faction)':<32} {'chars':>5} {'learned':>16} {'+ unlearned':>16}")
    for g in altarmy.groups(chars):
        cells = []
        for unlearned in (False, True):
            search = partial(service.search, market, g.characters, unlearned, everything)
            secs, results = best_of(args.repeat, search)
            cells.append(f"{secs:6.3f}s {len(results):>5}")
        print(f"{g.realm + ' (' + g.faction + ')':<32} {len(g.characters):>5} {cells[0]:>16} {cells[1]:>16}")
    conn.close()
    database.dispose()


if __name__ == "__main__":
    main()
