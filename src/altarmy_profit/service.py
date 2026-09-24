"""Use-cases behind the web API: the shared market cache, search, addon sync and the Manage actions.

No HTTP here. Characters come from the Alt Army addon and prices from Auctionator; `sync` re-reads either
SavedVariables file whenever the game has rewritten it (on logout or /reload).
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import altarmy, auctionator, db, ingest, prices, store
from .altarmy import Character
from .engine import ALL_EXITS, Choices, Crafter, Filters, Market, Result, recipes_for_characters


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


@dataclass(frozen=True)
class Selection:
    """Whose recipes count: every character of one realm and faction (they share an auction house)."""

    realm: str
    faction: str


def search(
    base: Market,
    chars: Sequence[Character],
    include_unlearned: bool,
    filters: Filters,
    exits: frozenset[str] = ALL_EXITS,
    no_ah: frozenset[int] = frozenset(),
    include_trivial: bool = True,
) -> list[Result]:
    """Rank what the characters can craft, selling only via `exits` (never items in `no_ah` on the AH),
    and keep what `filters` accepts. Chains sub-craft through any of their recipes too.

    `include_unlearned` widens that to every recipe of the characters' professions. Disenchanting needs
    an enchanter among them, plus postage unless one of the recipe's crafters enchants. Without
    `include_trivial` the final craft is only done by a character it can give a skillup.
    """
    market = _market(base, chars, include_unlearned, exits, no_ah, include_trivial)
    min_profit = filters.min_profit if filters.min_profit is not None else -(10**18)
    return [r for r in market.rank(min_profit=min_profit) if filters.accepts(r)]


def evaluate(
    base: Market,
    chars: Sequence[Character],
    include_unlearned: bool,
    exits: frozenset[str],
    recipe_id: int,
    choices: Choices,
    no_ah: frozenset[int] = frozenset(),
    include_trivial: bool = True,
) -> Result | None:
    """One recipe as `search` would rank it, but with the user's `choices` of sources and exit; None if
    the characters can't make or sell it."""
    market = _market(base, chars, include_unlearned, exits, no_ah, include_trivial)
    recipe = next((r for r in market.recipes if r.id == recipe_id), None)
    return None if recipe is None else market.evaluate(recipe, choices)


def _market(
    base: Market,
    chars: Sequence[Character],
    include_unlearned: bool,
    exits: frozenset[str],
    no_ah: frozenset[int],
    include_trivial: bool,
) -> Market:
    """`base` narrowed to what the characters can craft (see `search`), with them as the crafters."""
    known = frozenset().union(*(c.known_recipes for c in chars))
    professions = {p.name for c in chars for p in c.professions}
    recipes = recipes_for_characters(base.recipes, known, professions, include_unlearned)
    crafters = [
        Crafter(c.name, tuple((p.name, p.rank, p.max_rank) for p in c.professions), c.known_recipes)
        for c in chars
    ]
    return Market(
        base.items,
        recipes,
        base.prices,
        base.disenchant,
        crafters=crafters,
        include_unlearned=include_unlearned,
        exits=exits,
        no_ah=no_ah,
        include_trivial=include_trivial,
    )


# --- realm/faction selection -----------------------------------------------------------------------
def selection(conn: sqlite3.Connection, chars: Sequence[Character]) -> Selection | None:
    """The saved realm/faction if it still has characters, else the group with the most characters."""
    groups = altarmy.groups(chars)
    realm, faction = db.get_meta(conn, "selected_realm"), db.get_meta(conn, "selected_faction")
    for g in groups:
        if (g.realm, g.faction) == (realm, faction):
            return Selection(g.realm, g.faction)
    if not groups:
        return None
    best = max(groups, key=lambda g: len(g.characters))
    return Selection(best.realm, best.faction)


def select(conn: sqlite3.Connection, realm: str, faction: str) -> None:
    if not any((g.realm, g.faction) == (realm, faction) for g in altarmy.groups(store.load_characters(conn))):
        raise ValueError(f"no characters on {realm} ({faction})")
    db.set_meta(conn, "selected_realm", realm)
    db.set_meta(conn, "selected_faction", faction)


def selected_characters(conn: sqlite3.Connection) -> tuple[Selection | None, list[Character]]:
    chars = store.load_characters(conn)
    sel = selection(conn, chars)
    if sel is None:
        return None, []
    return sel, [c for c in chars if (c.realm, c.faction) == (sel.realm, sel.faction)]


def match_auctionator_realm(realms: Iterable[str], realm: str, faction: str) -> str | None:
    """Auctionator's key for a realm: the realm name without spaces, plus the faction where the auction
    houses are split (e.g. "ClassicBetaPvE", "Dreamscythe Horde")."""
    have = set(realms)
    nospace = realm.replace(" ", "")
    for key in (f"{nospace} {faction}", nospace, f"{realm} {faction}", realm):
        if key in have:
            return key
    return None


# --- addon file sync -------------------------------------------------------------------------------
@dataclass(frozen=True)
class SyncResult:
    changed: bool  # characters or prices were re-imported: drop the cached market
    warnings: list[str]


def default_path(files: Sequence[str], last: str | None) -> str | None:
    """The last used file (even a pasted one), else the first WoW: Forever file, else the first."""
    if last:
        return last
    forever = [f for f in files if "_classic_beta_" in f]
    return forever[0] if forever else (files[0] if files else None)


def data_version(conn: sqlite3.Connection) -> int:
    """Bumped by every sync that changed something, so the front end knows to refetch."""
    return int(db.get_meta(conn, "data_version") or 0)


