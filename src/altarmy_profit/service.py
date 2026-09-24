"""Use-cases behind the web API: the shared market cache, search, addon sync and the Manage actions.

No HTTP here. User state is per `user_uid` (local mode: `auth.LOCAL_USER`). Characters come from the Alt
Army addon and prices from Auctionator; in local mode `sync` re-reads either SavedVariables file whenever
the game has rewritten it (on logout or /reload).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Connection

from . import altarmy, auctionator, db, ingest, prices, store, users
from .altarmy import Character
from .engine import (
    AH_CUT,
    ALL_EXITS,
    MAIL_POSTAGE,
    Choices,
    Crafter,
    Filters,
    Market,
    Result,
    recipes_for_characters,
)
from .versions import GameVersion


class MarketCache:
    """In-process Markets for one game version, one per auction house, shared by all requests; rebuilt
    from the database lazily after invalidate().

    Market is read-only once built, so handing the same instance to several threads is safe.
    """

    def __init__(
        self,
        database: db.Database,
        game_version: str,
        *,
        ah_cut: float = AH_CUT,
        mail_postage: int = MAIL_POSTAGE,
    ) -> None:
        self.database = database
        self.game_version = game_version
        self.ah_cut = ah_cut
        self.mail_postage = mail_postage
        self._lock = threading.Lock()
        self._markets: dict[int | None, Market] = {}

    def get(self, auction_house_id: int | None) -> Market:
        """The version's game data priced by the auction house (None: unpriced)."""
        with self._lock:
            market = self._markets.get(auction_house_id)
            if market is None:
                with self.database.begin() as conn:
                    market = store.load_market(
                        conn,
                        self.game_version,
                        auction_house_id,
                        ah_cut=self.ah_cut,
                        mail_postage=self.mail_postage,
                    )
                self._markets[auction_house_id] = market
            return market

    def invalidate(self, auction_house_ids: Iterable[int] | None = None) -> None:
        """Drop the cached markets of these auction houses (default: all)."""
        with self._lock:
            if auction_house_ids is None:
                self._markets.clear()
            for ah in auction_house_ids or ():
                self._markets.pop(ah, None)


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
        base.ah_cut,
        crafters=crafters,
        include_unlearned=include_unlearned,
        exits=exits,
        no_ah=no_ah,
        include_trivial=include_trivial,
        mail_postage=base.mail_postage,
    )


# --- realm/faction selection -----------------------------------------------------------------------
def selection(
    conn: Connection, user_uid: str, game_version: str, chars: Sequence[Character]
) -> Selection | None:
    """The saved realm/faction if it still has characters, else the group with the most characters."""
    groups = altarmy.groups(chars)
    saved = users.get_settings(conn, user_uid, game_version)
    for g in groups:
        if (g.realm, g.faction) == (saved.selected_realm, saved.selected_faction):
            return Selection(g.realm, g.faction)
    if not groups:
        return None
    best = max(groups, key=lambda g: len(g.characters))
    return Selection(best.realm, best.faction)


def select(conn: Connection, user_uid: str, game_version: str, realm: str, faction: str) -> None:
    groups = altarmy.groups(store.load_characters(conn, user_uid, game_version))
    if not any((g.realm, g.faction) == (realm, faction) for g in groups):
        raise ValueError(f"no characters on {realm} ({faction})")
    users.update_settings(conn, user_uid, game_version, selected_realm=realm, selected_faction=faction)


def selected_characters(
    conn: Connection, user_uid: str, game_version: str
) -> tuple[Selection | None, list[Character]]:
    chars = store.load_characters(conn, user_uid, game_version)
    sel = selection(conn, user_uid, game_version, chars)
    if sel is None:
        return None, []
    return sel, [c for c in chars if (c.realm, c.faction) == (sel.realm, sel.faction)]


def auction_house_of(conn: Connection, game_version: str, sel: Selection | None) -> int | None:
    """The auction house that prices a selection (the unnamed one without characters); None if unknown.
    One named after an Auctionator key (its scan came before the characters) is found by that alias."""
    if sel is None:
        return prices.find_auction_house(conn, game_version, "", "")
    found = prices.find_auction_house(conn, game_version, sel.realm, sel.faction)
    if found is None:
        found = prices.find_auction_house_by_alias(conn, game_version, sel.realm, sel.faction)
    return found


