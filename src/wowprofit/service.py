"""Use-cases behind the web API: the shared market cache, search, and the Manage actions. No HTTP here."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path

from . import db, ingest, prices, store
from .engine import PROFESSIONS, Market, Result, recipes_for_professions


class MarketCache:
    """One in-process Market shared by all requests; rebuilt from SQLite lazily after invalidate().

    Market is read-only once built, so handing the same instance to several threads is safe.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._market: Market | None = None

    def get(self) -> Market:
        with self._lock:
            if self._market is None:
                conn = db.connect(self.db_path)
                try:
                    db.init_schema(conn)
                    self._market = store.load_market(conn)
                finally:
                    conn.close()
            return self._market

    def invalidate(self) -> None:
        with self._lock:
            self._market = None


def available_professions(market: Market) -> list[str]:
    present = {r.skill_name for r in market.recipes}
    return [p for p in PROFESSIONS if p in present]


def search(base: Market, professions: Iterable[str], min_profit: int, top: int) -> list[Result]:
    """Rank recipes of the given professions. Chains only sub-craft through those professions too."""
    market = Market(
        base.items, recipes_for_professions(base.recipes, professions), base.prices, base.disenchant
    )
    return market.rank(min_profit=min_profit)[:top]


def default_auctionator_path(files: list[str], last: str | None) -> str | None:
    """The last imported file (even a pasted one), else the first WoW: Forever file, else the first."""
    if last:
        return last
    forever = [f for f in files if "_classic_beta_" in f]
    return forever[0] if forever else (files[0] if files else None)


def default_realm(realms: list[str], last: str | None) -> str | None:
    if last in realms:
        return last
    return realms[0] if realms else None


def update_game_data(
    conn: sqlite3.Connection, cache_dir: Path, disenchant_csv: Path
) -> tuple[str, dict[str, int]]:
    """Download the newest build's DB2 tables and rebuild items/recipes (prices are kept)."""
    build = ingest.latest_build()
    return build, ingest.update(conn, build, cache_dir, disenchant_csv)


def import_auctionator(conn: sqlite3.Connection, path: Path, realm: str) -> tuple[str, int, int]:
    """Import one realm's prices and remember the file and realm for next time."""
    result = prices.import_auctionator(conn, path, realm)
    db.set_meta(conn, "auctionator_path", str(path))
    db.set_meta(conn, "auctionator_realm", result[0])
    return result