def set_sources(conn: sqlite3.Connection, altarmy_path: str | None, auctionator_path: str | None) -> None:
    """Point the sync at other SavedVariables files; None keeps that source as it is."""
    for key, path in (("altarmy_path", altarmy_path), ("auctionator_path", auctionator_path)):
        if path is None:
            continue
        if not Path(path).is_file():
            raise FileNotFoundError(f"File not found: {path}")
        db.set_meta(conn, key, path)


def sync(
    conn: sqlite3.Connection, roots: Iterable[Path] = prices.WOW_ROOTS, *, force: bool = False
) -> SyncResult:
    """Re-import Alt Army characters and the selected realm's Auctionator prices if either file changed.

    Unset paths are filled in from the files found under the WoW installs in `roots`.
    """
    roots = list(roots)
    warnings: list[str] = []
    changed = _sync_altarmy(conn, roots, force, warnings)
    changed = _sync_auctionator(conn, roots, force, warnings) or changed
    if changed:
        db.set_meta(conn, "data_version", str(data_version(conn) + 1))
    return SyncResult(changed, warnings)


def _source(
    conn: sqlite3.Connection, key: str, find: Callable[[Iterable[Path]], list[Path]], roots: list[Path]
) -> Path | None:
    path = db.get_meta(conn, key)
    if path is None:
        path = default_path([str(f) for f in find(roots)], None)
        if path is None:
            return None
        db.set_meta(conn, key, path)
    return Path(path)


def _changed_mtime(conn: sqlite3.Connection, path: Path, key: str, force: bool) -> str | None:
    """The file's mtime if it differs from the one stored under `key` (or `force`), else None."""
    mtime = str(path.stat().st_mtime_ns)
    return mtime if force or mtime != db.get_meta(conn, key) else None


def _sync_altarmy(conn: sqlite3.Connection, roots: list[Path], force: bool, warnings: list[str]) -> bool:
    path = _source(conn, "altarmy_path", prices.find_altarmy_files, roots)
    if path is None:
        warnings.append("No Alt Army file found. Pick AltArmy_TBC.lua on the Manage tab.")
        return False
    if not path.is_file():
        warnings.append(f"Alt Army file not found: {path}")
        return False
    mtime = _changed_mtime(conn, path, "altarmy_mtime", force)
    if mtime is None:
        return False
    try:
        chars = altarmy.parse_characters(path.read_bytes())
    except ValueError as e:
        warnings.append(f"Could not read {path}: {e}")
        return False
    store.save_characters(conn, chars)
    db.set_meta(conn, "altarmy_mtime", mtime)
    db.set_meta(conn, "altarmy_synced", _now())
    return True


def _sync_auctionator(conn: sqlite3.Connection, roots: list[Path], force: bool, warnings: list[str]) -> bool:
    sel = selection(conn, store.load_characters(conn))
    if sel is None:
        return False  # no characters yet, so no realm to price
    path = _source(conn, "auctionator_path", prices.find_auctionator_files, roots)
    if path is None:
        warnings.append("No Auctionator file found. Pick Auctionator.lua on the Manage tab.")
        return False
    if not path.is_file():
        warnings.append(f"Auctionator file not found: {path}")
        return False
    wanted = f"{sel.realm}\t{sel.faction}"
    moved = wanted != db.get_meta(conn, "auctionator_for")
    mtime = _changed_mtime(conn, path, "auctionator_mtime", force or moved)
    if mtime is None:
        if not db.get_meta(conn, "auctionator_realm"):
            warnings.append(_no_prices(sel))
        return False
    try:
        realms = auctionator.parse_price_database(path.read_bytes())
    except ValueError as e:
        warnings.append(f"Could not read {path}: {e}")
        return False
    key = match_auctionator_realm(realms, sel.realm, sel.faction)
    # Without a match, drop the previous realm's prices rather than rank with them.
    prices.replace_auctionator_prices(conn, {} if key is None else realms[key])
    if key is None:
        warnings.append(_no_prices(sel))
    db.set_meta(conn, "auctionator_realm", key or "")
    db.set_meta(conn, "auctionator_for", wanted)
    db.set_meta(conn, "auctionator_mtime", mtime)
    db.set_meta(conn, "auctionator_synced", _now())
    return True


def _now() -> str:
    """UTC, in SQLite's CURRENT_TIMESTAMP format."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _no_prices(sel: Selection) -> str:
    return f"Auctionator has no prices for {sel.realm} ({sel.faction}). Scan that auction house in game."


# --- game data -------------------------------------------------------------------------------------
def update_game_data(
    conn: sqlite3.Connection,
    cache_dir: Path,
    disenchant_csv: Path,
    vendor_csv: Path,
    *,
    only_if_new: bool = False,
) -> tuple[str, bool, dict[str, int]]:
    """Download the newest build's DB2 tables and rebuild items/recipes (prices are kept).

    With `only_if_new`, skip the rebuild when the database already holds the newest build. The manual
    update always rebuilds, since data/disenchant.csv or data/vendor_items.csv may have changed.
    Returns (build, whether it rebuilt, row counts).
    """
    build = ingest.latest_build()
    if only_if_new and db.get_meta(conn, "build") == build:
        return build, False, current_counts(conn)
    return build, True, ingest.update(conn, build, cache_dir, disenchant_csv, vendor_csv)


def current_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """The same counts `ingest.update` reports, read from the database as it stands."""
    return {
        "items": db.count_rows(conn, "items"),
        "recipes": db.count_rows(conn, "recipes"),
        "disenchant_rows": db.count_rows(conn, "disenchant"),
        "vendor_items": db.count_rows(conn, "vendor_items"),
    }