def selected_auction_house(conn: Connection, user_uid: str, game_version: str) -> int | None:
    sel, _ = selected_characters(conn, user_uid, game_version)
    return auction_house_of(conn, game_version, sel)


def pricing_auction_house(conn: Connection, user_uid: str, game_version: str) -> int:
    """Where manual and CSV prices go: the selection's auction house, or the unnamed one without
    characters. ValueError if the selected realm has no auction house yet."""
    sel, _ = selected_characters(conn, user_uid, game_version)
    if sel is None:
        return prices.unnamed_auction_house(conn, game_version)
    ah = auction_house_of(conn, game_version, sel)
    if ah is None:
        raise ValueError(
            f"No auction house known for {sel.realm} ({sel.faction}) yet: import its Auctionator scan first."
        )
    return ah


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
    """The last used file (even a pasted one), else the first one found."""
    return last or (files[0] if files else None)


def data_version(conn: Connection, user_uid: str, game_version: str) -> int:
    """Bumped whenever the user's characters or prices were re-imported, so the front end refetches."""
    return users.get_settings(conn, user_uid, game_version).data_version


def bump_data_version(conn: Connection, user_uid: str, game_version: str) -> None:
    users.update_settings(
        conn, user_uid, game_version, data_version=data_version(conn, user_uid, game_version) + 1
    )


def set_sources(
    conn: Connection,
    user_uid: str,
    game_version: str,
    altarmy_path: str | None,
    auctionator_path: str | None,
) -> None:
    """Point the sync at other SavedVariables files; None keeps that source as it is."""
    changes = {}
    for key, path in (("altarmy_path", altarmy_path), ("auctionator_path", auctionator_path)):
        if path is None:
            continue
        if not Path(path).is_file():
            raise FileNotFoundError(f"File not found: {path}")
        changes[key] = path
    users.update_sync(conn, user_uid, game_version, **changes)


def sync(
    conn: Connection,
    user_uid: str,
    game_version: str,
    roots: Iterable[Path] = prices.WOW_ROOTS,
    *,
    force: bool = False,
    flavors: Sequence[str] | None = None,
) -> SyncResult:
    """Local mode: re-import the user's Alt Army characters and the selected realm's Auctionator prices if
    either file changed.

    Unset paths are filled in from the files found under the WoW installs in `roots`, looking only in the
    game version's `flavors` folders (e.g. ("_anniversary_",)) when given.
    """
    found = _Finder(user_uid, game_version, list(roots), flavors)
    warnings: list[str] = []
    changed = _sync_altarmy(conn, found, force, warnings)
    changed = _sync_auctionator(conn, found, force, warnings) or changed
    if changed:
        bump_data_version(conn, user_uid, game_version)
    return SyncResult(changed, warnings)


Finder = Callable[[Iterable[Path], Sequence[str] | None], list[Path]]  # prices.find_*_files


@dataclass(frozen=True)
class _Finder:
    """Whose sync, which version's addon files, and where to look for them: WoW installs and, optionally,
    only some flavor folders."""

    user_uid: str
    game_version: str
    roots: list[Path]
    flavors: Sequence[str] | None

    def __call__(self, find: Finder) -> list[Path]:
        return find(self.roots, self.flavors)

    def state(self, conn: Connection) -> users.LocalSync:
        return users.get_sync(conn, self.user_uid, self.game_version)

    def update(self, conn: Connection, **changes: Any) -> None:
        users.update_sync(conn, self.user_uid, self.game_version, **changes)


def _source(conn: Connection, key: str, find: Finder, found: _Finder) -> Path | None:
    path: str | None = getattr(found.state(conn), key)
    if path is None:
        path = default_path([str(f) for f in found(find)], None)
        if path is None:
            return None
        found.update(conn, **{key: path})
    return Path(path)


def _changed_mtime(path: Path, last: int | None, force: bool) -> int | None:
    """The file's mtime (ns) if it differs from `last` (or `force`), else None."""
    mtime = path.stat().st_mtime_ns
    return mtime if force or mtime != last else None


