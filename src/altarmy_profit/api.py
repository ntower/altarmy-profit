"""FastAPI JSON API for the React front end, which it also serves once built (frontend/dist).

Money is integer copper on the wire; the front end formats it. Handlers are plain `def` so FastAPI runs
them in its threadpool: the game data download blocks for a while and must not stall other requests.
Each handler opens its own connection from the shared `db.Database` (never shared across threads).

Every route but /api/config and /api/versions has a user (`CurrentUser`). Local mode (`ALTARMY_MODE=local`,
the default) always has `auth.LOCAL_USER`; hosted mode verifies the Firebase ID token sent as a bearer
token. Rankings, characters and AH blocks need the linked tier (`LinkedUser`, else 403); the free tier sees
prices only for items up to `auth.FREE_TIER_MAX_LEVEL`. The addon file sync, source files and game data
update exist only in local mode (`LOCAL_ONLY`, else 404); account deletion only in hosted mode
(`HOSTED_ONLY`). Uploads also take an API key (`Uploader`), the CLI watcher's credential; no other route
does, so a leaked key can only upload. Hosted mode rate-limits every request per client IP and per user
(`ratelimit`), and no /api response may be cached (Firebase Hosting's CDN sits in front).
"""

from __future__ import annotations

import threading
import urllib.error
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from . import altarmy, auth, db, engine, prices, ratelimit, service, store, uploads, users, versions
from .store import CACHE_DIR
from .versions import GameVersion, GameVersionKey

DEFAULT_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

ExitKind = Literal["vendor", "ah", "disenchant"]
ALL_EXIT_KINDS: tuple[ExitKind, ...] = ("vendor", "ah", "disenchant")


# --- models ----------------------------------------------------------------------------------------
class SelectionModel(BaseModel):
    """A realm and faction: whose recipes count and which auction house prices them."""

    realm: str
    faction: str


class Status(BaseModel):
    db_path: str  # the SQLite file, or the database URL without its password; "" in hosted mode
    build: str | None
    items: int
    recipes: int
    prices: int  # current prices of the selection's auction house
    characters: int
    last_auctionator_import: str | None  # "YYYY-MM-DD HH:MM:SS", UTC
    last_altarmy_sync: str | None  # same format
    last_auctionator_sync: str | None  # same format; set even when the scan had no prices for the realm
    altarmy_path: str | None
    auctionator_path: str | None
    auctionator_realm: str | None  # Auctionator's key for the selection; "" if it has none
    selection: SelectionModel | None
    auction_house_id: int | None  # the selection's auction house (the unnamed one without characters)
    data_version: int  # bumped whenever a sync re-imported something: refetch characters and results
    price_version: (
        int | None
    )  # the auction house's, bumped by each merge that moved its statistics: refetch results
    warnings: list[str]  # addon files missing, unreadable, or without prices for the selection


class MaterialOut(BaseModel):
    """One possible disenchant result."""

    item_id: int
    name: str
    chance: float  # 0..1
    min_count: int
    max_count: int
    value: int | None  # expected net AH copper per disenchant; None if unpriced


class ExitOut(BaseModel):
    kind: str  # vendor | ah | disenchant
    value: int  # copper per item, after cuts
    materials: list[MaterialOut]  # disenchant only: what it yields
    postage: int  # copper per item to mail it to the character who can use this exit
    mail_to: str  # that character; "" if the crafter can use it themselves


class StepOut(BaseModel):
    action: Literal["buy", "craft", "mail", "sell"]
    item_id: int
    name: str
    quantity: int
    value: int  # copper for the whole step: negative when buying or mailing, positive when selling
    via: str  # buy: vendor | ah; craft: recipe name; mail: recipient; sell: vendor | ah | disenchant
    who: str  # the character doing it; "" if no characters are known


class OptionOut(BaseModel):
    """One way to get a node's items; POST it back as a choice by `key`."""

    key: str  # vendor | ah | craft:<recipe id>
    cost: int  # copper for the node's quantity this way, with postage
    source: str  # vendor | ah if bought
    via: str  # recipe name if crafted
    crafter: str  # who crafts it (the cheapest character for that recipe)


class SellOptionOut(BaseModel):
    kind: str  # vendor | ah | disenchant
    profit: int  # the best profit selling this way


class NodeOut(BaseModel):
    """One item in a craft's reagent tree: bought (no inputs) or crafted from its inputs, possibly by
    another character who then mails it on."""

    item_id: int
    name: str
    quantity: int  # units this branch needs
    cost: int  # copper spent on them, including postage
    via: str  # recipe name if crafted, "" if bought
    crafts: int  # recipe runs if crafted
    made: int  # units those crafts produce (may exceed quantity)
    source: str  # vendor | ah if bought, "" if crafted
    crafter: str  # who buys or crafts it
    mail_to: str  # who it is mailed to (the parent's crafter); "" if not mailed
    postage: int  # copper for that mail
    options: list[OptionOut]  # every way to get these items, cheapest first; empty for the recipe's craft
    option: str  # the key of the option taken; "" for the recipe's craft
    inputs: list[NodeOut]


def _node_out(n: engine.Node) -> NodeOut:
    return NodeOut(
        item_id=n.item_id,
        name=n.name,
        quantity=n.quantity,
        cost=n.cost,
        via=n.via,
        crafts=n.crafts,
        made=n.made,
        source=n.source,
        crafter=n.crafter,
        mail_to=n.mail_to,
        postage=n.postage,
        options=[OptionOut(**asdict(o)) for o in n.options],
        option=n.option,
        inputs=[_node_out(i) for i in n.inputs],
    )


class ItemCount(BaseModel):
    item_id: int
    count: int


