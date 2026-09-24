"""Command line interface: ingest, import-prices, import-auctionator, set-price, rank, ui."""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

from . import db, ingest, prices
from .engine import format_money
from .store import DISENCHANT_CSV, load_market


def cmd_ingest(args: argparse.Namespace) -> None:
    build = ingest.latest_build() if args.build == "latest" else args.build
    conn = db.connect(args.db)
    stats = ingest.update(conn, build, Path(args.cache), DISENCHANT_CSV)
    print(f"Ingested build {build}: {stats}")


def cmd_import_prices(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    n, unresolved = prices.import_csv(conn, Path(args.file))
    print(f"Imported {n} prices.")
    if unresolved:
        print("Unresolved names:", ", ".join(unresolved))


def cmd_import_auctionator(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    db.init_schema(conn)
    try:
        realm, n, unknown = prices.import_auctionator(conn, Path(args.file), args.realm)
    except ValueError as e:
        sys.exit(str(e))
    print(f"Imported {n} prices from realm {realm}.")
    if unknown:
        print(f"{unknown} of them are item IDs not in the items table (stored anyway).")


def cmd_set_price(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    prices.set_price(conn, args.item_id, args.copper)
    conn.commit()


def cmd_rank(args: argparse.Namespace) -> None:
    conn = db.connect(args.db)
    market = load_market(conn)
    results = market.rank(min_profit=args.min_profit, skill_name=args.skill)[: args.top]
    if not results:
        print("No profitable recipes found (are prices imported?).")
        return
    for r in results:
        out = market.items[r.recipe.output_item_id].name
        print(
            f"{format_money(r.profit):>14}  {r.roi:6.0%}  {r.recipe.name} -> {r.recipe.output_count}x {out}"
            f"  [cost {format_money(r.cost)}, sell via {r.best_exit}]"
        )
        for line in r.crafted_reagents:
            print(f"{'':>24}chain: {line}")


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
    print(f"wow-profit UI on {url} (Ctrl+C to stop)")
    uvicorn.run(create_app(Path(args.db).resolve()), host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="wowprofit")
    p.add_argument("--db", default=str(db.DEFAULT_DB))
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="download DB2 tables from wago.tools and build the database")
    s.add_argument("--build", default=ingest.DEFAULT_BUILD, help='a build version, or "latest"')
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

    s = sub.add_parser("set-price", help="set one item's price in copper")
    s.add_argument("item_id", type=int)
    s.add_argument("copper", type=int)
    s.set_defaults(fn=cmd_set_price)

    s = sub.add_parser("rank", help="rank recipes by profit")
    s.add_argument("--top", type=int, default=25)
    s.add_argument("--min-profit", type=int, default=0, help="copper")
    s.add_argument("--skill", help="filter by profession name, e.g. Tailoring")
    s.set_defaults(fn=cmd_rank)

    s = sub.add_parser("ui", help="serve the web UI and API locally (needs the [ui] extra)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8600)
    s.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    s.set_defaults(fn=cmd_ui)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
