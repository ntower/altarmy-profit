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
pip install -e ".[dev,ui]"   # drop ,ui if you only want the CLI; add ,hosted for hosted mode (firebase-admin)
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
altarmy-profit watch --server URL --key KEY    # upload the addon files to a hosted site as WoW rewrites them
altarmy-profit ingest --only-if-new            # the newest build, unless already loaded (the hosted daily job)
altarmy-profit migrate                         # migrate the database now (each hosted deploy runs this once)
altarmy-profit prune                           # drop price observations older than 90 days
```

Every command takes `--game-version forever|tbc` (default `forever`) before the command name; it picks the
game's data in the database, the data files under `data/<version>/` and the wago.tools product
(`wow_classic_beta` or `wow_anniversary`).

The database is `data/altarmy-profit.sqlite`; `--db <file>` picks another SQLite file and `DATABASE_URL`
(a SQLAlchemy URL such as `postgresql+psycopg://user:pass@host/db`) another database. Its schema is
migrated automatically (Alembic). The databases of earlier releases (`data/altarmy-profit-<version>.db`,
and the older `data/altarmy-profit.db`) are imported into it the first time a command runs without
`--db` or `DATABASE_URL`, prices, characters and settings included, and kept renamed to `*.imported`.

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
game. It has three tabs:

- **Search** ranks what your characters on the chosen realm and faction can craft, and names who
  crafts each recipe. A switch adds recipes of their professions they have not learned yet. Expand a
  recipe to see its plan as a flow chart or steps. Where a material could come from elsewhere (vendor,
  AH, or a craft), or the output could be sold another way, the node's ⇄ menu lists the options, best
  first. Picking one re-costs the recipe, adding or removing buy, craft and mail steps, and the row
  shows the changed numbers. **Reset** goes back to the best plan. A row's ⋯ menu can mark its output
  **Never sell on auction house**: from then on it is only vendored or disenchanted (it can still be
  bought there).
- **Prices** looks up an auction house's current prices by item name; **history** on a row shows
  Auctionator's daily low, high and quantity for it.
- **Manage** lists the items never sold on the auction house (remove one to allow it again), downloads
  the chosen game's latest data (its newest build on wago.tools; prices are kept) and shows the addon
  files in use.

The UI reads `AltArmy_TBC.lua` and `Auctionator.lua` itself: it finds them under the usual WoW install
folders, in the chosen game's folder (`_classic_beta_` for Forever, `_anniversary_` for TBC; paste
another path on Manage), and re-imports either one whenever
WoW rewrites it, on logout or `/reload`. Prices come from the chosen realm's Auctionator scan; each
auction house keeps its own, so switching realms back and forth loses nothing.

### Local and hosted mode

`ALTARMY_MODE` picks how the server runs (the same code either way):

- `local` (the default): one user, no sign-in, the addon files above are synced. Everything this README
  describes.
