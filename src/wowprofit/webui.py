"""Streamlit web UI: pick your professions, see the most profitable recipe chains.

Launch with `wowprofit ui`. Streamlit runs this file as a script, so imports are absolute and the DB
path comes from the WOWPROFIT_DB environment variable.
"""

from __future__ import annotations

import os

import streamlit as st

from wowprofit import db
from wowprofit.cli import load_market
from wowprofit.engine import PROFESSIONS, Item, Market, Result, format_money, recipes_for_professions

DB_ENV = "WOWPROFIT_DB"


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


def main() -> None:
    st.set_page_config(page_title="wow-profit", layout="wide")
    st.title("wow-profit")

    db_path = os.environ.get(DB_ENV, str(db.DEFAULT_DB))
    if st.sidebar.button("Reload data", help="Re-read the database after importing prices"):
        load_base_market.clear()
    base = load_base_market(db_path)

    if not base.recipes:
        st.error(f"No recipes in {db_path}. Run `wowprofit ingest` first.")
        return

    professions = st.sidebar.multiselect("Professions", available_professions(base))
    min_gold = st.sidebar.number_input("Min profit (gold)", value=0.0, step=0.5)
    top = int(st.sidebar.number_input("Show top", min_value=1, max_value=500, value=25, step=5))

    if not base.prices:
        st.warning("No prices yet. Import them with `wowprofit import-prices prices.csv`, then Reload data.")
    if not professions:
        st.info("Pick the professions you have in the sidebar.")
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


if __name__ == "__main__":
    main()
