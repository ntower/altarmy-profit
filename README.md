# wow-profit

Local tool that finds profitable crafting recipes and production chains for **WoW: Forever**.

- Items and recipes come from the client's DB2 tables (via [wago.tools](https://wago.tools/) CSV exports) into a local SQLite file.
- You supply auction house prices (CSV import for now).
- The engine ranks recipes by profit: reagent cost (buy, or craft an intermediate if cheaper) vs. the best of vendor sale, AH sale (minus the 5% cut) and expected disenchant value.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python scripts/check.py     # ruff lint + ruff format --check + mypy (strict) + pytest
```

Individual tools: `ruff check . --fix`, `ruff format .`, `mypy`, `pytest`.

## Usage

```powershell
wowprofit ingest                          # downloads DB2 tables into cache/, builds data/wowprofit.db
wowprofit import-prices prices.csv        # columns: item_id (or name), price   (copper)
wowprofit set-price 2589 250              # one item, copper
wowprofit rank --top 25 --skill Tailoring
```

`prices.csv` example:

```csv
name,price
Linen Cloth,45
Coarse Thread,120
```

## Data notes

- Pinned build: see `DEFAULT_BUILD` in `src/wowprofit/ingest.py`. Pass `--build` for a newer one.
- **Disenchant results are not in DB2** (they are server-side loot tables). Fill `data/disenchant.csv`
  (`item_class,quality,min_ilvl,max_ilvl,result_item_id,chance,min_count,max_count`) from a source such as
  Wowhead's Forever database, then re-run `wowprofit ingest`. Until then disenchant is ignored.
- **Vendor-sold reagents:** DB2 doesn't say which vendor sells what. Enter vendor prices as ordinary prices.
- Recipe output count is derived from `SpellEffect.EffectBasePointsF`; verify against known recipes.

## Layout

- `src/wowprofit/ingest.py` – download + load DB2 CSVs
- `src/wowprofit/engine.py` – pure profit/chain logic (no I/O), covered by `tests/`
- `src/wowprofit/prices.py` – price sources (CSV; addon SavedVariables importer is planned)
- `src/wowprofit/cli.py` – command line

## Roadmap

1. Verify ingest against known recipes on a real build.
2. Price importer for an AH-scanner addon's SavedVariables Lua file.
3. Streamlit UI (`pip install -e ".[ui]"`).
4. Recipe availability (who learns what / trainer vs. drop), auction volume and price-history risk.