- `hosted`: the multi-user web app at https://alt-army-prod.web.app (see `docs/HOSTED_PLAN.md` and
  **Deploy** below). Visitors are signed in with
  Firebase, anonymously at first; a guest sees the Prices tab (items of required level 30 and below) and
  the Upload tab. Linking an email address and password (the header's **Link account**) keeps the same
  user and unlocks Search, Manage and every price; **Sign in** gets back to that account on another
  browser (with **Forgot password?**), and **Sign out** starts a new guest session. Each user has their
  own characters, selection and AH blocks. The server never reads local addon files and has no game data
  download or reload button: data comes in through uploads (below), game data through a daily job. The
  footer's **Privacy** note says what is stored and deletes the account (`DELETE /api/me`). Requests are
  rate-limited per client IP and per user (429). Needs `pip install -e ".[hosted]"`
  and `FIREBASE_PROJECT_ID`, `FIREBASE_API_KEY` and `FIREBASE_AUTH_DOMAIN`.

In hosted mode:

- **Upload** takes `AltArmy_TBC.lua` (replaces your characters of the chosen game) and `Auctionator.lua`
  (adds a scan for every realm in it; everyone's scans fill the same auction houses, the newest price
  wins). Files are parsed on the server, never stored, and limited to 32 MB; the tab lists your recent
  uploads, rejected ones included.
- **Manage → Upload automatically** makes API keys for the watcher (linked accounts only; a key can only
  upload, is shown once, and can be revoked). On the computer you play on, with this package installed:

  ```powershell
  altarmy-profit watch --server https://<site> --key ak_...   # or set ALTARMY_KEY instead of --key
  ```

  It finds both addons' files for both games under the usual WoW folders (`--wow-root` for another),
  uploads the ones WoW rewrote every 15 seconds (`--interval`), and remembers what it sent in
  `~/.altarmy-profit/watch-state.json`. `--once` uploads what changed and exits. It needs no database.

**Firebase project.** `hosted.env` holds the project's public web config (`alt-army-prod`), and
`npm run dev:hosted` runs the dev loop below in hosted mode against it. That creates real users in the
project and keeps them in the local database file next to local mode's user. The project has the
**Anonymous** and **Email/Password** sign-in providers enabled. Its browser API key only calls the Identity
Toolkit and Token Service APIs (sign-in and token refresh) and only from `http://localhost:5173`,
`http://localhost:8600`, the same two on `127.0.0.1`, `alt-army-prod.firebaseapp.com`,
`alt-army-prod.web.app` and the staging channel `alt-army-prod--staging-hn1s06um.web.app` (Google's
referrer patterns take no port wildcard). To serve the front end from another origin, pass the full list
again, since the update replaces it. Firebase adds Hosting channels to Auth's authorized domains by itself;
a custom domain needs adding there too.

```powershell
gcloud services api-keys update 9856a0a7-d9e2-4b98-ad97-543f83f7bb5b --project alt-army-prod `
  --billing-project alt-army-prod `
  --api-target=service=identitytoolkit.googleapis.com --api-target=service=securetoken.googleapis.com `
  --allowed-referrers="http://localhost:5173/*,http://localhost:8600/*,http://127.0.0.1:5173/*,http://127.0.0.1:8600/*,https://alt-army-prod.firebaseapp.com/*,https://alt-army-prod.web.app/*,https://alt-army-prod--staging-hn1s06um.web.app/*,https://<new origin>/*"
```

To try hosted mode without touching the real project, run the Firebase Auth emulator (`firebase.json`;
needs Java 11+) and point the server at it:

```powershell
npx firebase-tools emulators:start --only auth --project demo-altarmy   # in its own terminal
$env:ALTARMY_MODE = "hosted"; $env:FIREBASE_PROJECT_ID = "demo-altarmy"
$env:FIREBASE_AUTH_EMULATOR_HOST = "127.0.0.1:9099"
altarmy-profit ui
```

The browser then signs in against the emulator. Tests never need Firebase: they pass a fake token verifier
to `create_app`.

### Deploy

Hosted mode runs on Google Cloud in `alt-army-prod` (us-central1). The config is in the repo:
`Dockerfile`, `firebase.json` / `firebase.staging.json` (Hosting) and `deploy/`.

| Piece | What |
|-------|------|
| Firebase Hosting | serves `frontend/dist`; `/api/**` rewrites to Cloud Run. Prod is the live site; staging is the `staging` preview channel (https://alt-army-prod--staging-hn1s06um.web.app, expires 30 days after its last deploy) |
| Cloud Run services | `altarmy` (min 0, max 2) and `altarmy-staging` (max 1): the API, 1 vCPU, 1 GiB. Instances never migrate |
| Cloud Run jobs | the same image running the CLI: `altarmy-migrate` (each deploy, before the service), `altarmy-ingest-tbc` / `-forever` (`ingest --only-if-new`), `altarmy-prune`. Staging has `altarmy-staging-migrate` |
| Cloud Scheduler | ingest tbc 09:00 UTC, ingest forever 09:15, prune 10:00, run as `altarmy-scheduler` |
| Cloud SQL | `altarmy-pg`: Postgres 16, db-f1-micro, databases `altarmy` and `altarmy_staging` |
| Secret Manager | `database-url`, `database-url-staging`: each database's `DATABASE_URL` (Cloud Run's Cloud SQL socket) |

About $9 to 11 a month, nearly all of it Cloud SQL; Cloud Run stays in its free tier at hobby traffic.

Deploys come from GitHub Actions (`.github/workflows/deploy.yml`). After `check` passes on a push to main,
it deploys prod; **Run workflow** deploys staging (or prod). It signs in through Workload Identity
Federation and needs two repository variables (Settings → Secrets and variables → Actions → Variables):

- `GCP_WIF_PROVIDER` = `projects/516573536063/locations/global/workloadIdentityPools/github/providers/github-actions`
- `GCP_DEPLOY_SA` = `altarmy-deploy@alt-army-prod.iam.gserviceaccount.com`

By hand (Git Bash, with gcloud and the Firebase CLI signed in; no Docker needed):

```bash
IMAGE=$(BUILDER=cloudbuild deploy/build.sh)   # build on Cloud Build, push to Artifact Registry
deploy/deploy.sh staging "$IMAGE"             # jobs, migrate, service, front end to the staging channel
deploy/deploy.sh prod "$IMAGE"
```

A new database gets its game data from an ingest run: `gcloud run jobs execute altarmy-ingest-tbc --wait`
(prod), or for staging its migrate job with other arguments:
`gcloud run jobs execute altarmy-staging-migrate --args=--game-version,tbc,ingest,--only-if-new,--cache,/tmp/cache`
(add `--region us-central1 --project alt-army-prod --billing-project alt-army-prod` to both).

`deploy/setup.sh` holds the one-time setup, one section per run: APIs, registry, service accounts and
roles, Cloud SQL, each database's user and secret, Workload Identity Federation, and the schedules. Every
command passes `--project alt-army-prod --billing-project alt-army-prod`, so gcloud's defaults don't matter.

### Front-end development

Run `npm run dev` (local mode) or `npm run dev:hosted` (hosted mode, see above) in the repo root. It starts
the Python API on :8600 (`altarmy-profit ui --no-browser`,
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
- `src/altarmy_profit/auth.py`, `users.py` – users and tiers (Firebase token verification in hosted mode,
  the fixed local user otherwise) and each user's settings and sync state
- `src/altarmy_profit/uploads.py`, `watch.py` – uploaded addon files (parse, pool, history, rate limit)
  and the CLI watcher that sends them
- `src/altarmy_profit/store.py` – load the database into engine dataclasses
- `src/altarmy_profit/service.py`, `api.py` – use-cases and the FastAPI JSON API behind the web UI
- `src/altarmy_profit/cli.py` – command line; `ratelimit.py` – hosted mode's per-IP and per-user limits
- `Dockerfile`, `firebase.json`, `deploy/`, `.github/workflows/deploy.yml` – the hosted deploy (see Deploy)
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
