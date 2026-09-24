# altarmy-profit

Local tool that finds profitable crafting recipes and production chains for **WoW: Forever** and
**TBC Anniversary**, the two clients the Alt Army addon runs on. Both share one database.

- Items and recipes come from the client's DB2 tables (via [wago.tools](https://wago.tools/) CSV exports) into a local SQLite file
  (or Postgres, for the planned hosted app).
- Auction house prices come from Auctionator's SavedVariables, a CSV or by hand, per auction house, with history.
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

Tests run on SQLite. To run them on Postgres too, point `TEST_DATABASE_URL` at a **throwaway** database
(its `public` schema is dropped), e.g. with a local PostgreSQL install:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/altarmy_test"; pytest
```

GitHub Actions (`.github/workflows/check.yml`) runs `check.py` and the Postgres suite on every push.

## Usage

```powershell
altarmy-profit ingest                          # downloads DB2 tables into cache/, loads WoW: Forever's game data
altarmy-profit ingest --build latest           # same, for the newest WoW: Forever build on wago.tools
altarmy-profit --game-version tbc ingest       # TBC Anniversary's instead
altarmy-profit import-prices prices.csv        # columns: item_id (or name), price   (copper)
altarmy-profit import-auctionator "<WoW>\_classic_beta_\WTF\Account\<account>\SavedVariables\Auctionator.lua"
altarmy-profit import-altarmy "<WoW>\_classic_beta_\WTF\Account\<account>\SavedVariables\AltArmy_TBC.lua"
altarmy-profit set-price 2589 250              # one item, copper
altarmy-profit rank --top 25 --realm "Classic Beta PvE" --faction Horde   # remembered; --include-unlearned
altarmy-profit ui                              # web UI on http://127.0.0.1:8600 (--port, --no-browser)
```

Every command takes `--game-version forever|tbc` (default `forever`) before the command name; it picks the
game's data in the database, the data files under `data/<version>/` and the wago.tools product
(`wow_classic_beta` or `wow_anniversary`).

The database is `data/altarmy-profit.sqlite`; `--db <file>` picks another SQLite file and `DATABASE_URL`
(a SQLAlchemy URL such as `postgresql+psycopg://user:pass@host/db`) another database. Its schema is
migrated automatically (Alembic). The databases of earlier releases (`data/altarmy-profit-<version>.db`,
and the older `data/altarmy-profit.db`) are imported into it the first time a command runs without
`--db`, prices, characters and settings included, and kept renamed to `*.imported`.

`import-auctionator` reads Auctionator's **account-wide** SavedVariables file (not the per-character
one) and records the realm's scan for its auction house: each item's latest minimum buyout, plus
Auctionator's per-day history (high, low and quantity available). WoW writes SavedVariables on logout
or `/reload`, so do one of those after scanning. Add `--realm "<name>"` if the file holds several
realms (the error lists them). Items missing from a scan keep their previous price.

Prices belong to an auction house: a realm and faction (one shared by both factions where the auction
house is, as on Forever). `import-prices` and `set-price` price the selected realm's auction house, or,
before any characters are imported, an unnamed one. The newest price per item wins, whatever its
source; older prices stay as history (see Data notes).

`import-altarmy` reads the [Alt Army](../altarmy_tbc) addon's account-wide SavedVariables: your
characters, their professions and the recipes they have learned. `rank` then only ranks what the
characters of one realm and faction can craft (chains may use any of their recipes, whoever knows them).

The web UI is a React app (`frontend/`) served by a local FastAPI server (`altarmy-profit ui`); build
it once with `npm run build` in `frontend/`. A switch in the header picks the game (WoW: Forever or TBC
Anniversary); everything below it, including characters, prices and settings on Manage, belongs to that
game. It has two tabs:

- **Search** ranks what your characters on the chosen realm and faction can craft, and names who
  crafts each recipe. A switch adds recipes of their professions they have not learned yet. Expand a
  recipe to see its plan as a flow chart or steps. Where a material could come from elsewhere (vendor,
  AH, or a craft), or the output could be sold another way, the node's ⇄ menu lists the options, best
  first. Picking one re-costs the recipe, adding or removing buy, craft and mail steps, and the row
  shows the changed numbers. **Reset** goes back to the best plan. A row's ⋯ menu can mark its output
  **Never sell on auction house**: from then on it is only vendored or disenchanted (it can still be
  bought there).
- **Manage** lists the items never sold on the auction house (remove one to allow it again), downloads
  the chosen game's latest data (its newest build on wago.tools; prices are kept) and shows the addon
  files in use.

