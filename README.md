# altarmy-profit

Local tool that finds profitable crafting recipes and production chains for **WoW: Forever**.

- Items and recipes come from the client's DB2 tables (via [wago.tools](https://wago.tools/) CSV exports) into a local SQLite file.
- You supply auction house prices (CSV import for now).
- The engine ranks recipes by profit: reagent cost (buy from a vendor or the AH, or craft an intermediate if cheaper) vs. the best of vendor sale, AH sale (minus the 5% cut) and expected disenchant value. Each craft is costed per character: a reagent is bought by the crafter, or crafted by whichever of your characters can make it and mailed over (30c postage per stack), whichever is cheapest. Disenchanting needs an enchanter among the selected characters; if the crafter doesn't enchant, the output is mailed to the highest-skilled enchanter.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,ui]"   # drop ,ui if you only want the CLI
npm ci; cd frontend; npm ci; npm run build; cd ..   # web UI and dev tooling (needs Node.js)
python scripts/check.py     # Python: ruff, mypy (strict), pytest. Front end: oxlint, vitest, tsc + vite build
```

`python scripts/check.py --skip-frontend` runs only the Python steps. Individual tools: `ruff check . --fix`,
`ruff format .`, `mypy`, `pytest`, and in `frontend/`: `npm run lint`, `npm test`, `npm run build`.

## Usage

```powershell
altarmy-profit ingest                          # downloads DB2 tables into cache/, builds data/altarmy-profit.db
altarmy-profit ingest --build latest           # same, for the newest WoW: Forever build on wago.tools
altarmy-profit import-prices prices.csv        # columns: item_id (or name), price   (copper)
altarmy-profit import-auctionator "<WoW>\_classic_beta_\WTF\Account\<account>\SavedVariables\Auctionator.lua"
altarmy-profit import-altarmy "<WoW>\_classic_beta_\WTF\Account\<account>\SavedVariables\AltArmy_TBC.lua"
altarmy-profit set-price 2589 250              # one item, copper
altarmy-profit rank --top 25 --realm "Classic Beta PvE" --faction Horde   # remembered; --include-unlearned
altarmy-profit ui                              # web UI on http://127.0.0.1:8600 (--port, --no-browser)
```

`import-auctionator` reads Auctionator's **account-wide** SavedVariables file (not the per-character
one) and stores each item's latest minimum buyout. WoW writes SavedVariables on logout or `/reload`,
so do one of those after scanning. Add `--realm "<name>"` if the file holds several realms (the error
lists them). Items missing from a scan keep their previous price.

`import-altarmy` reads the [Alt Army](../altarmy_tbc) addon's account-wide SavedVariables: your
characters, their professions and the recipes they have learned. `rank` then only ranks what the
characters of one realm and faction can craft (chains may use any of their recipes, whoever knows them).

The web UI is a React app (`frontend/`) served by a local FastAPI server (`altarmy-profit ui`); build
it once with `npm run build` in `frontend/`. It has two tabs:

- **Search** ranks what your characters on the chosen realm and faction can craft, and names who
  crafts each recipe. A switch adds recipes of their professions they have not learned yet. Expand a
  recipe to see its plan as a flow chart or steps. Where a material could come from elsewhere (vendor,
  AH, or a craft), or the output could be sold another way, the node's ⇄ menu lists the options, best
  first. Picking one re-costs the recipe, adding or removing buy, craft and mail steps, and the row
  shows the changed numbers. **Reset** goes back to the best plan. A row's ⋯ menu can mark its output
  **Never sell on auction house**: from then on it is only vendored or disenchanted (it can still be
  bought there).
- **Manage** lists the items never sold on the auction house (remove one to allow it again), downloads
  the latest game data (the newest `wow_classic_beta` build on wago.tools; prices are kept) and shows
  the addon files in use.

The UI reads `AltArmy_TBC.lua` and `Auctionator.lua` itself: it finds them under the usual WoW install
folders (preferring `_classic_beta_`; paste another path on Manage) and re-imports either one whenever
WoW rewrites it, on logout or `/reload`. Prices come from the chosen realm's Auctionator scan and replace
the previous realm's.

### Front-end development

Run `npm run dev` in the repo root. It starts the Python API on :8600 (`altarmy-profit ui --no-browser`,
via the venv), waits for it, then starts Vite and opens http://localhost:5173. Vite hot-reloads the
React code and proxies `/api` to the Python server; press Ctrl+C and rerun for Python changes. After changing the API's models or routes, regenerate the
TypeScript types with `python scripts/export_openapi.py` and `npm run gen-types` (`check.py` does both).

`prices.csv` example:

```csv
name,price
Linen Cloth,45
Coarse Thread,120
```

## Data notes

- Pinned build: see `DEFAULT_BUILD` in `src/altarmy_profit/ingest.py`. Pass `--build <version>` or `--build latest`
  for a newer one. The build actually loaded is stored in the `meta` table.
- **Disenchant results are not in DB2** (they are server-side loot tables). `data/disenchant.csv`
  (`item_class,quality,min_ilvl,max_ilvl,result_item_id,chance,min_count,max_count`) holds Classic-era
  rates, derived from the brackets Auctionator uses for Classic clients. Counts within a row are
  assumed uniform. Coverage: greens ilvl 5–65, blues 11–65, epics 40–80; items outside those
  ranges get no disenchant value. Forever-specific rates are not yet published — verify against
  Wowhead's Forever database as data comes in, then re-run `altarmy-profit ingest`.
- **Vendor-sold items are not in DB2** (vendor inventories are server-side). `data/vendor_items.csv`
  (`item_id,name`) lists the items vanilla vendors sell with unlimited stock and no reputation or event
  condition, taken from [vmangos](https://github.com/vmangos/core)' world database by
  `python scripts/build_vendor_items.py`. The price is DB2's `BuyPrice` per `VendorStackCount`, rounded up
  to whole copper. Reagents are bought from whichever of vendor and AH is cheaper. Forever may differ from
  vanilla; edit the CSV and re-run `altarmy-profit ingest` if a vendor item is missing or wrong.
- Recipe output count is derived from `SpellEffect.EffectBasePointsF`; verify against known recipes.

## Layout

- `src/altarmy_profit/ingest.py` – download + load DB2 CSVs
- `src/altarmy_profit/engine.py` – pure profit/chain logic (no I/O), covered by `tests/`
- `src/altarmy_profit/prices.py` – price sources (CSV, Auctionator SavedVariables via `auctionator.py`)
- `src/altarmy_profit/altarmy.py` – characters and learned recipes from Alt Army's SavedVariables (`luasv.py` parses them)
- `src/altarmy_profit/store.py` – load SQLite into engine dataclasses
- `src/altarmy_profit/service.py`, `api.py` – use-cases and the FastAPI JSON API behind the web UI
- `src/altarmy_profit/cli.py` – command line
- `frontend/` – Vite + React + TypeScript + Mantine web UI
- `docs/` – plans: `HOSTED_PLAN.md` (hosted, multi-user transition), `ROADMAP_IDEAS.md` (feature ideas)

## Roadmap

1. Verify ingest against known recipes on a real build.
2. ~~Auctionator SavedVariables importer~~ (done: `altarmy-profit import-auctionator`).
3. ~~Web UI~~ (done: `altarmy-profit ui`, React + FastAPI). Next: filter by skill level, which needs real required-skill data.
4. Recipe availability (who learns what / trainer vs. drop), auction volume and price-history risk.
5. Hosted, multi-user app for TBC Anniversary and Forever: see [docs/HOSTED_PLAN.md](docs/HOSTED_PLAN.md).
