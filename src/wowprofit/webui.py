"""Streamlit web UI. Search tab: pick your professions, see the most profitable recipe chains.
Manage tab: download the latest game data and import Auctionator prices.

Launch with `wowprofit ui`. Streamlit runs this file as a script, so imports are absolute and the DB
path comes from the WOWPROFIT_DB environment variable.
"""

from __future__ import annotations

import os
import sqlite3
import urllib.error
from pathlib import Path

import streamlit as st

from wowprofit import db, ingest, prices
from wowprofit.cli import DISENCHANT_CSV, load_market
from wowprofit.engine import PROFESSIONS, Item, Market, Result, format_money, recipes_for_professions

DB_ENV = "WOWPROFIT_DB"
CACHE_DIR = Path("cache")


def available_professions(market: Market) -> list[str]:
    present = {r.skill_name for r in market.recipes}
    return [p for p in PROFESSIONS if p in present]


def build_rows(results: list[Result], items: dict[int, Item]) -> list[dict[str, str]]:
    rows = []
    for r in results:
        out = items[r.recipe.output_item_id].name if r.recipe.output_item_id in items else "?"
        rows.append(
            {
                "Profit": format_money(r.profit),
                "ROI": f"{r.roi:.0%}",
                "Recipe": r.recipe.name,
                "Profession": r.recipe.skill_name,
                "Output": f"{r.recipe.output_count}x {out}",
                "Cost": format_money(r.cost),
                "Revenue": format_money(r.revenue),
                "Sell via": r.best_exit,
            }
        )
    return rows


@st.cache_resource
def load_base_market(db_path: str) -> Market:
    conn = db.connect(db_path)
    try:
        db.init_schema(conn)
        return load_market(conn)
    finally:
        conn.close()


@st.cache_data
def auctionator_realms(path: str, mtime: float) -> list[str]:
    """Realms in a SavedVariables file; `mtime` is only part of the cache key."""
    return prices.auctionator_realms(Path(path))


def default_auctionator_path(files: list[str], last: str | None) -> int | None:
    if last in files:
        return files.index(last)
    forever = [i for i, f in enumerate(files) if "_classic_beta_" in f]
    return forever[0] if forever else (0 if files else None)


def manage_tab(db_path: str) -> None:
    conn = db.connect(db_path)
    try:
        db.init_schema(conn)
        game_data_section(conn)
        st.divider()
        auctionator_section(conn)
        st.divider()
        if st.button("Reload data", help="Re-read the database after changing it from the command line"):
            load_base_market.clear()
    finally:
        conn.close()


def game_data_section(conn: sqlite3.Connection) -> None:
    st.subheader("Game data")
    n_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    n_recipes = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    st.write(f"Build **{db.get_meta(conn, 'build') or 'none'}**: {n_items:,} items, {n_recipes:,} recipes.")
    if st.button("Download latest game data", key="update_game_data"):
        try:
            with st.spinner("Downloading DB2 tables from wago.tools and rebuilding..."):
                build = ingest.latest_build()
                stats = ingest.update(conn, build, CACHE_DIR, DISENCHANT_CSV)
        except (urllib.error.URLError, OSError, ValueError) as e:
            st.error(f"Update failed: {e}")
            return
        load_base_market.clear()
        st.success(f"Loaded build {build}: {stats['items']:,} items, {stats['recipes']:,} recipes.")


def auctionator_section(conn: sqlite3.Connection) -> None:
    st.subheader("Auctionator prices")
    last = conn.execute("SELECT MAX(updated_at) FROM prices WHERE source = 'auctionator'").fetchone()[0]
    st.write(f"Last import: **{last} UTC**" if last else "Last import: **never**")
    st.caption("WoW writes SavedVariables on logout or `/reload`, so do one of those after scanning.")

    files = [str(f) for f in prices.find_auctionator_files()]
    path = st.selectbox(
        "Auctionator.lua (account-wide SavedVariables)",
        files,
        index=default_auctionator_path(files, db.get_meta(conn, "auctionator_path")),
        accept_new_options=True,
        placeholder="Paste the path to Auctionator.lua",
        key="auctionator_path",
    )
    if not path:
        return
    file = Path(path)
    if not file.is_file():
        st.error(f"File not found: {file}")
        return
    try:
        realms = auctionator_realms(str(file), file.stat().st_mtime)
    except ValueError as e:
        st.error(str(e))
        return
    if not realms:
        st.warning("No realms in this file yet. Scan the auction house first.")
        return
    last_realm = db.get_meta(conn, "auctionator_realm")
    realm = st.selectbox(
        "Realm", realms, index=realms.index(last_realm) if last_realm in realms else 0, key="realm"
    )
    if st.button("Import prices", key="import_auctionator"):
        _, n, unknown = prices.import_auctionator(conn, file, realm)
        db.set_meta(conn, "auctionator_path", str(file))
        db.set_meta(conn, "auctionator_realm", realm)
        load_base_market.clear()
        st.success(f"Imported {n:,} prices from {realm} ({unknown:,} items not in the game data).")


def search_tab(base: Market, db_path: str) -> None:
    if not base.recipes:
        st.error(
            f"No recipes in {db_path}. Download game data on the Manage tab (or run `wowprofit ingest`)."
        )
        return

    c1, c2, c3 = st.columns([3, 1, 1])
    professions = c1.multiselect("Professions", available_professions(base))
    min_gold = c2.number_input("Min profit (gold)", value=0.0, step=0.5)
    top = int(c3.number_input("Show top", min_value=1, max_value=500, value=25, step=5))

    if not base.prices:
        st.warning("No prices yet. Import them on the Manage tab.")
    if not professions:
        st.info("Pick the professions you have.")
        return

    market = Market(
        base.items, recipes_for_professions(base.recipes, professions), base.prices, base.disenchant
    )
    results = market.rank(min_profit=round(min_gold * 10000))[:top]
    if not results:
        st.info("No profitable recipes found for these professions with the current prices.")
        return

    st.dataframe(build_rows(results, base.items), hide_index=True)

    st.subheader("Details")
    for r in results:
        with st.expander(f"{format_money(r.profit)}  {r.recipe.name}"):
            if r.crafted_reagents:
                st.markdown("**Chain**\n" + "\n".join(f"- {line}" for line in r.crafted_reagents))
            else:
                st.markdown("**Chain:** buy all reagents")
            st.markdown(
                "**Sell options** (per item)\n"
                + "\n".join(f"- {e.kind}: {format_money(e.value)}" for e in r.exits)
            )


def main() -> None:
    st.set_page_config(page_title="wow-profit", layout="wide")
    st.title("wow-profit")

    db_path = os.environ.get(DB_ENV, str(db.DEFAULT_DB))
    search, manage = st.tabs(["Search", "Manage"])
    # Manage runs first so an import it triggers shows up in Search on the same run.
    with manage:
        manage_tab(db_path)
    with search:
        search_tab(load_base_market(db_path), db_path)


if __name__ == "__main__":
    main()