class ItemInfo(BaseModel):
    """Everything an item tooltip shows."""

    id: int
    name: str
    quality: int  # 0 poor .. 5 legendary
    class_id: int  # 2 weapon, 4 armor, ...
    subclass_name: str | None
    inventory_type: int  # equip slot, 0 if not equippable
    bonding: int  # 1 on pickup, 2 on equip, 3 on use, 4 quest item
    item_delay: int  # weapon speed, ms
    container_slots: int
    required_level: int
    required_skill: str | None
    required_skill_rank: int
    description: str | None
    sell_price: int
    icon: str | None  # wow.zamimg.com icon name
    ah_price: int | None  # the current minimum buyout: what buying it costs
    # what selling it on the AH counts as: the lower of ah_price and the 7-day median (hand-set prices as
    # they are), so a lone overpriced listing isn't taken for the going rate
    ah_sell_price: int | None
    vendor_price: int | None  # per unit, if a vendor sells it


class RankResult(BaseModel):
    recipe_id: int
    recipe: str
    profession: str
    crafters: list[str]  # selected characters who know the recipe; empty if nobody has learned it
    crafter: str  # who does the cheapest craft (may not have learned it, with include_unlearned)
    output_item_id: int
    output_name: str
    output_count: int
    cost: int  # reagents plus all postage
    revenue: int
    profit: int
    roi: float
    best_exit: str
    postage: int  # copper to mail the output to whoever sells it (included in cost)
    mail_to: str  # who the output is mailed to; "" if the crafter sells it
    exits: list[ExitOut]
    reagents: list[ItemCount]
    steps: list[StepOut]  # buy reagents, craft (intermediates first), mail, sell
    tree: NodeOut  # the recipe's craft, with reagents as inputs
    sell_options: list[SellOptionOut]  # each exit's best profit, best first


class RankResponse(BaseModel):
    results: list[RankResult]  # the first `top` matches
    total: int  # how many recipes matched the filters
    items: dict[int, ItemInfo]  # every item the results mention, for tooltips
    classes: dict[str, str]  # selected character name -> class file (e.g. PALADIN), for class colours


class EvaluateRequest(BaseModel):
    """Re-cost one recipe with some of its sources or its exit picked by the user."""

    recipe_id: int
    include_unlearned: bool = False
    include_trivial: bool = True  # False: only a crafter it can give a skillup does the final craft
    exits: list[ExitKind] = list(ALL_EXIT_KINDS)
    # tree path ("r.0", "r.0.1"; "sell" for the exit) -> option key (or exit kind); unknown keys are ignored
    choices: dict[str, str]


class EvaluateResponse(BaseModel):
    result: RankResult
    items: dict[int, ItemInfo]  # every item the result mentions, for tooltips


class AhBlockedItem(BaseModel):
    item_id: int
    added_at: str  # "YYYY-MM-DD HH:MM:SS", UTC


class AhBlocked(BaseModel):
    """Items never sold on the AH: only vendored or disenchanted."""

    items: list[AhBlockedItem]  # newest first
    details: dict[int, ItemInfo]  # for tooltips


class UpdateResult(BaseModel):
    build: str
    updated: bool  # False if only_if_new and the database already held this build
    items: int
    recipes: int
    disenchant_rows: int
    vendor_items: int


class SourceFiles(BaseModel):
    files: list[str]  # found under the usual WoW install folders
    default: str | None  # the file in use, else the best guess


class Sources(BaseModel):
    """SavedVariables files to sync from; a missing field keeps that source."""

    altarmy_path: str | None = None
    auctionator_path: str | None = None


class ProfessionOut(BaseModel):
    name: str
    rank: int
    max_rank: int
    recipes: int  # learned recipes


class CharacterOut(BaseModel):
    name: str
    class_file: str  # e.g. PALADIN
    level: int
    professions: list[ProfessionOut]


class GroupOut(BaseModel):
    realm: str
    faction: str
    characters: list[CharacterOut]


class Characters(BaseModel):
    groups: list[GroupOut]  # by realm, then faction
    selection: SelectionModel | None


class VersionOut(BaseModel):
    """A game version the app serves; pass its `key` as `game_version` to the other routes."""

    key: GameVersionKey
    label: str  # e.g. TBC Anniversary
    build: str | None  # the DB2 build loaded, None before the first game data download
    recipes: int


class FirebaseOut(BaseModel):
    """The Firebase web config the front end signs in with (public values)."""

    api_key: str
    auth_domain: str
    project_id: str
    emulator_url: str | None  # the Firebase Auth emulator, when developing


class ConfigOut(BaseModel):
    mode: auth.Mode  # local: no sign-in, one user; hosted: Firebase sign-in
    firebase: FirebaseOut | None  # hosted mode only


class Me(BaseModel):
    uid: str
    tier: auth.Tier  # free: prices up to free_max_level only; linked: everything
    free_max_level: int  # the free tier's highest required level


class AuctionHouseOut(BaseModel):
    id: int
    realm: str  # "" for the unnamed auction house (prices set by hand or CSV)
    faction: str  # "" if both factions share it
    prices: int  # items with a current price
    last_scan: str | None  # newest price seen, "YYYY-MM-DD HH:MM:SS" UTC


class PriceStatsOut(BaseModel):
    """An item's pooled statistics over the last 7 days (filled hourly; None until then or without data)."""

    median_7d: int | None  # median of the daily medians, copper
    avail_7d: int | None  # median of the most seen up at once per day
    scans_7d: int | None  # days with a scan of it


class PricesOut(BaseModel):
    items: list[ItemInfo]  # by name; `ah_price` is the auction house's current price
    stats: dict[int, PriceStatsOut]  # per listed item
    total: int  # how many items matched
    gated: bool  # True if items above the free tier's level were left out


