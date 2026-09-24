# CLAUDE.md

Conventions for AI agents working in this repository.

## Project

`wow-profit` is a local Python tool that finds profitable crafting recipes and production chains for **World of Warcraft: Forever**. Items and recipes come from client DB2 tables (wago.tools CSV exports) loaded into SQLite; the user supplies auction house prices; the engine ranks recipes by profit (buy or craft reagents, then sell via vendor, AH minus the 5% cut, or disenchant). See `README.md` for usage and roadmap.

## Layout

- `src/wowprofit/ingest.py` – download DB2 CSVs and load them into SQLite
- `src/wowprofit/engine.py` – pure profit/chain logic (no I/O)
- `src/wowprofit/prices.py` – price sources (CSV import, Auctionator import)
- `src/wowprofit/auctionator.py` – pure parser for Auctionator's SavedVariables (Lua string holding CBOR)
- `src/wowprofit/db.py` – SQLite schema and connection helpers
- `src/wowprofit/store.py` – `load_market(conn)`: SQLite rows to engine dataclasses
- `src/wowprofit/service.py` – web use-cases: `MarketCache`, `search` (profession filter via `engine.recipes_for_professions`, so chains only sub-craft through selected professions), game data update, Auctionator import
- `src/wowprofit/api.py` – FastAPI JSON API (`create_app(db_path, ...)`); also serves the built `frontend/dist`
- `src/wowprofit/cli.py` – argparse command line (`ingest`, `import-prices`, `import-auctionator`, `set-price`, `rank`, `ui`); `ui` runs uvicorn on :8600
- `frontend/` – Vite + React + TypeScript + Mantine + TanStack Query; `src/api/schema.d.ts` is generated from the API's OpenAPI spec
- `scripts/export_openapi.py` – writes `frontend/openapi.json` (input for `npm run gen-types`)
- `data/disenchant.csv` – hand-filled disenchant results (not in DB2)
- `tests/` – pytest; `conftest.py` holds a tiny fake DB2 CSV set shared by tests

## Commands

Use the project venv (`.venv`); do not install packages globally. If it is missing: `python -m venv .venv`, then `.venv\Scripts\python -m pip install -e ".[dev,ui]"`. Front-end packages live in `frontend/node_modules` (`npm ci` in `frontend/`); the root `package.json` only holds dev tooling (`npm ci` in the root).

- `python scripts/check.py` – ruff lint, ruff format check, mypy (strict), pytest, then regenerates the OpenAPI spec and TS types and runs oxlint, vitest and `tsc -b && vite build`. **Run before considering any change done.** Pass `--skip-frontend` for Python-only iteration.
- `ruff check . --fix`, `ruff format .`, `mypy`, `pytest` – individual Python tools; `npm run lint|test|build|dev|gen-types` in `frontend/`.
- Dev loop: `npm run dev` in the repo root runs the API (`scripts/dev-api.mjs`, venv python, :8600) and, once it answers, Vite on :5173, which proxies `/api` to it.

## Conventions

- **Money is integer copper** everywhere (prices, costs, profit), including the JSON API. Format only at the display edge: `format_money` in Python, `formatMoney` in `frontend/src/lib/money.ts`.
- API handlers are plain `def` (FastAPI runs them in a threadpool) and open their own SQLite connection per request; never share a connection across threads.
- After changing API models or routes, regenerate `frontend/openapi.json` and `frontend/src/api/schema.d.ts` (`check.py` does this) and commit both.
- **Keep `engine.py` pure**: no file, DB or network access. Load data in `store.py` and pass plain dataclasses in.
- **Type annotations are required**; mypy runs in strict mode over `src` and `tests`, and the front end uses TypeScript `strict`.
- Prefer red-green-refactor: write a failing test first, then make it pass. Ingest tests use fixture CSVs, never the network. API tests use FastAPI's `TestClient`; front-end tests use vitest + Testing Library with `fetch` stubbed (`frontend/src/test/utils.tsx`).
- Line length is 110; let `ruff format` handle style.

## Data gotchas

- Disenchant results are server-side loot data and are **not** in DB2. Until `data/disenchant.csv` is filled in, disenchant is ignored. Do not invent drop tables.
- DB2 does not say which vendors sell which reagents; vendor prices are entered as ordinary prices.
- `recipes.min_skill` currently comes out as 1 for every real recipe, so do not rely on it. Recipe output count comes from `SpellEffect.EffectBasePointsF` and is only spot-checked.
- Re-running `wowprofit ingest` rebuilds items, recipes and disenchant rows but preserves the `prices` table.
- The pinned build is `DEFAULT_BUILD` in `ingest.py`; `ingest.latest_build()` resolves the newest `wow_classic_beta` build from wago.tools' `/api/builds/latest` JSON. Downloaded CSVs are cached under `cache/` (git-ignored, as is `data/*.db`).