def _sync_altarmy(conn: Connection, found: _Finder, force: bool, warnings: list[str]) -> bool:
    path = _source(conn, "altarmy_path", prices.find_altarmy_files, found)
    if path is None:
        warnings.append("No Alt Army file found. Pick AltArmy_TBC.lua on the Manage tab.")
        return False
    if not path.is_file():
        warnings.append(f"Alt Army file not found: {path}")
        return False
    mtime = _changed_mtime(path, found.state(conn).altarmy_mtime, force)
    if mtime is None:
        return False
    try:
        chars = altarmy.parse_characters(path.read_bytes())
    except ValueError as e:
        warnings.append(f"Could not read {path}: {e}")
        return False
    store.save_characters(conn, found.user_uid, found.game_version, chars)
    found.update(conn, altarmy_mtime=mtime, altarmy_synced=db.utcnow())
    return True


def _sync_auctionator(conn: Connection, found: _Finder, force: bool, warnings: list[str]) -> bool:
    """Record the selected realm's scan when the file (or the selection) changed. Each auction house
    keeps its own prices, so a file without the realm leaves the prices alone and only warns."""
    uid, gv = found.user_uid, found.game_version
    sel = selection(conn, uid, gv, store.load_characters(conn, uid, gv))
    if sel is None:
        return False  # no characters yet, so no realm to price
    path = _source(conn, "auctionator_path", prices.find_auctionator_files, found)
    if path is None:
        warnings.append("No Auctionator file found. Pick Auctionator.lua on the Manage tab.")
        return False
    if not path.is_file():
        warnings.append(f"Auctionator file not found: {path}")
        return False
    state = found.state(conn)
    wanted = f"{sel.realm}\t{sel.faction}"
    moved = wanted != state.auctionator_for
    mtime = _changed_mtime(path, state.auctionator_mtime, force or moved)
    if mtime is None:
        if not state.auctionator_realm:
            warnings.append(_no_prices(sel))
        return False
    try:
        realms = auctionator.parse_price_database(path.read_bytes())
    except ValueError as e:
        warnings.append(f"Could not read {path}: {e}")
        return False
    key = match_auctionator_realm(realms, sel.realm, sel.faction)
    if key is None:
        warnings.append(_no_prices(sel))
    else:
        ah = prices.auctionator_auction_house(conn, gv, key, sel.realm, sel.faction)
        prices.record_auctionator(conn, ah, realms[key], prices.file_time(path), uploader_uid=uid)
        prices.prune(conn)
    found.update(
        conn,
        auctionator_realm=key or "",
        auctionator_for=wanted,
        auctionator_mtime=mtime,
        auctionator_synced=db.utcnow(),
    )
    return True


def _no_prices(sel: Selection) -> str:
    return f"Auctionator has no prices for {sel.realm} ({sel.faction}). Scan that auction house in game."


# --- game data -------------------------------------------------------------------------------------
def update_game_data(
    conn: Connection,
    version: GameVersion,
    cache_dir: Path,
    *,
    only_if_new: bool = False,
) -> tuple[str, bool, dict[str, int]]:
    """Download the version's newest build's DB2 tables and rebuild items/recipes (prices are kept).

    With `only_if_new`, skip the rebuild when the database already holds the newest build. The manual
    update always rebuilds, since the version's disenchant.csv or vendor_items.csv may have changed.
    Returns (build, whether it rebuilt, row counts).
    """
    build = ingest.latest_build(version.wago_product)
    if only_if_new and db.get_build(conn, version.key) == build:
        return build, False, current_counts(conn, version.key)
    stats = ingest.update(conn, version.key, build, cache_dir, version.disenchant_csv, version.vendor_csv)
    return build, True, stats


def current_counts(conn: Connection, game_version: str) -> dict[str, int]:
    """The same counts `ingest.update` reports, read from the database as it stands."""
    return {
        "items": db.count_rows(conn, "items", game_version),
        "recipes": db.count_rows(conn, "recipes", game_version),
        "disenchant_rows": db.count_rows(conn, "disenchant", game_version),
        "vendor_items": db.count_rows(conn, "vendor_items", game_version),
    }