class CoverageOut(BaseModel):
    """How well one auction house is scanned, so uploaders see where scans are needed."""

    auction_house_id: int
    realm: str
    faction: str  # "" if both factions share it
    prices: int  # items with a current price
    last_scan: str | None  # the newest accepted scan, "YYYY-MM-DD HH:MM:SS" UTC
    last_scan_items: int  # items in that scan
    scans_7d: int  # accepted scans in the last 7 days
    uploaders_7d: int  # how many users sent them


class DayOut(BaseModel):
    day: str  # YYYY-MM-DD
    low: int  # copper
    high: int
    available: int | None


class PriceHistoryOut(BaseModel):
    item: ItemInfo
    stats: PriceStatsOut | None  # None if the item has no current price
    days: list[DayOut]  # newest first


UploadKind = Literal["altarmy", "auctionator"]
UploadVia = Literal["browser", "watcher"]


class GroupCount(BaseModel):
    realm: str
    faction: str
    characters: int


class RealmPricesOut(BaseModel):
    key: str  # Auctionator's realm key
    auction_house_id: int
    realm: str
    faction: str
    items: int  # items priced in the scan
    moved: int  # of them, items whose current price changed
    quarantined: bool  # far off this auction house's recent prices, so not used


class UploadResult(BaseModel):
    kind: UploadKind
    detail: str  # a one-line summary
    characters: int  # altarmy: characters imported
    groups: list[GroupCount]  # altarmy: by realm and faction
    realms: list[RealmPricesOut]  # auctionator: every realm with prices


class UploadOut(BaseModel):
    id: int
    game_version: str
    kind: UploadKind
    via: UploadVia
    size: int  # bytes, decompressed
    received_at: str  # "YYYY-MM-DD HH:MM:SS" UTC
    outcome: Literal["accepted", "rejected"]
    detail: str


class KeyRequest(BaseModel):
    label: str = Field(min_length=1, max_length=64)  # e.g. the computer it runs on


class ApiKeyOut(BaseModel):
    id: int
    prefix: str  # the key's first characters
    label: str
    created_at: str  # "YYYY-MM-DD HH:MM:SS" UTC
    last_used_at: str | None


class NewApiKey(ApiKeyOut):
    key: str  # shown only now: only its hash is stored


# --- app state and helpers -------------------------------------------------------------------------
@dataclass
class AppState:
    """One game version's cached markets and locks, plus what every version shares."""

    version: GameVersion
    database: db.Database  # shared by every version
    cache_dir: Path
    cache: service.MarketCache
    rank_cache: service.RankCache
    update_lock: threading.Lock
    sync_lock: threading.Lock
    wow_roots: Sequence[Path]  # where to look for the addons' SavedVariables

    @property
    def key(self) -> str:
        return self.version.key


def _states(request: Request) -> dict[str, AppState]:
    states: dict[str, AppState] = request.app.state.wow
    return states


def _state(
    request: Request,
    game_version: Annotated[GameVersionKey, Query(description="which game's data: tbc or forever")],
) -> AppState:
    return _states(request)[game_version]


State = Annotated[AppState, Depends(_state)]


@dataclass(frozen=True)
class AuthState:
    mode: auth.Mode
    database: db.Database
    verifier: auth.TokenVerifier | None  # hosted mode
    firebase: auth.FirebaseConfig | None  # hosted mode
    accounts: auth.AccountAdmin | None = None  # hosted mode: deletes sign-in accounts
    per_ip: ratelimit.RateLimiter | None = None  # hosted mode
    per_uid: ratelimit.RateLimiter | None = None  # hosted mode


def _too_many(retry: float) -> HTTPException:
    return HTTPException(
        429, "Too many requests: slow down.", headers={"Retry-After": str(max(1, round(retry)))}
    )


def _limit_user(a: AuthState, user: auth.User) -> auth.User:
    retry = a.per_uid.hit(user.uid) if a.per_uid is not None else None
    if retry is not None:
        raise _too_many(retry)
    return user


def _auth(request: Request) -> AuthState:
    state: AuthState = request.app.state.auth
    return state


_bearer = HTTPBearer(auto_error=False, description="Firebase ID token (hosted mode only)")


