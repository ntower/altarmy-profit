# wow-profit

Local tool that finds profitable crafting recipes and production chains for **WoW: Forever**.

- Items and recipes come from the client's DB2 tables (via [wago.tools](https://wago.tools/) CSV exports) into a local SQLite file.
- You supply auction house prices (CSV import for now).
- The engine ranks recipes by profit: reagent cost (buy, or craft an intermediate if cheaper) vs. the best of vendor sale, AH sale (minus the 5% cut) and expected disenchant value.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,ui]"   # drop ,ui if you only want the CLI
python scripts/check.py     # ruff lint + ruff format --check + mypy (strict) + pytest
```

Individual tools: `ruff check . --fix`, `ruff format .`, `mypy`, `pytest`.

## Usage

```powershell
wowprofit ingest                          # downloads DB2 tables into cache/, builds data/wowprofit.db
wowprofit ingest --build latest           # same, for the newest WoW: Forever build on wago.tools
wowprofit import-prices prices.csv        # columns: item_id (or name), price   (copper)
wowprofit import-auctionator "<WoW>\_classic_beta_\WTF\Account\<account>\SavedVariables\Auctionator.lua"
wowprofit set-price 2589 250              # one item, copper
wowprofit rank --top 25 --skill Tailoring
wowprofit ui                              # web UI (Search and Manage tabs, see below)
```

`import-auctionator` reads Auctionator's **account-wide** SavedVariables file (not the per-character
one) and stores each item's latest minimum buyout. WoW writes SavedVariables on logout or `/reload`,
so do one of those after scanning. Add `--realm "<name>"` if the file holds several realms (the error
lists them). Items missing from a scan keep their previous price.

The web UI has two tabs. **Search** ranks recipes for the professions you pick. **Manage** has
buttons to download the latest game data (the newest `wow_classic_beta` build on wago.tools; prices
are kept) and to import Auctionator prices. It finds `Auctionator.lua` under the usual WoW install
folders, preferring `_classic_beta_`, and you can paste another path. It remembers the file and realm
you last imported.

`prices.csv` example:

```csv
name,price
Linen Cloth,45
Coarse Thread,120
```

## Data notes

- Pinned build: see `DEFAULT_BUILD` in `src/wowprofit/ingest.py`. Pass `--build <version>` or `--build latest`
  for a newer one. The build actually loaded is stored in the `meta` table.
- **Disenchant results are not in DB2** (they are server-side loot tables). `data/disenchant.csv`
  (`item_class,quality,min_ilvl,max_ilvl,result_item_id,chance,min_count,max_count`) holds Classic-era
  rates, derived from the brackets Auctionator uses for Classic clients. Counts within a row are
  assumed uniform. Coverage: greens ilvl 5–65, blues 11–65, epics 40–80; items outside those
  ranges get no disenchant value. Forever-specific rates are not yet published — verify against
  Wowhead's Forever database as data comes in, then re-run `wowprofit ingest`.
- **Vendor-sold reagents:** DB2 doesn't say which vendor sells what. Enter vendor prices as ordinary prices.
- Recipe output count is derived from `SpellEffect.EffectBasePointsF`; verify against known recipes.

## Layout

- `src/wowprofit/ingest.py` – download + load DB2 CSVs
- `src/wowprofit/engine.py` – pure profit/chain logic (no I/O), covered by `tests/`
- `src/wowprofit/prices.py` – price sources (CSV, Auctionator SavedVariables via `auctionator.py`)
- `src/wowprofit/cli.py` – command line

## Roadmap

1. Verify ingest against known recipes on a real build.
2. ~~Auctionator SavedVariables importer~~ (done: `wowprofit import-auctionator`).
3. ~~Streamlit UI~~ (done: `wowprofit ui`). Next: filter by skill level, which needs real required-skill data.
4. Recipe availability (who learns what / trainer vs. drop), auction volume and price-history risk.