The UI reads `AltArmy_TBC.lua` and `Auctionator.lua` itself: it finds them under the usual WoW install
folders, in the chosen game's folder (`_classic_beta_` for Forever, `_anniversary_` for TBC; paste
another path on Manage), and re-imports either one whenever
WoW rewrites it, on logout or `/reload`. Prices come from the chosen realm's Auctionator scan; each
auction house keeps its own, so switching realms back and forth loses nothing.

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

- Pinned builds: `default_build` per version in `src/altarmy_profit/versions.py`. Pass `--build <version>`
  or `--build latest` for a newer one. The build actually loaded is stored in the `game_versions` table.
- **Price history.** Every import is a snapshot (`price_snapshots`); it records observations only for
  items whose price or last-seen day moved (`price_observations`, pruned after 90 days) and updates
  `price_current`, which the ranking reads. Auctionator's per-day high/low/available go to `price_daily`,
  which is kept indefinitely (Auctionator itself forgets old days).
- **Disenchant results are not in DB2** (they are server-side loot tables). `data/<version>/disenchant.csv`
  (`item_class,quality,min_ilvl,max_ilvl,result_item_id,chance,min_count,max_count`) holds the rates.
  Forever's are Classic-era rates, derived from the brackets Auctionator uses for Classic clients, and
  cover greens ilvl 5–65, blues 11–65, epics 40–80. Counts within a row are assumed uniform.
  Forever-specific rates are not yet published — verify against Wowhead's Forever database as data comes
  in, then re-run `altarmy-profit ingest`. TBC's are generated from the TBC client's Auctionator
  (one row per count) by `python scripts/build_disenchant.py`.
- **Vendor-sold items are not in DB2** (vendor inventories are server-side). `data/<version>/vendor_items.csv`
  (`item_id,name`) lists the items vendors sell with unlimited stock and no reputation or event condition
  (TBC: and no honor or badge cost), taken from [vmangos](https://github.com/vmangos/core)' vanilla world
  database for Forever and [cmangos](https://github.com/cmangos/tbc-db)' for TBC by
  `python scripts/build_vendor_items.py --game-version forever|tbc`. The price is DB2's `BuyPrice` per
  `VendorStackCount`, rounded up to whole copper. Reagents are bought from whichever of vendor and AH is
  cheaper. Forever may differ from vanilla; edit the CSV and re-run `altarmy-profit ingest` if a vendor
  item is missing or wrong.
- Recipe output count comes from `SpellEffect.EffectBasePointsF` (Forever) or `EffectBasePoints` plus the
  average `EffectDieSides` roll (TBC); see `ingest.output_count`.

## Layout

- `src/altarmy_profit/versions.py` – the game versions (TBC Anniversary, Forever): data files,
  wago.tools product, WoW flavor folder, AH cut and postage
- `src/altarmy_profit/db.py`, `schema.py`, `migrations/` – the database (SQLAlchemy Core, SQLite or
  Postgres), its tables and Alembic migrations; `legacy.py` imports older releases' SQLite files
- `src/altarmy_profit/ingest.py` – download + load DB2 CSVs
- `src/altarmy_profit/engine.py` – pure profit/chain logic (no I/O), covered by `tests/`
- `src/altarmy_profit/prices.py` – the price store (auction houses, snapshots, current and daily prices)
  and its sources (CSV, Auctionator SavedVariables via `auctionator.py`)
- `src/altarmy_profit/altarmy.py` – characters and learned recipes from Alt Army's SavedVariables (`luasv.py` parses them)
- `src/altarmy_profit/store.py` – load the database into engine dataclasses
- `src/altarmy_profit/service.py`, `api.py` – use-cases and the FastAPI JSON API behind the web UI
- `src/altarmy_profit/cli.py` – command line
- `src/altarmy_profit/vmangos.py`, `cmangos.py`, `disenchant_rates.py` – sources for the hand data files
- `scripts/bench_rank.py` (ranking timings), `scripts/probe_blizzard_api.py` (Blizzard AH API check)
- `frontend/` – Vite + React + TypeScript + Mantine web UI
- `docs/` – plans: `HOSTED_PLAN.md` (hosted, multi-user transition), `ROADMAP_IDEAS.md` (feature ideas)

## Roadmap

1. Verify ingest against known recipes on a real build.
2. ~~Auctionator SavedVariables importer~~ (done: `altarmy-profit import-auctionator`).
3. ~~Web UI~~ (done: `altarmy-profit ui`, React + FastAPI). Next: filter by skill level, which needs real required-skill data.
4. Recipe availability (who learns what / trainer vs. drop), auction volume and price-history risk.
5. Hosted, multi-user app for TBC Anniversary and Forever: see [docs/HOSTED_PLAN.md](docs/HOSTED_PLAN.md).
