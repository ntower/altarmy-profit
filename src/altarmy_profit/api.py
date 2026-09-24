"""FastAPI JSON API for the React front end, which it also serves once built (frontend/dist).

Money is integer copper on the wire; the front end formats it. Handlers are plain `def` so FastAPI runs
them in its threadpool: the game data download blocks for a while and must not stall other requests.
Each handler opens its own SQLite connection (connections are not shared across threads).
"""

from __future__ import annotations

import sqlite3
import threading
import urllib.error
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import altarmy, db, engine, prices, service, store
from .store import CACHE_DIR, DISENCHANT_CSV, VENDOR_CSV

DEFAULT_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

ExitKind = Literal["vendor", "ah", "disenchant"]
ALL_EXIT_KINDS: tuple[ExitKind, ...] = ("vendor", "ah", "disenchant")


# --- models ----------------------------------------------------------------------------------------
class SelectionModel(BaseModel):
    """A realm and faction: whose recipes count and which auction house prices them."""

    realm: str
    faction: str


class Status(BaseModel):
    db_path: str
    build: str | None
    items: int
    recipes: int
    prices: int
    characters: int
    last_auctionator_import: str | None  # SQLite CURRENT_TIMESTAMP text, UTC
    last_altarmy_sync: str | None  # same format
    last_auctionator_sync: str | None  # same format; set even when the scan had no prices for the realm
    altarmy_path: str | None
    auctionator_path: str | None
    auctionator_realm: str | None  # Auctionator's key for the selection; "" if it has none
    selection: SelectionModel | None
    data_version: int  # bumped whenever a sync re-imported something: refetch characters and results
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
    ah_price: int | None
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
    added_at: str  # SQLite CURRENT_TIMESTAMP text, UTC


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


# --- app state and helpers -------------------------------------------------------------------------
@dataclass
class AppState:
    db_path: Path
    cache_dir: Path
    disenchant_csv: Path
    vendor_csv: Path
    cache: service.MarketCache
    update_lock: threading.Lock
    sync_lock: threading.Lock
    wow_roots: Sequence[Path]  # where to look for the addons' SavedVariables


def _state(request: Request) -> AppState:
    state: AppState = request.app.state.wow
    return state


@contextmanager
def _connect(state: AppState) -> Iterator[sqlite3.Connection]:
    conn = db.connect(state.db_path)
    try:
        db.init_schema(conn)
        yield conn
    finally:
        conn.close()


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


def _sync(state: AppState, conn: sqlite3.Connection, force: bool = False) -> list[str]:
    """Re-import whichever addon file the game rewrote; returns the sync's warnings."""
    with state.sync_lock:
        result = service.sync(conn, state.wow_roots, force=force)
    if result.changed:
        state.cache.invalidate()
    return result.warnings


def _selection_model(sel: service.Selection | None) -> SelectionModel | None:
    return None if sel is None else SelectionModel(realm=sel.realm, faction=sel.faction)


def _status(state: AppState, conn: sqlite3.Connection, warnings: list[str] | None = None) -> Status:
    sel, _ = service.selected_characters(conn)
    return Status(
        db_path=str(state.db_path),
        build=db.get_meta(conn, "build"),
        items=db.count_rows(conn, "items"),
        recipes=db.count_rows(conn, "recipes"),
        prices=db.count_rows(conn, "prices"),
        characters=db.count_rows(conn, "characters"),
        last_auctionator_import=db.last_import(conn),
        last_altarmy_sync=db.get_meta(conn, "altarmy_synced"),
        last_auctionator_sync=db.get_meta(conn, "auctionator_synced"),
        altarmy_path=db.get_meta(conn, "altarmy_path"),
        auctionator_path=db.get_meta(conn, "auctionator_path"),
        auctionator_realm=db.get_meta(conn, "auctionator_realm"),
        selection=_selection_model(sel),
        data_version=service.data_version(conn),
        warnings=warnings or [],
    )


def _vendor_price(market: engine.Market, item_id: int) -> int | None:
    item = market.items.get(item_id)  # the cached market may predate the database
    return None if item is None else item.vendor_price


# --- routes ----------------------------------------------------------------------------------------
router = APIRouter(prefix="/api")


@router.get("/status")
def get_status(request: Request) -> Status:
    """Also the addon file watcher: re-imports Alt Army and Auctionator data the game has rewritten."""
    state = _state(request)
    with _connect(state) as conn:
        return _status(state, conn, _sync(state, conn))


@router.post("/sync")
def sync_now(request: Request) -> Status:
    """Re-import both addon files even if they look unchanged."""
    state = _state(request)
    with _connect(state) as conn:
        return _status(state, conn, _sync(state, conn, force=True))


@router.get("/characters")
def get_characters(request: Request) -> Characters:
    with _connect(_state(request)) as conn:
        chars = store.load_characters(conn)
        sel = service.selection(conn, chars)
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
def put_selection(request: Request, body: SelectionModel) -> Status:
    """Switch realm/faction; that realm's Auctionator prices replace the previous ones."""
    state = _state(request)
    with _http_errors(), _connect(state) as conn:
        service.select(conn, body.realm, body.faction)
        return _status(state, conn, _sync(state, conn))


@router.put("/sources")
def put_sources(request: Request, body: Sources) -> Status:
    state = _state(request)
    with _http_errors(), _connect(state) as conn:
        service.set_sources(conn, body.altarmy_path, body.auctionator_path)
        return _status(state, conn, _sync(state, conn, force=True))


