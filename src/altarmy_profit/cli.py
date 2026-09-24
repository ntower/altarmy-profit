"""Command line interface: ingest, import-prices, import-auctionator, import-altarmy, set-price, rank, ui.

`--game-version` (tbc | forever) picks the game's data, files and wago.tools product. Every version shares
one database: `--db` (a SQLite file), else `DATABASE_URL`, else data/altarmy-profit.sqlite.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

from . import altarmy, db, ingest, legacy, prices, service, store, versions
from .db import LOCAL_UID
from .engine import Filters, format_money
from .store import load_market
from .versions import GameVersion


def _version(args: argparse.Namespace) -> GameVersion:
    return versions.get(args.game_version)


def _database(args: argparse.Namespace) -> db.Database:
    """`--db`, else DATABASE_URL, else the default SQLite file (absolute, so the UI's threads agree)."""
    if args.db:
        return db.Database(db.sqlite_url(Path(args.db).resolve()))
    url = db.default_url()
    return db.Database(url if url != db.sqlite_url(db.DEFAULT_DB) else db.sqlite_url(db.DEFAULT_DB.resolve()))


def cmd_ingest(args: argparse.Namespace) -> None:
    v = _version(args)
    build = args.build or v.default_build
    if build == "latest":
        build = ingest.latest_build(v.wago_product)
    with args.database.begin() as conn:
        stats = ingest.update(conn, v.key, build, Path(args.cache), v.disenchant_csv, v.vendor_csv)
    print(f"Ingested {v.label} build {build}: {stats}")


def cmd_import_prices(args: argparse.Namespace) -> None:
    gv = args.game_version
    with args.database.begin() as conn:
        try:
            ah = service.pricing_auction_house(conn, LOCAL_UID, gv)
        except ValueError as e:
            sys.exit(str(e))
        n, unresolved = prices.import_csv(conn, gv, ah, Path(args.file))
    print(f"Imported {n} prices.")
    if unresolved:
        print("Unresolved names:", ", ".join(unresolved))


def cmd_import_auctionator(args: argparse.Namespace) -> None:
    with args.database.begin() as conn:
        try:
            realm, n, unknown = prices.import_auctionator(
                conn, args.game_version, Path(args.file), args.realm
            )
        except ValueError as e:
            sys.exit(str(e))
    print(f"Imported {n} prices from realm {realm}.")
    if unknown:
        print(f"{unknown} of them are item IDs not in the items table (stored anyway).")


def cmd_import_altarmy(args: argparse.Namespace) -> None:
    try:
        chars = altarmy.parse_characters(Path(args.file).read_bytes())
    except ValueError as e:
        sys.exit(str(e))
    with args.database.begin() as conn:
        store.save_characters(conn, LOCAL_UID, args.game_version, chars)
    for g in altarmy.groups(chars):
        print(f"{g.realm} ({g.faction}): {', '.join(c.name for c in g.characters)}")


def cmd_set_price(args: argparse.Namespace) -> None:
    with args.database.begin() as conn:
        try:
            ah = service.pricing_auction_house(conn, LOCAL_UID, args.game_version)
        except ValueError as e:
            sys.exit(str(e))
        prices.set_price(conn, ah, args.item_id, args.copper)


def cmd_rank(args: argparse.Namespace) -> None:
    if (args.realm is None) != (args.faction is None):
        sys.exit("Pass both --realm and --faction.")
    v = _version(args)
    with args.database.begin() as conn:
        if args.realm:
            try:
                service.select(conn, LOCAL_UID, v.key, args.realm, args.faction)
            except ValueError as e:
                sys.exit(str(e))
        sel, chars = service.selected_characters(conn, LOCAL_UID, v.key)
        ah = service.auction_house_of(conn, v.key, sel)
        market = load_market(conn, v.key, ah, ah_cut=v.ah_cut, mail_postage=v.mail_postage)
        no_ah = frozenset(i for i, _ in store.load_ah_blocked(conn, LOCAL_UID, v.key))
    if sel is None:  # no Alt Army import: rank every recipe
        results = market.rank(min_profit=args.min_profit, skill_name=args.skill)
    else:
        print(f"{sel.realm} ({sel.faction}). Characters: {', '.join(c.name for c in chars)}")
        filters = Filters(min_profit=args.min_profit)
        results = service.search(
            market, chars, args.include_unlearned, filters, no_ah=no_ah, include_trivial=not args.no_trivial
        )
        if args.skill:
            results = [r for r in results if r.recipe.skill_name.lower() == args.skill.lower()]
    results = results[: args.top]
    if not results:
        print("No profitable recipes found (are prices imported?).")
        return
    for r in results:
        out = market.items[r.recipe.output_item_id].name
        print(
            f"{format_money(r.profit):>14}  {r.roi:6.0%}  {r.recipe.name} -> {r.recipe.output_count}x {out}"
            f"  [cost {format_money(r.cost)}, sell via {r.best_exit}]"
        )
        for step in r.steps:
            if step.action == "craft" and step.via != r.recipe.name:
                print(f"{'':>24}chain: {step.quantity}x {step.name} via {step.via}")


def cmd_ui(args: argparse.Namespace) -> None:
    try:
        import uvicorn

        from .api import DEFAULT_DIST, create_app
    except ImportError:
        sys.exit('The web UI needs FastAPI and uvicorn: pip install -e ".[ui]"')
    if not (DEFAULT_DIST / "index.html").is_file():
        print(f"Front end not built ({DEFAULT_DIST} missing): run `npm ci` and `npm run build` in frontend/.")
    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    print(f"altarmy-profit UI on {url} (Ctrl+C to stop)")
    uvicorn.run(create_app(versions.VERSIONS, database=args.database), host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="altarmy-profit")
    p.add_argument(
        "--game-version",
        choices=list(versions.VERSIONS),
        default=versions.DEFAULT_VERSION,
        help="which game's data to use (default: %(default)s)",
    )
    p.add_argument(
        "--db", help="SQLite database file (default: DATABASE_URL, else data/altarmy-profit.sqlite)"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="download DB2 tables from wago.tools and build the database")
    s.add_argument("--build", help='a build version, or "latest" (default: the pinned build)')
    s.add_argument("--cache", default="cache")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("import-prices", help="import prices from CSV (item_id|name, price in copper)")
    s.add_argument("file")
    s.set_defaults(fn=cmd_import_prices)

    s = sub.add_parser(
        "import-auctionator",
        help="import minimum buyouts from Auctionator's account-wide SavedVariables/Auctionator.lua",
    )
    s.add_argument("file")
    s.add_argument("--realm", help="realm key in the file (needed when it holds several)")
    s.set_defaults(fn=cmd_import_auctionator)

    s = sub.add_parser(
        "import-altarmy",
        help="import characters, professions and recipes from Alt Army's SavedVariables/AltArmy_TBC.lua",
    )
    s.add_argument("file")
    s.set_defaults(fn=cmd_import_altarmy)

    s = sub.add_parser("set-price", help="set one item's price in copper")
    s.add_argument("item_id", type=int)
    s.add_argument("copper", type=int)
    s.set_defaults(fn=cmd_set_price)

    s = sub.add_parser("rank", help="rank recipes by profit")
    s.add_argument("--top", type=int, default=25)
    s.add_argument("--min-profit", type=int, default=0, help="copper")
    s.add_argument("--skill", help="filter by profession name, e.g. Tailoring")
    s.add_argument("--realm", help="rank what this realm's characters can craft (with --faction; remembered)")
    s.add_argument("--faction", help="Horde or Alliance")
    s.add_argument(
        "--include-unlearned", action="store_true", help="also recipes of their professions not yet learned"
    )
    s.add_argument(
        "--no-trivial", action="store_true", help="only recipes that can give the crafter a skillup"
    )
    s.set_defaults(fn=cmd_rank)

    s = sub.add_parser("ui", help="serve the web UI and API locally (needs the [ui] extra)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8600)
    s.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    s.set_defaults(fn=cmd_ui)

    args = p.parse_args(argv)
    args.database = _database(args)
    try:
        if args.db is None:
            for path in legacy.import_version_files(args.database):
                print(f"Imported {path} into {args.database.display_url} (kept as {path.name}.imported).")
        args.fn(args)
    finally:
        args.database.dispose()


if __name__ == "__main__":
    main()
