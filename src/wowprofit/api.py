"""FastAPI JSON API for the React front end, which it also serves once built (frontend/dist).

Money is integer copper on the wire; the front end formats it. Handlers are plain `def` so FastAPI runs
them in its threadpool: the game data download blocks for a while and must not stall other requests.
Each handler opens its own SQLite connection (connections are not shared across threads).
"""

from __future__ import annotations

import sqlite3
import threading
import urllib.error
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, prices, service, store
from .store import CACHE_DIR, DISENCHANT_CSV

DEFAULT_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


# --- models ----------------------------------------------------------------------------------------
class Status(BaseModel):
    db_path: str
    build: str | None
    items: int
    recipes: int
    prices: int
    last_auctionator_import: str | None  # SQLite CURRENT_TIMESTAMP text, UTC


class ExitOut(BaseModel):
    kind: str  # vendor | ah | disenchant
    value: int  # copper per item, after cuts


class StepOut(BaseModel):
    action: Literal["buy", "craft", "sell"]
    item_id: int
    name: str
    quantity: int
    value: int  # copper for the whole step: negative when buying, positive when selling
    via: str  # craft: recipe name; sell: vendor | ah | disenchant


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


class RankResult(BaseModel):
    recipe_id: int
    recipe: str
    profession: str
    output_item_id: int
    output_name: str
    output_count: int
    cost: int
    revenue: int
    profit: int
    roi: float
    best_exit: str
    exits: list[ExitOut]
    reagents: list[ItemCount]
    steps: list[StepOut]  # buy reagents, craft (intermediates first), sell


class RankResponse(BaseModel):
    results: list[RankResult]
    items: dict[int, ItemInfo]  # every item the results mention, for tooltips


class UpdateResult(BaseModel):
    build: str
    items: int
    recipes: int
    disenchant_rows: int


class AuctionatorFiles(BaseModel):
    files: list[str]
    default: str | None


class Realms(BaseModel):
    realms: list[str]
    default: str | None


class ImportRequest(BaseModel):
    path: str
    realm: str


class ImportResult(BaseModel):
    realm: str
    imported: int
    unknown: int


# --- app state and helpers -------------------------------------------------------------------------
@dataclass
class AppState:
    db_path: Path
    cache_dir: Path
    disenchant_csv: Path
    cache: service.MarketCache
    update_lock: threading.Lock


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


def _existing_file(path: str) -> Path:
    file = Path(path)
    if not file.is_file():
        raise HTTPException(404, f"File not found: {file}")
    return file


def _status(state: AppState, conn: sqlite3.Connection) -> Status:
    return Status(
        db_path=str(state.db_path),
        build=db.get_meta(conn, "build"),
        items=db.count_rows(conn, "items"),
        recipes=db.count_rows(conn, "recipes"),
        prices=db.count_rows(conn, "prices"),
        last_auctionator_import=db.last_import(conn),
    )


# --- routes ----------------------------------------------------------------------------------------
router = APIRouter(prefix="/api")


@router.get("/status")
def get_status(request: Request) -> Status:
    state = _state(request)
    with _connect(state) as conn:
        return _status(state, conn)


@router.get("/professions")
def get_professions(request: Request) -> list[str]:
    return service.available_professions(_state(request).cache.get())


@router.get("/rank")
def get_rank(
    request: Request,
    professions: Annotated[list[str], Query(default_factory=list)],
    min_profit: Annotated[int, Query(description="copper")] = 0,
    top: Annotated[int, Query(ge=1, le=500)] = 25,
) -> RankResponse:
    state = _state(request)
    base = state.cache.get()
    results = service.search(base, professions, min_profit, top)
    item_ids = {s.item_id for r in results for s in r.steps} | {
        i for r in results for i, _ in r.recipe.reagents
    }
    with _connect(state) as conn:
        details = store.load_item_details(conn, item_ids)
    return RankResponse(
        items={i: ItemInfo(**asdict(d), ah_price=base.prices.get(i)) for i, d in details.items()},
        results=[
            RankResult(
                recipe_id=r.recipe.id,
                recipe=r.recipe.name,
                profession=r.recipe.skill_name,
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
                exits=[ExitOut(kind=e.kind, value=e.value) for e in r.exits],
                reagents=[ItemCount(item_id=i, count=c) for i, c in r.recipe.reagents],
                steps=[
                    StepOut(
                        action=cast(Literal["buy", "craft", "sell"], s.action),
                        item_id=s.item_id,
                        name=s.name,
                        quantity=s.quantity,
                        value=s.value,
                        via=s.via,
                    )
                    for s in r.steps
                ],
            )
            for r in results
        ],
    )


@router.post("/game-data/update")
def update_game_data(request: Request) -> UpdateResult:
    state = _state(request)
    if not state.update_lock.acquire(blocking=False):
        raise HTTPException(409, "A game data update is already running.")
    try:
        with _http_errors(), _connect(state) as conn:
            build, stats = service.update_game_data(conn, state.cache_dir, state.disenchant_csv)
    finally:
        state.update_lock.release()
    state.cache.invalidate()
    return UpdateResult(
        build=build, items=stats["items"], recipes=stats["recipes"], disenchant_rows=stats["disenchant_rows"]
    )


@router.get("/auctionator/files")
def get_auctionator_files(request: Request) -> AuctionatorFiles:
    files = [str(f) for f in prices.find_auctionator_files()]
    with _connect(_state(request)) as conn:
        last = db.get_meta(conn, "auctionator_path")
    return AuctionatorFiles(files=files, default=service.default_auctionator_path(files, last))


@router.get("/auctionator/realms")
def get_auctionator_realms(request: Request, path: str) -> Realms:
    file = _existing_file(path)
    with _http_errors():
        realms = prices.auctionator_realms(file)
    with _connect(_state(request)) as conn:
        last = db.get_meta(conn, "auctionator_realm")
    return Realms(realms=realms, default=service.default_realm(realms, last))


@router.post("/auctionator/import")
def import_auctionator(request: Request, body: ImportRequest) -> ImportResult:
    state = _state(request)
    file = _existing_file(body.path)
    with _http_errors(), _connect(state) as conn:
        realm, imported, unknown = service.import_auctionator(conn, file, body.realm)
    state.cache.invalidate()
    return ImportResult(realm=realm, imported=imported, unknown=unknown)


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
    static_dir: Path | None = DEFAULT_DIST,
) -> FastAPI:
    """Build the app. Touches no database or network, so tests and the OpenAPI export can call it freely."""
    db_path = Path(db_path)
    app = FastAPI(title="wow-profit", version="0.1.0")
    app.state.wow = AppState(
        db_path, cache_dir, disenchant_csv, service.MarketCache(db_path), threading.Lock()
    )
    app.include_router(router)
    if static_dir is not None and (static_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    else:

        @app.get("/", include_in_schema=False)
        def build_hint() -> dict[str, str]:
            return {"detail": "The front end is not built. Run `npm ci` and `npm run build` in frontend/."}

    return app