@router.get("/rank")
def get_rank(
    request: Request,
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
    state = _state(request)
    base = state.cache.get()
    with _connect(state) as conn:
        _, chars = service.selected_characters(conn)
        no_ah = _no_ah(conn)
    filters = engine.Filters(min_cost, max_cost, min_profit, max_profit, min_roi, max_roi)
    matches = service.search(
        base, chars, include_unlearned, filters, frozenset(exits), no_ah, include_trivial
    )
    results = matches[:top]
    crafters = altarmy.crafters(chars)
    return RankResponse(
        total=len(matches),
        classes={c.name: c.class_file for c in chars},
        items=_item_infos(state, base, results),
        results=[_result_out(r, base, crafters) for r in results],
    )


@router.post("/evaluate")
def evaluate(request: Request, body: EvaluateRequest) -> EvaluateResponse:
    """One recipe as /api/rank would give it, with the user's `choices` of sources and exit applied."""
    state = _state(request)
    base = state.cache.get()
    with _connect(state) as conn:
        _, chars = service.selected_characters(conn)
        no_ah = _no_ah(conn)
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
        return _item_details(conn, base, item_ids)


def _item_details(
    conn: sqlite3.Connection, base: engine.Market, item_ids: Iterable[int]
) -> dict[int, ItemInfo]:
    details = store.load_item_details(conn, item_ids)
    return {
        i: ItemInfo(**asdict(d), ah_price=base.prices.get(i), vendor_price=_vendor_price(base, i))
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


def _no_ah(conn: sqlite3.Connection) -> frozenset[int]:
    return frozenset(i for i, _ in store.load_ah_blocked(conn))


def _ah_blocked(state: AppState, conn: sqlite3.Connection) -> AhBlocked:
    blocked = store.load_ah_blocked(conn)
    return AhBlocked(
        items=[AhBlockedItem(item_id=i, added_at=added) for i, added in blocked],
        details=_item_details(conn, state.cache.get(), (i for i, _ in blocked)),
    )


@router.get("/ah-blocked")
def get_ah_blocked(request: Request) -> AhBlocked:
    state = _state(request)
    with _connect(state) as conn:
        return _ah_blocked(state, conn)


@router.put("/ah-blocked/{item_id}")
def block_ah(request: Request, item_id: int) -> AhBlocked:
    """Never sell `item_id` on the AH: /api/rank and /api/evaluate only vendor or disenchant it."""
    state = _state(request)
    with _connect(state) as conn:
        store.set_ah_blocked(conn, item_id, True)
        return _ah_blocked(state, conn)


@router.delete("/ah-blocked/{item_id}")
def unblock_ah(request: Request, item_id: int) -> AhBlocked:
    """Allow selling `item_id` on the AH again."""
    state = _state(request)
    with _connect(state) as conn:
        store.set_ah_blocked(conn, item_id, False)
        return _ah_blocked(state, conn)


@router.post("/game-data/update")
def update_game_data(
    request: Request,
    only_if_new: Annotated[bool, Query(description="skip the rebuild if the newest build is loaded")] = False,
) -> UpdateResult:
    state = _state(request)
    if not state.update_lock.acquire(blocking=False):
        raise HTTPException(409, "A game data update is already running.")
    try:
        with _http_errors(), _connect(state) as conn:
            build, updated, stats = service.update_game_data(
                conn, state.cache_dir, state.disenchant_csv, state.vendor_csv, only_if_new=only_if_new
            )
    finally:
        state.update_lock.release()
    if updated:
        state.cache.invalidate()
    return UpdateResult(build=build, updated=updated, **stats)


def _source_files(request: Request, find: Callable[[Iterable[Path]], list[Path]], key: str) -> SourceFiles:
    state = _state(request)
    files = [str(f) for f in find(state.wow_roots)]
    with _connect(state) as conn:
        last = db.get_meta(conn, key)
    return SourceFiles(files=files, default=service.default_path(files, last))


@router.get("/auctionator/files")
def get_auctionator_files(request: Request) -> SourceFiles:
    return _source_files(request, prices.find_auctionator_files, "auctionator_path")


@router.get("/altarmy/files")
def get_altarmy_files(request: Request) -> SourceFiles:
    return _source_files(request, prices.find_altarmy_files, "altarmy_path")


@router.post("/reload")
def reload(request: Request) -> Status:
    """Drop the cached market, e.g. after changing the database from the command line."""
    state = _state(request)
    state.cache.invalidate()
    with _connect(state) as conn:
        return _status(state, conn)


def create_app(
    db_path: Path | str,
    *,
    cache_dir: Path = CACHE_DIR,
    disenchant_csv: Path = DISENCHANT_CSV,
    vendor_csv: Path = VENDOR_CSV,
    static_dir: Path | None = DEFAULT_DIST,
    wow_roots: Sequence[Path] = tuple(prices.WOW_ROOTS),
) -> FastAPI:
    """Build the app. Touches no database or network, so tests and the OpenAPI export can call it freely."""
    db_path = Path(db_path)
    app = FastAPI(title="altarmy-profit", version="0.1.0")
    app.state.wow = AppState(
        db_path,
        cache_dir,
        disenchant_csv,
        vendor_csv,
        service.MarketCache(db_path),
        threading.Lock(),
        threading.Lock(),
        wow_roots,
    )
    app.include_router(router)
    if static_dir is not None and (static_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    else:

        @app.get("/", include_in_schema=False)
        def build_hint() -> dict[str, str]:
            return {"detail": "The front end is not built. Run `npm ci` and `npm run build` in frontend/."}

    return app
