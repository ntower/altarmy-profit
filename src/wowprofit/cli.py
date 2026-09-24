"""Command line interface: ingest, import-prices, import-auctionator, set-price, rank, ui."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from . import db, ingest, prices
from .engine import DisenchantRow, Item, Market, Recipe, format_money

DISENCHANT_CSV = Path("data/disenchant.csv")


def load_market(conn: sqlite3.Connection) -> Market:
    items = {
        r["id"]: Item(r["id"], r["name"], r["quality"], r["item_level"], r["class_id"], r["sell_price"])
        for r in conn.execute("SELECT * FROM items")
    }
    reagents: dict[int, list[tuple[int, int]]] = {}
    for r in conn.execute("SELECT recipe_id, item_id, count FROM recipe_reagents"):
        reagents.setdefault(r["recipe_id"], []).append((r["item_id"], r["count"]))
    recipes = [
        Recipe(
            r["id"],
            r["name"],
            r["output_item_id"],
            r["output_count"],
            tuple(reagents.get(r["id"], ())),
            r["skill_name"],
            r["min_skill"],
        )
        for r in conn.execute("SELECT * FROM recipes")
    ]
    de = [DisenchantRow(*tuple(r)) for r in conn.execute("SELECT * FROM disenchant")]
    return Market(items, recipes, prices.load_prices(conn), de)


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
        from streamlit.web import cli as stcli
    except ImportError:
        sys.exit('The web UI needs Streamlit: pip install -e ".[ui]"')
    os.environ["WOWPROFIT_DB"] = str(Path(args.db).resolve())
    sys.argv = ["streamlit", "run", str(Path(__file__).with_name("webui.py")), *args.streamlit_args]
    sys.exit(stcli.main())


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

    s = sub.add_parser(
        "ui",
        help="open the web UI (needs the [ui] extra); extra args go to streamlit, e.g. --server.port 8600",
    )
    s.set_defaults(fn=cmd_ui)

    args, extra = p.parse_known_args(argv)
    if extra and args.cmd != "ui":
        p.error(f"unrecognized arguments: {' '.join(extra)}")
    args.streamlit_args = extra
    args.fn(args)


if __name__ == "__main__":
    main()