def _current_user(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> auth.User:
    """The local user in local mode; in hosted mode, whoever the bearer token says (401 without one)."""
    a = _auth(request)
    if a.mode == "local":
        return auth.LOCAL_USER
    if credentials is None or a.verifier is None:
        raise HTTPException(401, "Sign in first.", headers={"WWW-Authenticate": "Bearer"})
    try:
        user = auth.user_from_claims(a.verifier.verify(credentials.credentials))
    except auth.InvalidToken as e:
        raise HTTPException(401, f"Invalid sign-in token: {e}", headers={"WWW-Authenticate": "Bearer"}) from e
    _limit_user(a, user)
    with a.database.begin() as conn:
        users.ensure_user(conn, user)
    return user


CurrentUser = Annotated[auth.User, Depends(_current_user)]


def _uploader(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> auth.User:
    """Like CurrentUser, but an API key (the CLI watcher's) also signs in, as its owner. Local mode, as
    everywhere, is the local user whatever is sent."""
    a = _auth(request)
    token = credentials.credentials if credentials is not None else ""
    if a.mode == "local" or not token.startswith(users.KEY_PREFIX):
        return _current_user(request, credentials)
    with a.database.begin() as conn:
        user = users.user_for_key(conn, token)
    if user is None:
        raise HTTPException(401, "Unknown or revoked API key.", headers={"WWW-Authenticate": "Bearer"})
    return _limit_user(a, user)


Uploader = Annotated[auth.User, Depends(_uploader)]


def _linked_user(user: CurrentUser) -> auth.User:
    if not user.linked:
        raise HTTPException(403, "Link your account to see rankings, characters and AH blocks.")
    return user


LinkedUser = Annotated[auth.User, Depends(_linked_user)]


def _local_only(request: Request) -> None:
    if _auth(request).mode != "local":
        raise HTTPException(404, "Not available in hosted mode.")


LOCAL_ONLY = [Depends(_local_only)]  # route dependencies of the local file sync and admin actions


def _hosted_only(request: Request) -> None:
    if _auth(request).mode != "hosted":
        raise HTTPException(404, "Only in hosted mode.")


HOSTED_ONLY = [Depends(_hosted_only)]  # route dependencies of account management


def _max_level(user: auth.User) -> int | None:
    """The highest required level whose prices the user may see; None: any."""
    return None if user.linked else auth.FREE_TIER_MAX_LEVEL


@contextmanager
def _connect(state: AppState) -> Iterator[Connection]:
    """A connection in a transaction, committed when the block succeeds."""
    with state.database.begin() as conn:
        yield conn


@contextmanager
def _http_errors() -> Iterator[None]:
    """Map domain errors to HTTP. Order matters: URLError and FileNotFoundError are OSErrors."""
    try:
        yield
    except urllib.error.URLError as e:
        raise HTTPException(502, f"Download failed: {e.reason}") from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except OSError as e:
        raise HTTPException(500, str(e)) from e


def _sync(state: AppState, conn: Connection, user: auth.User, force: bool = False) -> list[str]:
    """Re-import whichever addon file the game rewrote; returns the sync's warnings."""
    with state.sync_lock:
        result = service.sync(
            conn, user.uid, state.key, state.wow_roots, force=force, flavors=state.version.flavor_folders
        )
    if result.changed:
        state.cache.invalidate()
    return result.warnings


def _selection_model(sel: service.Selection | None) -> SelectionModel | None:
    return None if sel is None else SelectionModel(realm=sel.realm, faction=sel.faction)


def _status(
    state: AppState, conn: Connection, user: auth.User, hosted: bool, warnings: list[str] | None = None
) -> Status:
    gv, uid = state.key, user.uid
    sel, _ = service.selected_characters(conn, uid, gv)
    ah = service.auction_house_of(conn, gv, sel)
    sync = users.get_sync(conn, uid, gv)
    return Status(
        db_path="" if hosted else state.database.display_url,
        build=db.get_build(conn, gv),
        items=db.count_rows(conn, "items", gv),
        recipes=db.count_rows(conn, "recipes", gv),
        prices=prices.count_current(conn, ah),
        characters=store.count_characters(conn, uid, gv),
        last_auctionator_import=prices.last_import(conn, ah),
        last_altarmy_sync=db.timestamp_text(sync.altarmy_synced),
        last_auctionator_sync=db.timestamp_text(sync.auctionator_synced),
        altarmy_path=sync.altarmy_path,
        auctionator_path=sync.auctionator_path,
        auctionator_realm=sync.auctionator_realm,
        selection=_selection_model(sel),
        auction_house_id=ah,
        data_version=service.data_version(conn, uid, gv),
        price_version=prices.price_version(conn, ah),
        warnings=warnings or [],
    )


def _vendor_price(market: engine.Market, item_id: int) -> int | None:
    item = market.items.get(item_id)  # the cached market may predate the database
    return None if item is None else item.vendor_price


# --- routes ----------------------------------------------------------------------------------------
router = APIRouter(prefix="/api")


@router.get("/status")
def get_status(state: State, user: CurrentUser, request: Request) -> Status:
    """In local mode also the addon file watcher: re-imports Alt Army and Auctionator data the game has
    rewritten. Hosted mode never reads local files."""
    hosted = _auth(request).mode == "hosted"
    with _connect(state) as conn:
        warnings = [] if hosted else _sync(state, conn, user)
        return _status(state, conn, user, hosted, warnings)


@router.post("/sync", dependencies=LOCAL_ONLY)
def sync_now(state: State, user: CurrentUser) -> Status:
    """Re-import both addon files even if they look unchanged."""
    with _connect(state) as conn:
        return _status(state, conn, user, False, _sync(state, conn, user, force=True))


@router.get("/characters")
def get_characters(state: State, user: LinkedUser) -> Characters:
    with _connect(state) as conn:
        chars = store.load_characters(conn, user.uid, state.key)
        sel = service.selection(conn, user.uid, state.key, chars)
    return Characters(
        groups=[
            GroupOut(
                realm=g.realm,
                faction=g.faction,
                characters=[
                    CharacterOut(
                        name=c.name,
                        class_file=c.class_file,
                        level=c.level,
                        professions=[
                            ProfessionOut(
                                name=p.name, rank=p.rank, max_rank=p.max_rank, recipes=len(p.recipe_ids)
                            )
                            for p in c.professions
                        ],
                    )
                    for c in g.characters
                ],
            )
            for g in altarmy.groups(chars)
        ],
        selection=_selection_model(sel),
    )


@router.put("/selection")
def put_selection(state: State, user: LinkedUser, body: SelectionModel, request: Request) -> Status:
    """Switch realm/faction; in local mode that realm's Auctionator prices are synced too."""
    hosted = _auth(request).mode == "hosted"
    with _http_errors(), _connect(state) as conn:
        service.select(conn, user.uid, state.key, body.realm, body.faction)
        return _status(state, conn, user, hosted, [] if hosted else _sync(state, conn, user))


@router.put("/sources", dependencies=LOCAL_ONLY)
def put_sources(state: State, user: CurrentUser, body: Sources) -> Status:
    with _http_errors(), _connect(state) as conn:
        service.set_sources(conn, user.uid, state.key, body.altarmy_path, body.auctionator_path)
        return _status(state, conn, user, False, _sync(state, conn, user, force=True))


@router.get("/rank")
def get_rank(
    state: State,
    user: LinkedUser,
    include_unlearned: Annotated[
        bool, Query(description="rank every recipe of the characters' professions, not just learned ones")
    ] = False,
    include_trivial: Annotated[
        bool, Query(description="also recipes that can't give the crafter a skillup (grey or at the cap)")
    ] = True,
    exits: Annotated[Sequence[ExitKind], Query(description="ways the crafts may be sold")] = ALL_EXIT_KINDS,
    min_cost: Annotated[int | None, Query(description="copper")] = None,
    max_cost: Annotated[int | None, Query(description="copper")] = None,
    min_profit: Annotated[int | None, Query(description="copper")] = None,
    max_profit: Annotated[int | None, Query(description="copper")] = None,
    min_roi: Annotated[float | None, Query(description="profit / cost (0.5 = 50%)")] = None,
    max_roi: Annotated[float | None, Query(description="profit / cost (0.5 = 50%)")] = None,
    top: Annotated[int, Query(ge=1)] = 50,
) -> RankResponse:
    """What the selected realm/faction's characters can craft, most profitable first. Bounds are
    inclusive; an omitted bound is unbounded (so losses are included unless `min_profit` is set)."""
    base, chars, no_ah = _selected(state, user)
    filters = engine.Filters(min_cost, max_cost, min_profit, max_profit, min_roi, max_roi)
    key = (user.uid, tuple(chars), include_unlearned, include_trivial, frozenset(exits), filters, no_ah)
    matches = state.rank_cache.get(key, base)
    if matches is None:
        matches = service.search(
            base, chars, include_unlearned, filters, frozenset(exits), no_ah, include_trivial
        )
        state.rank_cache.put(key, base, matches)
    results = matches[:top]
    crafters = altarmy.crafters(chars)
    return RankResponse(
        total=len(matches),
        classes={c.name: c.class_file for c in chars},
        items=_item_infos(state, base, results),
        results=[_result_out(r, base, crafters) for r in results],
    )


@router.post("/evaluate")
def evaluate(state: State, user: LinkedUser, body: EvaluateRequest) -> EvaluateResponse:
    """One recipe as /api/rank would give it, with the user's `choices` of sources and exit applied."""
    base, chars, no_ah = _selected(state, user)
    r = service.evaluate(
        base,
        chars,
        body.include_unlearned,
        frozenset(body.exits),
        body.recipe_id,
        body.choices,
        no_ah,
        body.include_trivial,
    )
    if r is None:
        raise HTTPException(404, "These characters can't craft and sell that recipe.")
    return EvaluateResponse(
        result=_result_out(r, base, altarmy.crafters(chars)), items=_item_infos(state, base, [r])
    )


def _selected(
    state: AppState, user: auth.User
) -> tuple[engine.Market, list[altarmy.Character], frozenset[int]]:
    """The selection's market (priced by its auction house), characters and never-on-the-AH items."""
    with _connect(state) as conn:
        sel, chars = service.selected_characters(conn, user.uid, state.key)
        ah = service.auction_house_of(conn, state.key, sel)
        no_ah = _no_ah(state, conn, user)
    return state.cache.get(ah), chars, no_ah


def _item_infos(
    state: AppState, base: engine.Market, results: Sequence[engine.Result]
) -> dict[int, ItemInfo]:
    """Tooltip details for every item the results mention."""
    item_ids = (
        {s.item_id for r in results for s in r.steps}
        | {i for r in results for i, _ in r.recipe.reagents}
        | {m.item_id for r in results for e in r.exits for m in e.materials}
    )
    with _connect(state) as conn:
        return _item_details(state, conn, base, item_ids)


def _item_details(
    state: AppState, conn: Connection, base: engine.Market, item_ids: Iterable[int]
) -> dict[int, ItemInfo]:
    details = store.load_item_details(conn, state.key, item_ids)
    return {
        i: ItemInfo(
            **asdict(d),
            ah_price=base.prices.get(i),
            ah_sell_price=base.sell_prices.get(i),
            vendor_price=_vendor_price(base, i),
        )
        for i, d in details.items()
    }


def _result_out(r: engine.Result, base: engine.Market, crafters: dict[int, list[str]]) -> RankResult:
    return RankResult(
        recipe_id=r.recipe.id,
        recipe=r.recipe.name,
        profession=r.recipe.skill_name,
        crafters=crafters.get(r.recipe.spell_id, []),
        crafter=r.crafter,
        output_item_id=r.recipe.output_item_id,
        output_name=base.items[r.recipe.output_item_id].name
        if r.recipe.output_item_id in base.items
        else "?",
        output_count=r.recipe.output_count,
        cost=r.cost,
        revenue=r.revenue,
        profit=r.profit,
        roi=r.roi,
        best_exit=r.best_exit,
        postage=r.postage,
        mail_to=r.mail_to,
        exits=[
            ExitOut(
                kind=e.kind,
                value=e.value,
                materials=[MaterialOut(**asdict(m)) for m in e.materials],
                postage=e.postage,
                mail_to=e.mail_to,
            )
            for e in r.exits
        ],
        reagents=[ItemCount(item_id=i, count=c) for i, c in r.recipe.reagents],
        steps=[
            StepOut(
                action=cast(Literal["buy", "craft", "mail", "sell"], s.action),
                item_id=s.item_id,
                name=s.name,
                quantity=s.quantity,
                value=s.value,
                via=s.via,
                who=s.who,
            )
            for s in r.steps
        ],
        tree=_node_out(r.tree),
        sell_options=[SellOptionOut(**asdict(o)) for o in r.sell_options],
    )


def _no_ah(state: AppState, conn: Connection, user: auth.User) -> frozenset[int]:
    return frozenset(i for i, _ in store.load_ah_blocked(conn, user.uid, state.key))


def _ah_blocked(state: AppState, conn: Connection, user: auth.User) -> AhBlocked:
    blocked = store.load_ah_blocked(conn, user.uid, state.key)
    base = state.cache.get(service.selected_auction_house(conn, user.uid, state.key))
    return AhBlocked(
        items=[AhBlockedItem(item_id=i, added_at=added) for i, added in blocked],
        details=_item_details(state, conn, base, (i for i, _ in blocked)),
    )


@router.get("/ah-blocked")
def get_ah_blocked(state: State, user: LinkedUser) -> AhBlocked:
    with _connect(state) as conn:
        return _ah_blocked(state, conn, user)


@router.put("/ah-blocked/{item_id}")
def block_ah(state: State, user: LinkedUser, item_id: int) -> AhBlocked:
    """Never sell `item_id` on the AH: /api/rank and /api/evaluate only vendor or disenchant it."""
    with _connect(state) as conn:
        store.set_ah_blocked(conn, user.uid, state.key, item_id, True)
        return _ah_blocked(state, conn, user)


@router.delete("/ah-blocked/{item_id}")
def unblock_ah(state: State, user: LinkedUser, item_id: int) -> AhBlocked:
    """Allow selling `item_id` on the AH again."""
    with _connect(state) as conn:
        store.set_ah_blocked(conn, user.uid, state.key, item_id, False)
        return _ah_blocked(state, conn, user)


# --- uploads and API keys -------------------------------------------------------------------------
def _database(request: Request) -> db.Database:
    return _auth(request).database


def _upload_out(u: uploads.UploadRow) -> UploadOut:
    return UploadOut(
        id=u.id,
        game_version=u.game_version,
        kind=cast(UploadKind, u.kind),
        via=cast(UploadVia, u.via),
        size=u.size,
        received_at=db.timestamp_text(u.received_at) or "",
        outcome=cast(Literal["accepted", "rejected"], u.outcome),
        detail=u.detail,
    )


def _read_upload(file: UploadFile) -> bytes:
    """The file's bytes, un-gzipped; 413 past uploads.MAX_BYTES either way."""
    raw = file.file.read(uploads.MAX_BYTES + 1)
    try:
        return uploads.decompress(raw, uploads.MAX_BYTES)
    except uploads.TooLarge:
        raise HTTPException(413, f"Files are limited to {uploads.MAX_BYTES // 2**20} MB.") from None


@router.post("/uploads")
def post_upload(
    state: State,
    user: Uploader,
    file: UploadFile,
    kind: Annotated[UploadKind, Form()],
    modified_at: Annotated[int | None, Form(description="the file's modified time, ms since 1970")] = None,
    via: Annotated[UploadVia, Form()] = "browser",
) -> UploadResult:
    """Import an addon's SavedVariables file (plain or gzipped): Alt Army replaces your characters of this
    game version, Auctionator adds a scan for every realm it has prices for."""
    database = state.database
    with database.begin() as conn:
        try:
            uploads.check_rate(conn, user.uid)
        except uploads.RateLimited:
            raise HTTPException(429, "Too many uploads: try again in an hour.") from None

    def reject(size: int, why: str) -> None:
        with database.begin() as conn:
            uploads.record_upload(conn, user.uid, state.key, kind, via, size, "rejected", why)

    try:
        data = _read_upload(file)
    except HTTPException as e:
        reject(uploads.MAX_BYTES, str(e.detail))
        raise
    except ValueError as e:
        reject(0, str(e))
        raise HTTPException(400, str(e)) from e
    modified = None if modified_at is None else datetime.fromtimestamp(modified_at / 1000, UTC)
    try:
        with database.begin() as conn:
            got = uploads.ingest(conn, user.uid, state.key, kind, data, modified)
            uploads.record_upload(conn, user.uid, state.key, kind, via, len(data), "accepted", got.detail)
    except ValueError as e:
        reject(len(data), str(e))
        raise HTTPException(400, str(e)) from e
    if got.auction_house_ids:
        state.cache.invalidate(got.auction_house_ids)
    return UploadResult(
        kind=kind,
        detail=got.detail,
        characters=got.characters,
        groups=[GroupCount(realm=r, faction=f, characters=n) for r, f, n in got.groups],
        realms=[RealmPricesOut(**asdict(r)) for r in got.realms],
    )


@router.get("/uploads")
def get_uploads(request: Request, user: CurrentUser) -> list[UploadOut]:
    """Your newest uploads (every game version), newest first."""
    with _database(request).begin() as conn:
        return [_upload_out(u) for u in uploads.recent(conn, user.uid)]


def _key_out(k: users.ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=k.id,
        prefix=k.prefix,
        label=k.label,
        created_at=db.timestamp_text(k.created_at) or "",
        last_used_at=db.timestamp_text(k.last_used_at),
    )


@router.get("/keys")
def get_keys(request: Request, user: LinkedUser) -> list[ApiKeyOut]:
    """Your API keys for the CLI watcher (the keys themselves are not stored)."""
    with _database(request).begin() as conn:
        return [_key_out(k) for k in users.list_keys(conn, user.uid)]


@router.post("/keys")
def post_key(request: Request, user: LinkedUser, body: KeyRequest) -> NewApiKey:
    """A new API key for `altarmy-profit watch`. The key is in this response only."""
    with _database(request).begin() as conn:
        made, key = users.create_key(conn, user.uid, body.label.strip() or "key")
    return NewApiKey(**_key_out(made).model_dump(), key=key)


@router.delete("/keys/{key_id}")
def delete_key(request: Request, user: LinkedUser, key_id: int) -> list[ApiKeyOut]:
    """Revoke a key: the watcher using it stops. Returns your remaining keys."""
    with _database(request).begin() as conn:
        if not users.revoke_key(conn, user.uid, key_id):
            raise HTTPException(404, f"You have no API key {key_id}.")
        return [_key_out(k) for k in users.list_keys(conn, user.uid)]


# --- prices ----------------------------------------------------------------------------------------
@router.get("/realms")
def get_realms(state: State, user: CurrentUser) -> list[AuctionHouseOut]:
    """The version's auction houses, with how many current prices each has."""
    with _connect(state) as conn:
        found = prices.auction_houses(conn, state.key)
    return [
        AuctionHouseOut(
            id=a.id,
            realm=a.realm,
            faction=a.faction,
            prices=a.prices,
            last_scan=db.timestamp_text(a.last_scan),
        )
        for a in found
    ]


def _check_auction_house(state: AppState, conn: Connection, auction_house_id: int) -> None:
    if prices.game_version_of(conn, auction_house_id) != state.key:
        raise HTTPException(404, f"No {state.version.label} auction house {auction_house_id}.")


@router.get("/prices")
def get_prices(
    state: State,
    user: CurrentUser,
    auction_house_id: int,
    q: Annotated[str, Query(description="part of the item name, any case; empty: every priced item")] = "",
    top: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PricesOut:
    """Items priced on the auction house, by name. The free tier only sees items whose required level is
    at most `free_max_level` (see /api/me)."""
    max_level = _max_level(user)
    with _connect(state) as conn:
        _check_auction_house(state, conn, auction_house_id)
        ids, total = store.search_prices(conn, state.key, auction_house_id, q, max_level, top)
        base = state.cache.get(auction_house_id)
        details = _item_details(state, conn, base, ids)
        found = prices.stats(conn, auction_house_id, ids)
    listed = [details[i] for i in ids if i in details]
    return PricesOut(
        items=listed,
        stats={i.id: _stats_out(found.get(i.id)) for i in listed},
        total=total,
        gated=max_level is not None,
    )


def _stats_out(s: prices.PriceStats | None) -> PriceStatsOut:
    if s is None:
        return PriceStatsOut(median_7d=None, avail_7d=None, scans_7d=None)
    return PriceStatsOut(median_7d=s.median_7d, avail_7d=s.avail_7d, scans_7d=s.scans_7d)


@router.get("/coverage")
def get_coverage(state: State, user: CurrentUser) -> list[CoverageOut]:
    """Each named auction house's scans: where uploads are needed. Open to every tier."""
    with _connect(state) as conn:
        found = prices.coverage(conn, state.key)
    return [
        CoverageOut(
            auction_house_id=c.auction_house_id,
            realm=c.realm,
            faction=c.faction,
            prices=c.prices,
            last_scan=db.timestamp_text(c.last_scan),
            last_scan_items=c.last_scan_items,
            scans_7d=c.scans_7d,
            uploaders_7d=c.uploaders_7d,
        )
        for c in found
    ]


@router.get("/prices/{item_id}")
def get_price_history(
    state: State, user: CurrentUser, auction_house_id: int, item_id: int
) -> PriceHistoryOut:
    """One item's current price and daily history on the auction house (403 for the free tier above its
    level)."""
    with _connect(state) as conn:
        _check_auction_house(state, conn, auction_house_id)
        base = state.cache.get(auction_house_id)
        details = _item_details(state, conn, base, [item_id])
        if item_id not in details:
            raise HTTPException(404, f"Unknown item {item_id}.")
        item = details[item_id]
        max_level = _max_level(user)
        if max_level is not None and item.required_level > max_level:
            raise HTTPException(
                403, f"Link your account to see prices of items above level {auth.FREE_TIER_MAX_LEVEL}."
            )
        days = prices.daily(conn, auction_house_id, item_id)
        found = prices.stats(conn, auction_house_id, [item_id]).get(item_id)
    return PriceHistoryOut(
        item=item,
        stats=None if found is None else _stats_out(found),
        days=[
            DayOut(day=d.isoformat(), low=low, high=high, available=available)
            for d, low, high, available in reversed(days)
        ],
    )


# --- local mode: game data, addon files ------------------------------------------------------------
@router.post("/game-data/update", dependencies=LOCAL_ONLY)
def update_game_data(
    state: State,
    only_if_new: Annotated[bool, Query(description="skip the rebuild if the newest build is loaded")] = False,
) -> UpdateResult:
    if not state.update_lock.acquire(blocking=False):
        raise HTTPException(409, "A game data update is already running.")
    try:
        with _http_errors(), _connect(state) as conn:
            build, updated, stats = service.update_game_data(
                conn, state.version, state.cache_dir, only_if_new=only_if_new
            )
    finally:
        state.update_lock.release()
    if updated:
        state.cache.invalidate()
    return UpdateResult(build=build, updated=updated, **stats)


def _source_files(state: AppState, user: auth.User, find: service.Finder, key: str) -> SourceFiles:
    files = [str(f) for f in find(state.wow_roots, state.version.flavor_folders)]
    with _connect(state) as conn:
        last: str | None = getattr(users.get_sync(conn, user.uid, state.key), key)
    return SourceFiles(files=files, default=service.default_path(files, last))


@router.get("/auctionator/files", dependencies=LOCAL_ONLY)
def get_auctionator_files(state: State, user: CurrentUser) -> SourceFiles:
    return _source_files(state, user, prices.find_auctionator_files, "auctionator_path")


@router.get("/altarmy/files", dependencies=LOCAL_ONLY)
def get_altarmy_files(state: State, user: CurrentUser) -> SourceFiles:
    return _source_files(state, user, prices.find_altarmy_files, "altarmy_path")


@router.post("/reload", dependencies=LOCAL_ONLY)
def reload(state: State, user: CurrentUser) -> Status:
    """Drop the cached market, e.g. after changing the database from the command line."""
    state.cache.invalidate()
    with _connect(state) as conn:
        return _status(state, conn, user, False)


# --- who and how -----------------------------------------------------------------------------------
@router.get("/config")
def get_config(request: Request) -> ConfigOut:
    """How the front end signs in: not at all (local mode), or with this Firebase project."""
    a = _auth(request)
    fb = a.firebase
    return ConfigOut(
        mode=a.mode,
        firebase=None
        if fb is None
        else FirebaseOut(
            api_key=fb.api_key,
            auth_domain=fb.auth_domain,
            project_id=fb.project_id,
            emulator_url=f"http://{fb.emulator_host}" if fb.emulator_host else None,
        ),
    )


@router.get("/me")
def get_me(user: CurrentUser) -> Me:
    return Me(uid=user.uid, tier=user.tier, free_max_level=auth.FREE_TIER_MAX_LEVEL)


@router.delete("/me", dependencies=HOSTED_ONLY, status_code=204)
def delete_me(request: Request, user: CurrentUser) -> None:
    """Delete your account: your characters, settings, AH blocks, upload history and API keys, then the
    sign-in account itself. Prices you uploaded stay in the pool, no longer linked to you."""
    a = _auth(request)
    if a.accounts is None:
        raise HTTPException(501, "Account deletion is not configured.")
    with a.database.begin() as conn:  # rolled back if the sign-in account can't be deleted
        users.delete_user(conn, user.uid)
        try:
            a.accounts.delete_user(user.uid)
        except auth.AccountError as e:
            raise HTTPException(502, f"Could not delete the sign-in account: {e}") from e


@router.get("/versions")
def get_versions(request: Request) -> list[VersionOut]:
    """The game versions served, each with the build its data comes from."""
    out = []
    for state in _states(request).values():
        with _connect(state) as conn:
            build, recipes = db.get_build(conn, state.key), db.count_rows(conn, "recipes", state.key)
        out.append(VersionOut(key=state.version.key, label=state.version.label, build=build, recipes=recipes))
    return out


def create_app(
    game_versions: Mapping[str, GameVersion] = versions.VERSIONS,
    *,
    database: db.Database | None = None,
    cache_dir: Path = CACHE_DIR,
    static_dir: Path | None = DEFAULT_DIST,
    wow_roots: Sequence[Path] = tuple(prices.WOW_ROOTS),
    mode: auth.Mode | None = None,
    verifier: auth.TokenVerifier | None = None,
    firebase: auth.FirebaseConfig | None = None,
    accounts: auth.AccountAdmin | None = None,
    limits: ratelimit.Limits | None = None,
) -> FastAPI:
    """Build the app for `game_versions`, each with its own data files, sharing `database` (default:
    `DATABASE_URL`, else data/altarmy-profit.sqlite). Touches no database or network (the schema is
    migrated on the first request), so tests and the OpenAPI export can call it freely.

    `mode` defaults to `ALTARMY_MODE` (local). Hosted mode takes the Firebase project from the environment
    (`auth.FirebaseConfig.from_env`) unless `firebase` is given, and verifies tokens with firebase-admin
    unless a `verifier` is given (tests pass a fake one), which also deletes accounts unless `accounts` is
    given. Hosted mode rate-limits with `limits` (default `ratelimit.HOSTED_LIMITS`) and never migrates
    the default database: each deploy does, once."""
    mode = mode or auth.mode_from_env()
    database = database or db.Database(db.default_url(), migrate=mode == "local")
    per_ip = per_uid = None
    if mode == "hosted":
        firebase = firebase or auth.FirebaseConfig.from_env()
        verifier = verifier or auth.FirebaseVerifier(firebase.project_id)
        if accounts is None and isinstance(verifier, auth.AccountAdmin):
            accounts = verifier
        limits = limits or ratelimit.HOSTED_LIMITS
        per_ip = ratelimit.RateLimiter(limits.per_ip, limits.window)
        per_uid = ratelimit.RateLimiter(limits.per_uid, limits.window)
    else:
        firebase = verifier = accounts = None
    app = FastAPI(title="altarmy-profit", version="0.1.0")
    app.state.auth = AuthState(mode, database, verifier, firebase, accounts, per_ip, per_uid)

    @app.middleware("http")
    async def api_headers_and_ip_limit(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        peer = request.client.host if request.client else None
        retry = per_ip.hit(ratelimit.client_ip(request.headers, peer)) if per_ip is not None else None
        if retry is not None:
            e = _too_many(retry)
            response: Response = JSONResponse({"detail": e.detail}, 429, headers=e.headers)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.state.wow = {
        key: AppState(
            v,
            database,
            cache_dir,
            service.MarketCache(database, v.key, ah_cut=v.ah_cut, mail_postage=v.mail_postage),
            service.RankCache(),
            threading.Lock(),
            threading.Lock(),
            wow_roots,
        )
        for key, v in game_versions.items()
    }
    app.include_router(router)
    if static_dir is not None and (static_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    else:

        @app.get("/", include_in_schema=False)
        def build_hint() -> dict[str, str]:
            return {"detail": "The front end is not built. Run `npm ci` and `npm run build` in frontend/."}

    return app
